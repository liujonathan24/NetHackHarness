"""Runtime overlay loader test.

Exercises the ``NETHACK_HARNESS`` env-var hook in
``environments.nethack.nethack.load_environment``. Writes a tiny harness TOML
to ``tmp_path``, redirects ``tools.launchpad.core.harness._PACKAGE_ROOT`` at
it, sets the env var via ``monkeypatch``, then calls ``apply_overlay`` and
asserts that ``SYSTEM_PROMPT`` actually got replaced.

We test the seam (``harness_overlay.apply_overlay``) rather than instantiating
the full ``NetHackVerifiersEnv`` because the latter spins up an NLE process —
overkill for verifying the overlay wiring. The bit-identical-when-unset check
is included as a separate test.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _seed_harness_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, text: str) -> None:
    """Point launchpad's harnesses_dir() at tmp_path and write <name>.toml."""
    from tools.launchpad.core import harness as H

    pkg_root = tmp_path / "launchpad"
    (pkg_root / "harnesses").mkdir(parents=True)
    monkeypatch.setattr(H, "_PACKAGE_ROOT", pkg_root)

    toml_body = (
        f'name = "{name}"\n'
        'extends = ""\n'
        "\n"
        "[system_prompt]\n"
        'mode = "replace"\n'
        f'text = """{text}"""\n'
        "\n"
        "[per_step_prompt]\n"
        'template = "B1_minimal"\n'
        "\n"
        "[tools]\n"
        "enabled = []\n"
        "disabled = []\n"
        "\n"
        "[rewards]\n"
        "scout = 7.5\n"
    )
    (pkg_root / "harnesses" / f"{name}.toml").write_text(toml_body, encoding="utf-8")


class _NHStub:
    """Lightweight stand-in for the ``environments.nethack.nethack`` module.

    The real module imports ``verifiers``/``numpy``/``NLE`` — too heavy for a
    unit test of the overlay seam. ``harness_overlay`` only touches a small
    surface (``SYSTEM_PROMPT``, ``_VARIANT_FORMATTERS``), so a SimpleNamespace
    with the same attribute shape is a faithful substitute.
    """

    SYSTEM_PROMPT = "ORIGINAL SYSTEM PROMPT (baseline)"
    _VARIANT_FORMATTERS: dict = {"B1": None}


def _make_reward_fn(name: str, weight: float):
    def fn():  # pragma: no cover - never executed
        return 0.0
    fn.__name__ = name
    fn.weight = weight
    return fn


def test_apply_overlay_replaces_system_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "OVERLAY SYSTEM PROMPT v42"
    _seed_harness_toml(tmp_path, monkeypatch, "ovl_test", sentinel)

    from environments.nethack import harness_overlay

    stub = _NHStub()
    monkeypatch.setenv("NETHACK_HARNESS", "ovl_test")
    cfg = harness_overlay.apply_overlay(stub)
    assert cfg is not None, "apply_overlay returned None despite env var being set"
    assert stub.SYSTEM_PROMPT == sentinel, (
        f"SYSTEM_PROMPT not replaced: got {stub.SYSTEM_PROMPT[:80]!r}"
    )

    # Reward weights propagate via apply_reward_weights.
    scout = _make_reward_fn("scout_reward", 1.0)
    descent = _make_reward_fn("descent_reward", 10.0)
    harness_overlay.apply_reward_weights([scout, descent], cfg)
    assert scout.weight == pytest.approx(7.5)
    assert descent.weight == pytest.approx(10.0)  # not in TOML → unchanged


def test_apply_overlay_noop_without_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    from environments.nethack import harness_overlay

    monkeypatch.delenv("NETHACK_HARNESS", raising=False)
    stub = _NHStub()
    before = stub.SYSTEM_PROMPT
    result = harness_overlay.apply_overlay(stub)
    assert result is None
    assert stub.SYSTEM_PROMPT == before


def test_filter_tool_callables_respects_enabled_disabled() -> None:
    from environments.nethack import harness_overlay
    from tools.launchpad.types import HarnessConfig, ToolsOverlay

    def _mk(name: str):
        fn = lambda: None  # noqa: E731
        fn.__name__ = name
        return fn

    cbs = [_mk("move"), _mk("attack"), _mk("descend")]
    cfg = HarnessConfig(
        name="t",
        extends="",
        tools=ToolsOverlay(enabled=["move", "descend"], disabled=["descend"]),
    )
    out = harness_overlay.filter_tool_callables(cbs, cfg)
    names = [f.__name__ for f in out]
    assert names == ["move"]

    # cfg=None is a no-op.
    assert harness_overlay.filter_tool_callables(cbs, None) is cbs
