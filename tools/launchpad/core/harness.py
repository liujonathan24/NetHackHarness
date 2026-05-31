"""Harness TOML loader/writer/validator/preview.

Harness TOMLs live at ``tools/launchpad/harnesses/*.toml``. The runtime overlay
loader is in ``environments/nethack/nethack.py`` (gated by the ``NETHACK_HARNESS``
env var); this module owns the CLI/TUI side of CRUD + preview.

Public API (see ``tools/launchpad/CONTRACTS.md`` section 3):

- ``harnesses_dir()``
- ``list_harnesses()``
- ``load_harness(name)``         (recursive ``extends`` resolution)
- ``save_harness(cfg)``          (atomic write)
- ``create_harness(name, extends="default")``
- ``edit_harness(name)``         (spawns ``$EDITOR``)
- ``diff_harness(name, against="default")``
- ``validate_harness(name)``
- ``preview_harness(name, state=None)``
"""

from __future__ import annotations

import difflib
import logging
import os
import shutil
import subprocess
import tempfile
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import ValidationError

from tools.launchpad.types import (
    HarnessConfig,
    PerStepPromptOverlay,
    SystemPromptOverlay,
    ToolsOverlay,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # tools/launchpad/
_HARNESSES_SUBDIR = "harnesses"


def harnesses_dir() -> Path:
    """Return the on-disk dir containing harness TOMLs (creates if missing)."""
    d = _PACKAGE_ROOT / _HARNESSES_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _harness_path(name: str) -> Path:
    if not name:
        raise ValueError("harness name must be non-empty")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError(f"invalid harness name: {name!r}")
    return harnesses_dir() / f"{name}.toml"


def _read_toml_raw(name: str) -> dict[str, Any]:
    """Parse one harness TOML (no overlay resolution)."""
    path = _harness_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"harness not found: {path}")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"malformed TOML in {path}: {exc}") from exc
    # Stamp the source path so callers can locate the file later.
    data.setdefault("name", name)
    data["source_path"] = str(path)
    return data


def _atomic_write(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` atomically (tempfile + rename in same dir)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except OSError:
        # Clean up the temp file on any I/O failure.
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------------------
# Overlay merge (per CONTRACTS.md section 3)
# ---------------------------------------------------------------------------


def _merge_system_prompt(
    parent: SystemPromptOverlay, child: SystemPromptOverlay
) -> SystemPromptOverlay:
    """Combine parent+child system-prompt overlays per ``child.mode``.

    Modes:
      - ``replace`` (default): child wins outright.
      - ``append``: child text appended after parent text with a blank line.
      - ``patch``: token-level naive merge (lines from child override matching
        leading-prefix lines in parent; new lines appended).
    """
    if child.mode == "replace":
        return SystemPromptOverlay(mode="replace", text=child.text)
    if child.mode == "append":
        joined = (parent.text.rstrip() + "\n\n" + child.text).strip("\n")
        return SystemPromptOverlay(mode="replace", text=joined)
    # patch: line-replace where the first 24 chars match
    parent_lines = parent.text.splitlines()
    index: dict[str, int] = {}
    for i, line in enumerate(parent_lines):
        key = line[:24]
        index.setdefault(key, i)
    merged = list(parent_lines)
    extras: list[str] = []
    for line in child.text.splitlines():
        key = line[:24]
        if key in index:
            merged[index[key]] = line
        else:
            extras.append(line)
    if extras:
        merged.extend(extras)
    return SystemPromptOverlay(mode="replace", text="\n".join(merged))


def _merge_per_step(
    parent: PerStepPromptOverlay, child_raw: dict[str, Any]
) -> PerStepPromptOverlay:
    """Dict-update child fields onto parent (only keys present in child override)."""
    base = parent.model_dump()
    base.update(child_raw)
    try:
        return PerStepPromptOverlay.model_validate(base)
    except ValidationError as exc:
        raise ValueError(f"per_step_prompt merge failed: {exc}") from exc


def _merge_tools(parent: ToolsOverlay, child: ToolsOverlay) -> ToolsOverlay:
    """List-union ``enabled`` with parent then child, mask via combined ``disabled``."""
    combined_disabled = list(dict.fromkeys([*parent.disabled, *child.disabled]))
    disabled_set = set(combined_disabled)
    enabled_union: list[str] = []
    for name in (*parent.enabled, *child.enabled):
        if name in disabled_set:
            continue
        if name not in enabled_union:
            enabled_union.append(name)
    overrides = deepcopy(parent.overrides)
    for tool_name, override in child.overrides.items():
        existing = overrides.get(tool_name, {})
        existing.update(override)
        overrides[tool_name] = existing
    return ToolsOverlay(
        enabled=enabled_union,
        disabled=combined_disabled,
        overrides=overrides,
    )


def _merge_rewards(
    parent: dict[str, float], child: dict[str, float]
) -> dict[str, float]:
    out = dict(parent)
    out.update(child)
    return out


def _normalize_extends(extends: str | None) -> str | None:
    """Treat empty string as 'no parent' (matches default.toml convention)."""
    if extends is None:
        return None
    extends = extends.strip()
    return extends or None


def _resolve(name: str, visited: tuple[str, ...]) -> HarnessConfig:
    """Recursive resolution. ``visited`` is the chain of names walked so far."""
    if name in visited:
        chain = " -> ".join([*visited, name])
        raise ValueError(f"extends cycle detected: {chain}")
    raw = _read_toml_raw(name)
    # Validate the *raw* leaf (so schema errors are localized).
    raw_for_validation = {k: v for k, v in raw.items() if k != "source_path"}
    try:
        leaf = HarnessConfig.model_validate(raw_for_validation)
    except ValidationError as exc:
        raise ValueError(f"harness {name!r} failed validation: {exc}") from exc
    leaf = leaf.model_copy(update={"source_path": raw.get("source_path")})

    parent_name = _normalize_extends(leaf.extends)
    if parent_name is None:
        return leaf
    parent = _resolve(parent_name, (*visited, name))

    merged_system = _merge_system_prompt(parent.system_prompt, leaf.system_prompt)
    # For per_step, we want only fields explicitly set in the child TOML to win.
    child_per_step_raw: dict[str, Any] = raw.get("per_step_prompt", {}) or {}
    merged_per_step = _merge_per_step(parent.per_step_prompt, child_per_step_raw)
    merged_tools = _merge_tools(parent.tools, leaf.tools)
    merged_rewards = _merge_rewards(parent.rewards, leaf.rewards)

    return HarnessConfig(
        name=leaf.name,
        extends=leaf.extends,
        system_prompt=merged_system,
        per_step_prompt=merged_per_step,
        tools=merged_tools,
        rewards=merged_rewards,
        source_path=leaf.source_path,
    )


# ---------------------------------------------------------------------------
# Public CRUD
# ---------------------------------------------------------------------------


def list_harnesses() -> list[HarnessConfig]:
    """List every harness in ``harnesses_dir()``, sorted by name.

    Harnesses that fail to parse are logged and skipped rather than aborting
    the whole listing.
    """
    out: list[HarnessConfig] = []
    for path in sorted(harnesses_dir().glob("*.toml")):
        name = path.stem
        try:
            out.append(load_harness(name))
        except (FileNotFoundError, ValueError) as exc:
            log.warning("skipping unreadable harness %s: %s", name, exc)
    return out


def load_harness(name: str) -> HarnessConfig:
    """Load one harness by name (with ``extends`` resolution applied)."""
    return _resolve(name, visited=())


def save_harness(cfg: HarnessConfig) -> Path:
    """Write ``cfg`` to ``harnesses_dir()/<cfg.name>.toml`` via ``tomli_w``."""
    path = _harness_path(cfg.name)
    payload = cfg.model_dump(exclude_none=False)
    # source_path is filesystem-derived; never persist it in the TOML body.
    payload.pop("source_path", None)
    # tomli_w can't serialize tuples; convert map_window.
    if "per_step_prompt" in payload and isinstance(
        payload["per_step_prompt"].get("map_window"), tuple
    ):
        payload["per_step_prompt"]["map_window"] = list(
            payload["per_step_prompt"]["map_window"]
        )
    # Drop None extends (tomli_w refuses None values).
    if payload.get("extends") is None:
        payload["extends"] = ""
    body = tomli_w.dumps(payload).encode("utf-8")
    _atomic_write(path, body)
    log.info("wrote harness %s -> %s", cfg.name, path)
    return path


def create_harness(name: str, extends: str = "default") -> HarnessConfig:
    """Create a new harness that ``extends`` another."""
    path = _harness_path(name)
    if path.exists():
        raise FileExistsError(f"harness already exists: {path}")
    parent_norm = _normalize_extends(extends)
    if parent_norm is not None and not _harness_path(parent_norm).is_file():
        raise FileNotFoundError(f"extends target not found: {parent_norm}.toml")
    cfg = HarnessConfig(name=name, extends=extends)
    save_harness(cfg)
    # Re-load through the resolver so overlays come back applied.
    return load_harness(name)


def edit_harness(name: str) -> int:
    """Open ``<name>.toml`` in ``$EDITOR`` (fallback: nano). Returns exit code."""
    path = _harness_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"harness not found: {path}")
    editor = os.environ.get("EDITOR") or shutil.which("nano") or "nano"
    log.info("editing %s with %s", path, editor)
    try:
        proc = subprocess.run([editor, str(path)], check=False)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"editor not on PATH: {editor!r}") from exc
    return proc.returncode


def diff_harness(name: str, against: str = "default") -> str:
    """Return a unified-diff string of ``<name>.toml`` vs ``<against>.toml``."""
    def _safe_text(harness_name: str) -> list[str]:
        try:
            path = _harness_path(harness_name)
        except ValueError:
            return []
        if not path.is_file():
            return []
        try:
            return path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError as exc:
            log.warning("could not read %s for diff: %s", path, exc)
            return []

    a_lines = _safe_text(against)
    b_lines = _safe_text(name)
    diff = difflib.unified_diff(
        a_lines, b_lines, fromfile=f"{against}.toml", tofile=f"{name}.toml"
    )
    return "".join(diff)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


# Known tool names — mirrors environments/nethack/nethack_core/skills.py.
_KNOWN_TOOLS: frozenset[str] = frozenset(
    {
        "move", "attack", "descend", "search",
        "eat", "quaff", "read", "pray", "engrave_elbereth",
        "kick", "throw", "pickup",
        "inventory_item", "menu_option",
        "move_to", "autoexplore", "find_and_descend",
        "add_note", "recall", "pin_objective",
        "wiki_lookup", "wiki_search",
    }
)

_KNOWN_REWARDS: frozenset[str] = frozenset(
    {"scout", "descent", "success", "ascension"}
)


def validate_harness(name: str) -> list[str]:
    """Validate ``<name>.toml``. Returns warnings; raises on hard errors."""
    cfg = load_harness(name)  # raises ValueError/FileNotFoundError as documented
    warnings: list[str] = []

    for tool in cfg.tools.enabled:
        if tool not in _KNOWN_TOOLS:
            warnings.append(f"unknown tool in 'enabled': {tool!r}")
    for tool in cfg.tools.disabled:
        if tool not in _KNOWN_TOOLS:
            warnings.append(f"unknown tool in 'disabled': {tool!r}")
    for tool in cfg.tools.overrides:
        if tool not in _KNOWN_TOOLS:
            warnings.append(f"unknown tool in 'overrides': {tool!r}")

    for reward_name in cfg.rewards:
        if reward_name not in _KNOWN_REWARDS:
            warnings.append(f"unknown reward weight: {reward_name!r}")

    mw = cfg.per_step_prompt.map_window
    if len(mw) != 2 or mw[0] <= 0 or mw[1] <= 0:
        warnings.append(f"per_step_prompt.map_window looks wrong: {mw!r}")

    return warnings


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _default_sample_state() -> dict[str, Any]:
    """Frozen Dlvl-1 sample state used when ``preview_harness`` gets no input."""
    return {
        "turn": 0,
        "dlvl": 1,
        "hp": 16,
        "max_hp": 16,
        "ac": 9,
        "gold": 0,
        "messages": ["Hello stranger, welcome to NetHack!"],
        "inventory": [
            {"slot": "a", "name": "+0 short sword (weapon in hand)"},
            {"slot": "b", "name": "+0 leather armor (being worn)"},
        ],
        "adjacent": ["E: door", "S: floor", "W: floor", "N: wall"],
        "visible": ["@ (5,8) you", "> (12,3) stairs DOWN"],
        "raw_grid": [
            "--------",
            "|......|",
            "|..@..>|",
            "|......|",
            "--------",
        ],
        "under_player": "floor",
    }


def _render_preview_local(cfg: HarnessConfig, state: dict[str, Any]) -> str:
    """Render the per-step user message from the resolved overlay + state.

    This is a deterministic best-effort renderer that mirrors the shape of the
    runtime ``B1_minimal`` formatter. The runtime will produce a richer string;
    this preview is intentionally pure-Python so it works without a live NLE.
    """
    psp = cfg.per_step_prompt
    parts: list[str] = []
    parts.append(f"=== TURN {state.get('turn', 0)} (Dlvl {state.get('dlvl', 1)}) ===")
    parts.append(
        f"HP {state.get('hp', '?')}/{state.get('max_hp', '?')}  "
        f"AC {state.get('ac', '?')}  Gold {state.get('gold', 0)}"
    )

    grid = state.get("raw_grid", []) or []
    win_w, win_h = psp.map_window
    parts.append("--- MAP ---")
    parts.extend(line[:win_w] for line in grid[:win_h])

    if psp.include_inventory:
        parts.append("--- INVENTORY ---")
        for item in state.get("inventory", []):
            parts.append(f"  {item.get('slot', '?')}) {item.get('name', '?')}")

    msgs = state.get("messages", []) or []
    if msgs and psp.include_messages_n > 0:
        parts.append("--- MESSAGES ---")
        for m in msgs[-psp.include_messages_n :]:
            parts.append(f"  - {m}")

    if psp.include_adjacent:
        parts.append("--- ADJACENT ---")
        for a in state.get("adjacent", []):
            parts.append(f"  {a}")

    if psp.include_visible:
        parts.append("--- VISIBLE FEATURES ---")
        for v in state.get("visible", []):
            parts.append(f"  {v}")

    if psp.ascii_legend:
        parts.append("--- LEGEND ---")
        parts.append("  @ you  > stairs DOWN  < stairs UP  . floor  # corridor")

    parts.append(f"--- UNDER PLAYER: {state.get('under_player', 'floor')} ---")
    return "\n".join(parts)


def preview_harness(name: str, state: dict[str, Any] | None = None) -> str:
    """Render the turn-0 user message that the LLM would see under this harness.

    Per CONTRACTS.md the implementation should defer to the runtime overlay
    formatter (set ``NETHACK_HARNESS=<name>`` and invoke it). That entrypoint
    is not yet exposed by the nethack package, so we fall back to a local
    deterministic renderer that consumes the resolved ``HarnessConfig`` plus
    a frozen sample state. Either way the return shape matches
    ``TraceTurn.rendered_user_message``.
    """
    cfg = load_harness(name)
    sample = state if state is not None else _default_sample_state()

    # Try the runtime entry point if it ever lands; otherwise fall back locally.
    os.environ["NETHACK_HARNESS"] = name
    try:
        from environments.nethack import nethack as _nethack_mod  # type: ignore
    except ImportError:
        log.debug("nethack runtime unavailable; using local preview renderer")
        return _render_preview_local(cfg, sample)

    formatter = getattr(_nethack_mod, "render_user_message_preview", None)
    if not callable(formatter):
        log.debug(
            "nethack runtime has no preview hook; using local preview renderer"
        )
        return _render_preview_local(cfg, sample)
    try:
        rendered = formatter(cfg.model_dump(), sample)
    except (TypeError, ValueError) as exc:
        log.warning("runtime preview hook failed (%s); falling back locally", exc)
        return _render_preview_local(cfg, sample)
    if not isinstance(rendered, str):
        log.warning(
            "runtime preview hook returned %s, not str; falling back locally",
            type(rendered).__name__,
        )
        return _render_preview_local(cfg, sample)
    return rendered


__all__ = [
    "harnesses_dir",
    "list_harnesses",
    "load_harness",
    "save_harness",
    "create_harness",
    "edit_harness",
    "diff_harness",
    "validate_harness",
    "preview_harness",
]
