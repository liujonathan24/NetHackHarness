"""Synthesize TraceTurn lists from legacy `prime eval samples` JSON files.

Older runs (anything in `experiments/results/wave2/` and earlier) predate the
NDJSON trace writer — they only carry `samples[].completion` and `samples[].prompt`.
We reconstruct what we can:

  - `assistant_message` + `tool_calls`  : direct from completion[i] when role=='assistant'
  - `rendered_user_message`             : direct from the preceding user / tool message
  - `raw_grid`                          : best-effort parse of the `=== MAP ===` block
  - `status`                            : best-effort regex on the `=== STATUS ===` block
  - `turn`                              : extracted from status.Turn when present, else index

When the LLM view is all you have, that's fine — it's better than a blank screen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.launchpad.types import ToolCallRecord, TraceTurn

_MAP_BLOCK = re.compile(r"===\s*MAP\s*===\s*\n(.*?)(?=\n===|\Z)", re.DOTALL)
_STATUS_BLOCK = re.compile(r"===\s*STATUS\s*===\s*\n(.*?)(?=\n===|\Z)", re.DOTALL)
_STATUS_KV = re.compile(r"(HP|AC|Dlvl|Turn|XP|\$|Pos|Character)\s*:\s*([^\s][^\n]*?)(?:\s{2,}|\n|$)")
_HP_FRAC = re.compile(r"(\d+)\s*/\s*(\d+)")


def _parse_map(user_msg: str) -> list[str]:
    m = _MAP_BLOCK.search(user_msg)
    if not m:
        return []
    block = m.group(1).rstrip("\n")
    return [line.rstrip() for line in block.split("\n")]


def _parse_status(user_msg: str) -> dict[str, Any]:
    m = _STATUS_BLOCK.search(user_msg)
    if not m:
        return {}
    block = m.group(1)
    out: dict[str, Any] = {}
    for key, val in _STATUS_KV.findall(block):
        val = val.strip()
        if key == "HP":
            frac = _HP_FRAC.search(val)
            if frac:
                out["hp"] = int(frac.group(1))
                out["max_hp"] = int(frac.group(2))
            continue
        if key == "Dlvl":
            try:
                out["dlvl"] = int(val.split()[0])
            except (ValueError, IndexError):
                pass
            continue
        if key == "Turn":
            try:
                out["turn"] = int(val.split()[0])
            except (ValueError, IndexError):
                pass
            continue
        if key == "AC":
            try:
                out["ac"] = int(val.split()[0])
            except (ValueError, IndexError):
                pass
            continue
        if key == "$":
            try:
                out["gold"] = int(val.split()[0])
            except (ValueError, IndexError):
                pass
            continue
        out[key.lower()] = val
    return out


def _normalize_tool_calls(raw: Any) -> list[ToolCallRecord]:
    if not raw:
        return []
    out: list[ToolCallRecord] = []
    for tc in raw:
        if isinstance(tc, str):
            try:
                tc = json.loads(tc)
            except json.JSONDecodeError:
                continue
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name") if isinstance(fn, dict) else None
        args = fn.get("arguments") if isinstance(fn, dict) else None
        name = name or tc.get("name")
        args = args or tc.get("arguments")
        if isinstance(args, dict):
            args = json.dumps(args)
        out.append(ToolCallRecord(name=name, arguments=args))
    return out


def is_legacy_samples_file(path: Path) -> bool:
    """Cheap structural check: top-level dict with `samples` key."""
    try:
        with path.open("r", encoding="utf-8") as f:
            head = f.read(512)
    except OSError:
        return False
    return path.suffix == ".json" and '"samples"' in head


def read_legacy_samples(path: Path, sample_idx: int = 0) -> list[TraceTurn]:
    """Build a TraceTurn list from one sample inside a prime-eval samples JSON.

    Each (user, assistant) message pair in `completion` becomes one TraceTurn.
    The `prompt` (typically system + initial user) is folded into the first turn
    so the LLM view shows the system prompt.

    Args:
        path: path to the JSON file (top-level keys include `samples`).
        sample_idx: which sample to render. Default 0.

    Returns:
        TraceTurn list (may be empty if the file is malformed).
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    samples = data.get("samples") or []
    if not samples or sample_idx >= len(samples):
        return []
    sample = samples[sample_idx]
    completion = sample.get("completion") or []
    prompt = sample.get("prompt") or []
    initial_user = ""
    for m in prompt:
        if isinstance(m, dict) and m.get("role") == "user":
            initial_user = str(m.get("content") or "")
            break

    turns: list[TraceTurn] = []
    pending_user: str | None = initial_user or None
    turn_no = 0
    for msg in completion:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content") or ""
        if role in ("user", "tool"):
            pending_user = str(content) if isinstance(content, str) else json.dumps(content)
            continue
        if role == "assistant":
            user_text = pending_user or ""
            status = _parse_status(user_text)
            grid = _parse_map(user_text)
            turn_no = int(status.get("turn") or turn_no + 1)
            turns.append(
                TraceTurn(
                    turn=turn_no,
                    raw_grid=grid,
                    status=status,
                    dlvl=status.get("dlvl"),
                    hp=status.get("hp"),
                    max_hp=status.get("max_hp"),
                    rendered_user_message=user_text,
                    assistant_message=str(content) if isinstance(content, str) else "",
                    tool_calls=_normalize_tool_calls(msg.get("tool_calls")),
                )
            )
            pending_user = None
    return turns


def count_samples(path: Path) -> int:
    """Return number of samples in a legacy JSON file (0 on error)."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    return len(data.get("samples") or [])
