"""Code-edit proposer: ask GLM-5 for anchored search/replace edits to ONE
whitelisted harness file.

Unlike `proposer.LLMProposer` (which mutates env-ARGS + bootstrap JSON), this
proposer asks the model for a small list of EXACT {old, new} snippet edits to a
single source file under the harness, implementing one focused improvement to
the TOOLING or OBSERVATION layer. The game engine is never in scope.

Why search/replace (not a full-file rewrite): full-file rewrites of large files
(skills.py ~1700 lines) either truncate (invalid JSON) or subtly corrupt the
file (tests fail). Anchored edits emit only the small changed regions, so they
are reliable on files of any size and cannot accidentally rewrite the rest of
the file.

Contract:
  - Input: a PROBLEM BRIEF, a target file's relative path, and its FULL current
    contents (with line numbers for the model's reference).
  - Model output: STRICT JSON {"edits": [{"old": <exact snippet>, "new": <repl>},
    ...], "summary": <one line>}. Each `old` must be an EXACT substring of the
    current file occurring EXACTLY ONCE.
  - We apply the edits locally (verifying the exact-once match) and return a
    `CodeEdit` whose `.content` is the full new file — so the caller's apply +
    `git diff --name-only` guard logic is unchanged (still exactly one path).

On ANY failure (no creds, network error, bad JSON, truncation, an `old` that is
missing or ambiguous, or a no-op) the proposer returns None and the caller
REJECTS the iteration — it never crashes the loop and never applies a degenerate
or partially-matched edit.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


# The ONLY files the loop is allowed to edit. Paths are relative to the repo
# (worktree) root. This list is the single source of truth for the whitelist;
# `auto_improve.py` imports it for the hard post-apply guard.
WHITELIST: tuple[str, ...] = (
    "environments/nethack/nethack_harness/tools/skills.py",
    "environments/nethack/nethack_harness/tools/code_mode.py",
    "environments/nethack/nethack_harness/prompt/rendering.py",
    "environments/nethack/nethack_harness/prompt/prompt_spec.py",
    "environments/nethack/nethack_harness/prompt/map_encoders.py",
    "environments/nethack/nethack_harness/navigation/pathfinding.py",
)

# Anything that touches these prefixes is the FROZEN game engine and may never
# be written by the loop. Used as a defence-in-depth check in addition to the
# positive whitelist.
ENGINE_PREFIXES: tuple[str, ...] = (
    "third_party/",
    "nethack_core/",
    "environments/nethack/nethack_core/",
)
# Filenames that are engine-binding glue and off-limits even though they sit
# inside the otherwise-editable package tree.
ENGINE_FILES: tuple[str, ...] = (
    "_engine.py",
    "engine_env.py",
    "engine_binding.py",
)


_SYSTEM_PROMPT = (
    "You are improving the HARNESS around a FROZEN NetHack game engine. You may "
    "edit exactly ONE Python source file via anchored search/replace edits. You "
    "must NOT change the game engine, the environment's reward, or any public "
    "function signature that the rest of the harness imports — only improve the "
    "TOOLING or OBSERVATION/PROMPT behavior implemented inside this one file. "
    "Make ONE focused, self-contained improvement that targets the stated "
    "bottleneck while preserving all existing imports, public names, and call "
    "signatures so the package still imports and all tests still pass.\n\n"
    "Return STRICT JSON only (no markdown fences) with keys:\n"
    '  "edits": a list of {"old": <string>, "new": <string>} objects, where each '
    '"old" is an EXACT substring copied verbatim from the current file '
    "(including indentation and newlines) that occurs EXACTLY ONCE, and \"new\" is "
    "its replacement. Keep each `old` snippet small but large enough (include "
    "surrounding lines) to be unique. Use 1-4 edits.\n"
    '  "summary": a one-line description of the change.\n'
    "Do NOT return the whole file. Do NOT invent code that references undefined "
    "names. If you add a new helper, include it via an edit that anchors on "
    "nearby existing code."
)


def is_whitelisted(rel_path: str) -> bool:
    """True iff `rel_path` (relative to the worktree root, forward slashes) is an
    allowed edit target AND is not an engine path/file."""
    rel = rel_path.replace("\\", "/").lstrip("./")
    if rel not in WHITELIST:
        return False
    if any(rel.startswith(p) for p in ENGINE_PREFIXES):
        return False
    if any(rel.endswith("/" + f) or rel == f for f in ENGINE_FILES):
        return False
    return True


@dataclass
class CodeEdit:
    """A proposed full-file replacement for one whitelisted target (computed by
    applying the model's anchored edits to the current file)."""

    target: str       # relative path under the worktree
    content: str      # full new file body (after applying the edits)
    summary: str      # one-line change description
    n_edits: int = 0  # how many anchored edits were applied


def _resolve_creds() -> dict[str, Optional[str]]:
    api_key = (
        os.getenv("REFINER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("PI_API_KEY")
    )
    base_url = os.getenv("REFINER_BASE_URL")
    return {"base_url": base_url, "api_key": api_key}


def _number_lines(src: str) -> str:
    return "\n".join(f"{i+1:5d}| {ln}" for i, ln in enumerate(src.splitlines()))


def _build_user_msg(problem: str, target: str, current: str) -> str:
    return "\n".join([
        "PROBLEM BRIEF (the current bottleneck to target):",
        problem.strip(),
        "",
        f"TARGET FILE (you may ONLY edit this one file): {target}",
        "",
        "CURRENT CONTENTS (line numbers are for your reference only — do NOT "
        "include the 'N| ' prefix in your `old`/`new` strings):",
        "<<<FILE",
        _number_lines(current),
        "FILE>>>",
        "",
        'Return STRICT JSON: {"edits": [{"old": "...", "new": "..."}], "summary": "..."}',
    ])


def apply_edits(current: str, edits: list) -> Optional[str]:
    """Apply anchored {old,new} edits to `current`. Each `old` must occur EXACTLY
    once. Returns the new content, or None if any edit is malformed, missing, or
    ambiguous (so the caller rejects the iteration)."""
    if not isinstance(edits, list) or not edits:
        return None
    out = current
    for e in edits:
        if not isinstance(e, dict):
            return None
        old = e.get("old")
        new = e.get("new")
        if not isinstance(old, str) or not isinstance(new, str) or old == "":
            return None
        count = out.count(old)
        if count != 1:
            # not found, or ambiguous → unsafe to apply
            return None
        out = out.replace(old, new, 1)
    if out == current:
        return None
    return out


class CodeProposer:
    """GLM-5 (default) anchored-edit proposer over the Prime Inference
    OpenAI-compatible endpoint. Returns a CodeEdit or None (never raises)."""

    def __init__(
        self,
        model: str = "z-ai/glm-5",
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: float = 180.0,
    ) -> None:
        creds = _resolve_creds()
        self.model = model
        self.base_url = base_url or creds["base_url"]
        self.api_key = api_key or creds["api_key"]
        self.timeout_s = float(os.getenv("REFINER_TIMEOUT_S", timeout_s))

    def propose(self, problem: str, target: str, current: str) -> Optional[CodeEdit]:
        if not self.api_key:
            return None
        msgs = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_msg(problem, target, current)},
        ]
        # Up to 2 attempts: the second is a repair pass if the first edit applied
        # but produced syntactically-invalid Python (the most common LLM edit
        # failure — wrong indentation in the `new` block).
        for attempt in range(2):
            try:
                raw, finish = self._call_messages(msgs)
                if finish == "length":
                    return None
                data = json.loads(raw)
            except Exception:
                return None
            if not isinstance(data, dict):
                return None
            edits = data.get("edits")
            new_content = apply_edits(current, edits)
            if new_content is None:
                # An `old` didn't match (often whitespace) — ask once for a retry.
                if attempt == 0:
                    msgs.append({"role": "assistant", "content": raw})
                    msgs.append({"role": "user", "content": (
                        "At least one `old` snippet did not match the file EXACTLY "
                        "once (copy it verbatim including indentation), or the edit "
                        "list was empty. Return corrected JSON edits.")})
                    continue
                return None
            err = _syntax_error(new_content, target)
            if err is not None:
                if attempt == 0:
                    msgs.append({"role": "assistant", "content": raw})
                    msgs.append({"role": "user", "content": (
                        f"Your edit produced invalid Python: {err}. The most likely "
                        "cause is wrong indentation in a `new` block. Return "
                        "corrected JSON edits that compile.")})
                    continue
                return None
            summary = data.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                summary = "(no summary provided)"
            return CodeEdit(
                target=target,
                content=new_content,
                summary=summary.strip(),
                n_edits=len(edits),
            )
        return None

    def _call_messages(self, messages: list) -> tuple[str, str]:
        from openai import OpenAI  # lazy import, mirrors refiner

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=16000,
            timeout=self.timeout_s,
        )
        choice = resp.choices[0]
        return (choice.message.content or "", choice.finish_reason or "")


def _syntax_error(content: str, target: str) -> Optional[str]:
    """Return a short error string if `content` is not valid Python, else None.
    Only enforced for .py targets."""
    if not target.endswith(".py"):
        return None
    try:
        compile(content, target, "exec")
        return None
    except SyntaxError as e:  # noqa: PERF203
        return f"{e.msg} (line {e.lineno})"
    except Exception as e:  # noqa: BLE001
        return str(e)[:120]
