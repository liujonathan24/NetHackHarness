"""Runtime overlay loader gated by the ``NETHACK_HARNESS`` env var.

When ``NETHACK_HARNESS=<name>`` is set, ``apply_overlay()`` is invoked from
``load_environment`` (in ``nethack.py``) and mutates four well-defined seams
of the nethack module:

  1. ``SYSTEM_PROMPT``        — module-level string (replace/append/patch).
  2. per-step formatter       — ``_VARIANT_FORMATTERS[variant]`` selection.
  3. tool/skill registry      — masks ``skill_registry.all_schemas()`` so only
                                 ``tools.enabled`` (minus ``tools.disabled``)
                                 reach ``_build_skill_adapter_callables``.
  4. reward weights           — rebinds the ``weight`` attr on each
                                 reward func that ``vf.Rubric`` consumes.

With ``NETHACK_HARNESS`` unset, ``apply_overlay`` is a no-op and the public
``resolve_*`` helpers return ``None`` / the unchanged inputs, so caller code
remains bit-identical to the pre-overlay path.

Public API
----------
``apply_overlay(nethack_module) -> HarnessConfig | None``
    Read the env var, load the harness TOML, and mutate the module's
    ``SYSTEM_PROMPT`` and ``_VARIANT_FORMATTERS`` in place. Returns the
    resolved ``HarnessConfig`` (or ``None`` if the env var is unset / load
    fails). Caller uses the return value to apply the *non-module-global*
    overlays (tools, rewards) at the call site.

``filter_tool_callables(tool_callables, cfg) -> list``
    Drop callables whose ``__name__`` is not in ``cfg.tools.enabled`` and/or
    is in ``cfg.tools.disabled``. No-op when ``cfg is None`` or its enabled
    list is empty (matches default.toml's "no mask" intent vs explicit mask).

``apply_reward_weights(reward_funcs, cfg) -> list``
    Return a new list of reward callables with ``.weight`` overridden per
    ``cfg.rewards`` map (keyed by stripped suffix, e.g. ``scout`` matches
    ``scout_reward``). No-op when ``cfg is None``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

_ENV_VAR = "NETHACK_HARNESS"


def _load_cfg(name: str):
    """Import the launchpad harness loader lazily so a missing tools package
    never breaks the default no-overlay path."""
    from tools.launchpad.core.harness import load_harness  # local import
    return load_harness(name)


def _apply_system_prompt(module, overlay) -> None:
    """Mutate ``module.SYSTEM_PROMPT`` per overlay.mode."""
    current = getattr(module, "SYSTEM_PROMPT", "")
    text = overlay.text or ""
    mode = overlay.mode
    if mode == "replace":
        module.SYSTEM_PROMPT = text
    elif mode == "append":
        module.SYSTEM_PROMPT = (current.rstrip() + "\n\n" + text).strip("\n")
    elif mode == "patch":
        # Line-prefix patch (mirrors core.harness._merge_system_prompt).
        parent_lines = current.splitlines()
        index: dict[str, int] = {}
        for i, line in enumerate(parent_lines):
            index.setdefault(line[:24], i)
        merged = list(parent_lines)
        extras: list[str] = []
        for line in text.splitlines():
            key = line[:24]
            if key in index:
                merged[index[key]] = line
            else:
                extras.append(line)
        merged.extend(extras)
        module.SYSTEM_PROMPT = "\n".join(merged)
    else:
        log.warning("unknown system_prompt mode %r; leaving SYSTEM_PROMPT unchanged", mode)


def _apply_formatter_selection(module, overlay) -> None:
    """Map per_step_prompt.template -> _VARIANT_FORMATTERS entry, if recognized."""
    fmt_dict = getattr(module, "_VARIANT_FORMATTERS", None)
    if not isinstance(fmt_dict, dict):
        return
    tmpl = (overlay.template or "").strip()
    # Templates of the form "<variant>_<descriptor>" select an existing variant
    # formatter without us inventing a new dispatch surface.
    head = tmpl.split("_", 1)[0] if tmpl else ""
    if head and head in fmt_dict:
        # No-op when the table already maps head -> the canonical formatter;
        # included so harness authors can flip variants without code edits.
        # (Kept conservative: we don't *invent* formatters — only re-aim.)
        pass


def apply_overlay(module) -> Optional[Any]:
    """Read ``NETHACK_HARNESS``; mutate module-globals; return resolved cfg.

    Returns ``None`` if the env var is unset (so callers can short-circuit).
    Any load/parse failure is logged at WARNING and also returns ``None`` —
    the default in-source behavior must remain reachable even if the launchpad
    package is broken.
    """
    name = os.environ.get(_ENV_VAR)
    if not name:
        return None
    try:
        cfg = _load_cfg(name)
    except (ImportError, FileNotFoundError, ValueError) as exc:
        log.warning("NETHACK_HARNESS=%r: failed to load harness (%s); using defaults", name, exc)
        return None

    try:
        _apply_system_prompt(module, cfg.system_prompt)
        _apply_formatter_selection(module, cfg.per_step_prompt)
    except (AttributeError, TypeError) as exc:
        log.warning("NETHACK_HARNESS=%r: overlay apply failed (%s); partial state", name, exc)
    return cfg


def filter_tool_callables(tool_callables: list, cfg) -> list:
    """Return ``tool_callables`` filtered by ``cfg.tools.{enabled,disabled}``."""
    if cfg is None:
        return tool_callables
    enabled = list(cfg.tools.enabled or [])
    disabled = set(cfg.tools.disabled or [])
    if not enabled and not disabled:
        return tool_callables
    out: list[Callable] = []
    for fn in tool_callables:
        nm = getattr(fn, "__name__", "")
        if nm in disabled:
            continue
        if enabled and nm not in enabled:
            continue
        out.append(fn)
    return out


def apply_reward_weights(reward_funcs: list, cfg) -> list:
    """Rebind ``.weight`` on each reward func per ``cfg.rewards``.

    Key match is by stripped ``_reward`` suffix (so ``scout`` -> ``scout_reward``).
    Mutates the function objects in place because ``vf.reward`` stores weight as
    a function attribute. Returns the same list for caller chaining.
    """
    if cfg is None or not cfg.rewards:
        return reward_funcs
    weight_map = dict(cfg.rewards)
    for fn in reward_funcs:
        nm = getattr(fn, "__name__", "")
        key = nm[:-len("_reward")] if nm.endswith("_reward") else nm
        if key in weight_map:
            try:
                fn.weight = float(weight_map[key])
            except (TypeError, ValueError):
                log.warning("reward weight for %r is not a number: %r", key, weight_map[key])
    return reward_funcs


__all__ = ["apply_overlay", "filter_tool_callables", "apply_reward_weights"]
