"""
nethack_harness.refiner
====================

Continual-Harness Refiner (arXiv:2605.09998).

Every `refine_interval` turns, a Refiner reads the recent trajectory window
and emits CRUD edits over four harness components:

* prompt addendum `p` — text appended to the system message
* sub-agents `G` — named directive snippets injected on a state trigger
* skills `K` — named *macros* (ordered sequences of existing skill calls)
* memory `M` — the existing `Journal` (notes + objective)

Two implementations:

* `OfflineRefiner` — deterministic no-op; for tests + when no API key set.
* `TeacherLLMRefiner` — calls a configured chat-completions endpoint.

The Refiner NEVER raises into the rollout. Errors are logged and swallowed
(same pattern as `belief_state` summarization in nethack.py — losing a
refinement window is fine; killing the rollout is not).

Why a separate teacher model (paper: process-reward co-learning)?
    The intent of the paper is that a frontier model (Opus/GPT-class) refines
    a weaker open-source agent's harness mid-rollout. Using the same model
    for both rolls and refinement collapses to "ask yourself to think
    harder" — which is approximately what variant=P already did and
    didn't beat B1 on wave-1.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

log = logging.getLogger(__name__)


# ---------- edit payloads ----------


@dataclass
class SubagentSpec:
    """Named directive that fires when `trigger` is True against structured_obs.

    `trigger` is a small DSL string of the form `<field><op><value>`:
        "hp_pct<0.4"       — current HP < 40% of max
        "depth>=4"         — dungeon level at least 4
        "hostile_count>0"  — any visible hostile
        "always"           — fires every turn (use sparingly)

    The evaluator is intentionally limited to a handful of fields so a
    refiner can't accidentally exfiltrate state into arbitrary Python.
    """
    trigger: str
    text: str


@dataclass
class MacroStep:
    skill: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefinerEdits:
    """One refinement window's CRUD payload.

    Each component uses `*_set` for create-or-update and `*_delete` for
    remove. The prompt addendum is a full replacement (single string).
    Journal ops use the existing add_note / pin_objective semantics.
    """
    prompt_addendum: Optional[str] = None  # None = leave unchanged
    subagents_set: dict[str, SubagentSpec] = field(default_factory=dict)
    subagents_delete: list[str] = field(default_factory=list)
    skills_set: dict[str, list[MacroStep]] = field(default_factory=dict)
    skills_delete: list[str] = field(default_factory=list)
    notes_set: dict[str, str] = field(default_factory=dict)
    notes_delete: list[str] = field(default_factory=list)
    objective: Optional[str] = None  # None = leave unchanged

    def is_noop(self) -> bool:
        return (
            self.prompt_addendum is None
            and not self.subagents_set and not self.subagents_delete
            and not self.skills_set and not self.skills_delete
            and not self.notes_set and not self.notes_delete
            and self.objective is None
        )

    def to_trace_dict(self) -> dict:
        return {
            "prompt_addendum": self.prompt_addendum,
            "subagents_set": {k: {"trigger": v.trigger, "text": v.text} for k, v in self.subagents_set.items()},
            "subagents_delete": self.subagents_delete,
            "skills_set": {k: [{"skill": s.skill, "args": s.args} for s in v] for k, v in self.skills_set.items()},
            "skills_delete": self.skills_delete,
            "notes_set": self.notes_set,
            "notes_delete": self.notes_delete,
            "objective": self.objective,
        }


# ---------- Refiner protocol + implementations ----------


class Refiner(Protocol):
    def refine(self, *, window: list[dict], components: dict) -> RefinerEdits:
        """Return CRUD edits given the recent trajectory window.

        `window` is a list of {"role": str, "content": str} dicts (the last
        N turns of chat). `components` is a snapshot of the current harness
        state: {"prompt_addendum": str, "subagents": {...}, "skills": {...},
        "notes": {...}, "objective": str|None}.
        """
        ...


class OfflineRefiner:
    """No-op refiner. Used in tests and when no teacher model is configured."""

    def refine(self, *, window: list[dict], components: dict) -> RefinerEdits:
        return RefinerEdits()


_TEACHER_SYSTEM_PROMPT = """You are the Refiner in a Continual-Harness setup (arXiv:2605.09998).
A weaker agent is playing NetHack via a fixed skill API. Every refinement window
you read the agent's recent turns and emit CRUD edits over four components:

  - prompt_addendum: a short addendum (<=400 chars) appended to the agent's system prompt
  - subagents: named directives (<=200 chars each) that fire on a trigger like
    "hp_pct<0.4", "depth>=N", "hostile_count>0", or "always"
  - skills: named MACROS, i.e. ordered lists of existing skill calls (no model-authored code)
  - notes: keyed journal entries (the agent's persistent memory)

Respond with STRICT JSON only, matching this schema:
{
  "prompt_addendum": string | null,    // null = no change
  "subagents_set": { "<name>": {"trigger": "<expr>", "text": "<directive>"} },
  "subagents_delete": [ "<name>" ],
  "skills_set": { "<name>": [ {"skill": "<existing_skill>", "args": {...}}, ... ] },
  "skills_delete": [ "<name>" ],
  "notes_set": { "<key>": "<text>" },
  "notes_delete": [ "<key>" ],
  "objective": string | null
}

Be conservative: most fields should be empty most windows. Only edit when the
trajectory shows a concrete failure mode (navigation loop, repeated tool
error, stalled descent). Never invent state — only summarize what the window
shows."""


class TeacherLLMRefiner:
    """Calls an OpenAI-style chat completions endpoint with the configured model.

    Supports both Anthropic (api.anthropic.com via chat-completions-compatible
    proxy) and any OAI-compatible endpoint. Configure via env vars:

      REFINER_BASE_URL  (default: https://api.anthropic.com/v1)
      REFINER_API_KEY   (default: ANTHROPIC_API_KEY)
      REFINER_TIMEOUT_S (default: 30)
    """

    def __init__(self, model: str, *, base_url: Optional[str] = None,
                 api_key: Optional[str] = None, timeout_s: float = 30.0,
                 max_window_chars: int = 8000) -> None:
        self.model = model
        self.base_url = base_url or os.getenv("REFINER_BASE_URL")
        self.api_key = api_key or os.getenv("REFINER_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        self.timeout_s = float(os.getenv("REFINER_TIMEOUT_S", timeout_s))
        self.max_window_chars = max_window_chars

    def refine(self, *, window: list[dict], components: dict) -> RefinerEdits:
        if not self.api_key:
            log.warning("TeacherLLMRefiner: no api key; returning no-op edits")
            return RefinerEdits()
        try:
            window_text = _format_window(window, self.max_window_chars)
            comp_text = json.dumps(components, indent=2, default=str)[:4000]
            user_msg = (
                f"=== Current harness components ===\n{comp_text}\n\n"
                f"=== Recent trajectory window ===\n{window_text}\n\n"
                f"Emit JSON edits per the schema."
            )
            raw = self._call_chat(user_msg)
            return _parse_edits(raw)
        except Exception as e:
            log.warning("TeacherLLMRefiner.refine failed: %s", e)
            return RefinerEdits()

    def _call_chat(self, user_msg: str) -> str:
        # Lazy import so the module imports cleanly without network deps.
        try:
            import anthropic  # type: ignore
        except ImportError:
            anthropic = None  # type: ignore

        if anthropic is not None and self.model.startswith("claude"):
            client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
            resp = client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=_TEACHER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                timeout=self.timeout_s,
            )
            # Pull text from the first content block.
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    return block.text
            return ""

        # OAI-compatible fallback.
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _TEACHER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            timeout=self.timeout_s,
        )
        return resp.choices[0].message.content or ""


# ---------- helpers ----------


def _format_window(window: list[dict], max_chars: int) -> str:
    """Cheap textification of the last-N turns. Keeps tail; head gets elided."""
    lines = []
    total = 0
    for msg in reversed(window):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            # multimodal — flatten to text where possible
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        line = f"[{role}] {content}"
        if total + len(line) > max_chars:
            lines.append(f"[... {len(window) - len(lines)} earlier turns elided ...]")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(reversed(lines))


def _parse_edits(raw: str) -> RefinerEdits:
    """Parse model JSON output into a validated RefinerEdits. Permissive: any
    structurally wrong field is dropped to a no-op rather than raising."""
    if not raw:
        return RefinerEdits()
    # Strip code fences if the model wrapped JSON in ```json ... ```
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract a JSON object from anywhere in the text.
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return RefinerEdits()
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return RefinerEdits()
    if not isinstance(data, dict):
        return RefinerEdits()

    def _str_or_none(x):
        return x if isinstance(x, str) and x.strip() else None

    edits = RefinerEdits(
        prompt_addendum=_str_or_none(data.get("prompt_addendum")),
        objective=_str_or_none(data.get("objective")),
    )

    for name, spec in (data.get("subagents_set") or {}).items():
        if not isinstance(spec, dict): continue
        trig = spec.get("trigger"); text = spec.get("text")
        if not (isinstance(name, str) and isinstance(trig, str) and isinstance(text, str)):
            continue
        edits.subagents_set[name] = SubagentSpec(trigger=trig.strip(), text=text.strip()[:400])
    for name in (data.get("subagents_delete") or []):
        if isinstance(name, str):
            edits.subagents_delete.append(name)

    for name, steps in (data.get("skills_set") or {}).items():
        if not (isinstance(name, str) and isinstance(steps, list)): continue
        parsed_steps = []
        for s in steps:
            if not isinstance(s, dict): continue
            sk = s.get("skill")
            if not isinstance(sk, str): continue
            args = s.get("args", {})
            if not isinstance(args, dict): args = {}
            parsed_steps.append(MacroStep(skill=sk, args=args))
        if parsed_steps:
            edits.skills_set[name] = parsed_steps
    for name in (data.get("skills_delete") or []):
        if isinstance(name, str):
            edits.skills_delete.append(name)

    for k, v in (data.get("notes_set") or {}).items():
        if isinstance(k, str) and isinstance(v, str):
            edits.notes_set[k] = v
    for k in (data.get("notes_delete") or []):
        if isinstance(k, str):
            edits.notes_delete.append(k)

    return edits


# Trigger DSL — kept tiny on purpose. See SubagentSpec docstring.
_TRIGGER_OPS = ("<=", ">=", "<", ">", "==", "!=")


def trigger_fires(trigger: str, structured_obs) -> bool:
    """Evaluate `trigger` against a structured_obs. Unknown fields/operators
    return False (fail-closed)."""
    if not trigger:
        return False
    t = trigger.strip()
    if t.lower() == "always":
        return True
    op = next((o for o in _TRIGGER_OPS if o in t), None)
    if op is None:
        return False
    lhs, rhs = t.split(op, 1)
    lhs = lhs.strip(); rhs = rhs.strip()
    try:
        rhs_val = float(rhs)
    except ValueError:
        return False
    actual = _read_obs_field(lhs, structured_obs)
    if actual is None:
        return False
    try:
        a = float(actual)
    except (TypeError, ValueError):
        return False
    if op == "<": return a < rhs_val
    if op == ">": return a > rhs_val
    if op == "<=": return a <= rhs_val
    if op == ">=": return a >= rhs_val
    if op == "==": return a == rhs_val
    if op == "!=": return a != rhs_val
    return False


def _read_obs_field(name: str, structured_obs) -> Optional[float]:
    if structured_obs is None:
        return None
    status = getattr(structured_obs, "status", {}) or {}
    if name == "hp":
        return status.get("hitpoints")
    if name == "hp_max":
        return status.get("max_hitpoints")
    if name == "hp_pct":
        hp = status.get("hitpoints"); mx = status.get("max_hitpoints")
        if hp is None or not mx:
            return None
        return float(hp) / float(mx)
    if name == "depth":
        return status.get("depth")
    if name == "hostile_count":
        hostiles = getattr(structured_obs, "hostiles", None)
        if hostiles is None:
            return 0.0
        try:
            return float(len(hostiles))
        except TypeError:
            return 0.0
    if name == "turn":
        return status.get("time")
    return None


# ---------- application ----------


def apply_edits(state: dict, edits: RefinerEdits) -> dict:
    """Mutate state in place per the edits. Returns a small dict summarizing
    what was applied (for tracing). Never raises."""
    applied = {"prompt": False, "subagents": 0, "skills": 0, "notes": 0, "objective": False}

    if edits.prompt_addendum is not None:
        state["_ch_prompt_addendum"] = edits.prompt_addendum.strip()[:1200]
        applied["prompt"] = True

    subagents = state.setdefault("_ch_subagents", {})
    for name, spec in edits.subagents_set.items():
        subagents[name] = {"trigger": spec.trigger, "text": spec.text}
        applied["subagents"] += 1
    for name in edits.subagents_delete:
        if subagents.pop(name, None) is not None:
            applied["subagents"] += 1

    skills = state.setdefault("_ch_skills", {})
    for name, steps in edits.skills_set.items():
        # Validate skill names against the live registry to refuse macros
        # that compose unknown / mis-spelled skill names.
        try:
            from nethack_harness.tools.skills import registry as _reg
            valid = set(_reg.all_schemas().keys())
        except Exception:
            valid = set()
        clean_steps = [{"skill": s.skill, "args": s.args} for s in steps if not valid or s.skill in valid]
        if clean_steps:
            skills[name] = clean_steps
            applied["skills"] += 1
    for name in edits.skills_delete:
        if skills.pop(name, None) is not None:
            applied["skills"] += 1

    journal = state.get("journal")
    if journal is not None:
        for k, v in edits.notes_set.items():
            try:
                journal.add_note(k, v)
                applied["notes"] += 1
            except Exception:
                pass
        for k in edits.notes_delete:
            if journal.notes.pop(k.strip().lower(), None) is not None:
                applied["notes"] += 1
        if edits.objective is not None:
            try:
                journal.pin_objective(edits.objective)
                applied["objective"] = True
            except Exception:
                pass

    return applied


# ---------- bootstrap I/O ----------


def snapshot_components(state: dict) -> dict:
    """Serialize the four CH components to a JSON-safe dict."""
    journal = state.get("journal")
    return {
        "prompt_addendum": state.get("_ch_prompt_addendum", ""),
        "subagents": dict(state.get("_ch_subagents", {})),
        "skills": dict(state.get("_ch_skills", {})),
        "notes": dict(journal.notes) if journal is not None else {},
        "objective": (journal.objective if journal is not None else None),
    }


def load_components(state: dict, data: dict) -> None:
    """Restore CH components into state. Journal notes/objective are merged
    into the existing Journal so tier-pinned objectives survive."""
    if not isinstance(data, dict):
        return
    if isinstance(data.get("prompt_addendum"), str):
        state["_ch_prompt_addendum"] = data["prompt_addendum"]
    if isinstance(data.get("subagents"), dict):
        state["_ch_subagents"] = {k: v for k, v in data["subagents"].items() if isinstance(v, dict)}
    if isinstance(data.get("skills"), dict):
        state["_ch_skills"] = {k: v for k, v in data["skills"].items() if isinstance(v, list)}
    journal = state.get("journal")
    if journal is not None:
        for k, v in (data.get("notes") or {}).items():
            if isinstance(k, str) and isinstance(v, str):
                try:
                    journal.add_note(k, v)
                except Exception:
                    pass
        obj = data.get("objective")
        if isinstance(obj, str) and obj.strip():
            # Only override if no tier-pinned objective is present.
            if not journal.objective:
                journal.pin_objective(obj)
