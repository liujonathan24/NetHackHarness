"""Tests for ``tools.launchpad.core.harness``.

No real subprocess calls — ``edit_harness`` is exercised via ``unittest.mock``
on ``subprocess.run``. All filesystem state lives under ``tmp_path``: we
monkeypatch ``harness._PACKAGE_ROOT`` so each test gets its own sandbox.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from tools.launchpad.core import harness as H
from tools.launchpad.types import (
    HarnessConfig,
    SystemPromptOverlay,
    ToolsOverlay,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``harnesses_dir()`` into a fresh tmp dir and seed `default.toml`."""
    pkg_root = tmp_path / "launchpad"
    (pkg_root / "harnesses").mkdir(parents=True)
    monkeypatch.setattr(H, "_PACKAGE_ROOT", pkg_root)

    default = HarnessConfig(
        name="default",
        extends="",
        system_prompt=SystemPromptOverlay(mode="replace", text="BASE PROMPT"),
        tools=ToolsOverlay(enabled=["move", "attack"], disabled=[]),
        rewards={"scout": 1.0, "descent": 10.0},
    )
    H.save_harness(default)
    return pkg_root / "harnesses"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_save_then_load_roundtrip(sandbox: Path) -> None:
    cfg = H.load_harness("default")
    assert cfg.name == "default"
    assert cfg.system_prompt.text == "BASE PROMPT"
    assert cfg.tools.enabled == ["move", "attack"]
    assert (sandbox / "default.toml").is_file()
    assert cfg.source_path == str(sandbox / "default.toml")


def test_create_and_extends_merges_overlays(sandbox: Path) -> None:
    """A child with `append` system_prompt + extra tools + reward override."""
    H.create_harness("child", extends="default")
    raw = (sandbox / "child.toml").read_text()
    assert 'name = "child"' in raw
    assert 'extends = "default"' in raw

    # Mutate the child on disk to exercise overlay merging.
    child = HarnessConfig(
        name="child",
        extends="default",
        system_prompt=SystemPromptOverlay(mode="append", text="EXTRA"),
        tools=ToolsOverlay(enabled=["search"], disabled=["attack"]),
        rewards={"descent": 20.0, "success": 100.0},
    )
    H.save_harness(child)

    resolved = H.load_harness("child")
    # append mode: parent + blank line + child
    assert resolved.system_prompt.text == "BASE PROMPT\n\nEXTRA"
    assert resolved.system_prompt.mode == "replace"  # collapsed after merge
    # tool union with disabled mask removing "attack"
    assert "move" in resolved.tools.enabled
    assert "search" in resolved.tools.enabled
    assert "attack" not in resolved.tools.enabled
    assert "attack" in resolved.tools.disabled
    # reward override (child wins on conflict, parent retained otherwise)
    assert resolved.rewards["scout"] == 1.0
    assert resolved.rewards["descent"] == 20.0
    assert resolved.rewards["success"] == 100.0


def test_list_harnesses_sorted(sandbox: Path) -> None:
    H.create_harness("zeta", extends="default")
    H.create_harness("alpha", extends="default")
    names = [c.name for c in H.list_harnesses()]
    assert names == ["alpha", "default", "zeta"]


def test_validate_warns_on_unknown_tool(sandbox: Path) -> None:
    bad = HarnessConfig(
        name="weird",
        extends="default",
        tools=ToolsOverlay(enabled=["not_a_real_tool"]),
        rewards={"bogus_reward": 0.5},
    )
    H.save_harness(bad)
    warnings = H.validate_harness("weird")
    assert any("not_a_real_tool" in w for w in warnings)
    assert any("bogus_reward" in w for w in warnings)


def test_diff_harness_shows_changes(sandbox: Path) -> None:
    H.create_harness("child", extends="default")
    diff = H.diff_harness("child", against="default")
    assert "--- default.toml" in diff
    assert "+++ child.toml" in diff


def test_preview_returns_string_containing_state(sandbox: Path) -> None:
    out = H.preview_harness("default")
    assert isinstance(out, str) and out
    # The synthetic state advertises Dlvl 1 and shows the @ glyph.
    assert "Dlvl 1" in out
    assert "@" in out


def test_preview_with_explicit_state_uses_overrides(sandbox: Path) -> None:
    state = {
        "turn": 7,
        "dlvl": 4,
        "hp": 3,
        "max_hp": 22,
        "ac": 5,
        "gold": 42,
        "messages": ["You feel feverish."],
        "inventory": [{"slot": "a", "name": "wand of digging"}],
        "adjacent": ["N: floor"],
        "visible": ["> (1,1) stairs DOWN"],
        "raw_grid": [".....@.....", "..........."],
        "under_player": "floor",
    }
    out = H.preview_harness("default", state=state)
    assert "TURN 7" in out
    assert "Dlvl 4" in out
    assert "wand of digging" in out
    assert "feverish" in out


def test_save_atomic_writes_via_tempfile(sandbox: Path) -> None:
    """No stray ``.tmp`` files left behind and content is valid TOML."""
    cfg = H.load_harness("default")
    H.save_harness(cfg)
    leftovers = list(sandbox.glob("*.tmp")) + list(sandbox.glob(".*.tmp"))
    assert leftovers == []
    with (sandbox / "default.toml").open("rb") as fh:
        reparsed: dict[str, Any] = tomllib.load(fh)
    assert reparsed["name"] == "default"


def test_edit_harness_invokes_editor(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``edit_harness`` uses $EDITOR and returns its exit code — no real spawn."""
    monkeypatch.setenv("EDITOR", "fake-editor")
    fake_completed = mock.Mock(returncode=0)
    with mock.patch.object(H.subprocess, "run", return_value=fake_completed) as runner:
        rc = H.edit_harness("default")
    assert rc == 0
    runner.assert_called_once()
    args, _kwargs = runner.call_args
    assert args[0][0] == "fake-editor"
    assert args[0][1].endswith("default.toml")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_load_missing_raises_filenotfound(sandbox: Path) -> None:
    with pytest.raises(FileNotFoundError):
        H.load_harness("does_not_exist")


def test_create_duplicate_raises(sandbox: Path) -> None:
    with pytest.raises(FileExistsError):
        H.create_harness("default", extends="default")


def test_create_missing_parent_raises(sandbox: Path) -> None:
    with pytest.raises(FileNotFoundError):
        H.create_harness("orphan", extends="no_such_parent")


def test_save_rejects_path_separator(sandbox: Path) -> None:
    bad = HarnessConfig(name="../escape", extends="")
    with pytest.raises(ValueError):
        H.save_harness(bad)


def test_extends_cycle_raises_valueerror(sandbox: Path) -> None:
    """A -> B -> A must be detected, not infinite-loop."""
    H.save_harness(HarnessConfig(name="a", extends="b"))
    H.save_harness(HarnessConfig(name="b", extends="a"))
    with pytest.raises(ValueError, match="cycle"):
        H.load_harness("a")


def test_malformed_toml_raises_valueerror(sandbox: Path) -> None:
    (sandbox / "broken.toml").write_text("this is = not valid = toml\n[[[")
    with pytest.raises(ValueError):
        H.load_harness("broken")


def test_edit_missing_raises(sandbox: Path) -> None:
    with pytest.raises(FileNotFoundError):
        H.edit_harness("ghost")


def test_diff_against_missing_is_one_sided(sandbox: Path) -> None:
    """``diff_harness`` never raises, even when the comparand is absent."""
    diff = H.diff_harness("default", against="nonexistent")
    # `default.toml` lines should appear as additions (the b-side).
    assert "+++ default.toml" in diff
    assert "name = \"default\"" in diff
