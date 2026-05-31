"""Smoke tests for the TRACES screen + reusable widgets.

We don't drive a full Textual event loop here; we just verify the screen
imports, instantiates cleanly, and renders an empty state when no runs exist.
The widget helpers (format_status, sparkline) are also unit-tested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.launchpad.tui.widgets.ascii_map import AsciiMap
from tools.launchpad.tui.widgets.llm_turn import LLMTurnView
from tools.launchpad.tui.widgets.metric_chart import _sparkline
from tools.launchpad.tui.widgets.scrubber import Scrubber
from tools.launchpad.types import ToolCallRecord, TraceTurn


def test_screen_imports_and_constructs(tmp_path: Path) -> None:
    from tools.launchpad.tui.screens.traces import TracesScreen, format_status

    screen = TracesScreen(repo_root=tmp_path)
    assert screen is not None
    # format_status helper round-trip.
    assert "HP" in format_status({"hp": 12, "max_hp": 18}).plain
    assert "no status" in format_status(None).plain


def test_widgets_handle_empty_inputs() -> None:
    am = AsciiMap()
    rendered = am.render()
    assert "no map" in rendered.plain
    am.update_grid(["....", "..@.", "...."])
    assert "@" in am.render().plain

    llm = LLMTurnView()
    assert "no turn" in llm.render().renderables[0].plain  # type: ignore[union-attr]
    turn = TraceTurn(
        turn=3,
        rendered_user_message="HP 5",
        assistant_message="run away",
        tool_calls=[ToolCallRecord(name="move", arguments='{"direction":"N"}')],
    )
    llm.update_turn(turn)
    # Should now contain at least one panel rather than the empty placeholder.
    out = llm.render()
    assert any("user" in getattr(p, "title", "") or "" for p in out.renderables)


def test_sparkline_handles_empty_and_flat() -> None:
    assert _sparkline([], 20) == ""
    flat = _sparkline([1.0, 1.0, 1.0], 10)
    assert len(flat) == 3
    spark = _sparkline([0.0, 1.0, 2.0, 3.0], 10)
    assert spark[0] != spark[-1]


def test_scrubber_value_clamp() -> None:
    sc = Scrubber(0, 10, 5)
    sc.action_step(100)
    assert sc.value == 10
    sc.action_step(-1000)
    assert sc.value == 0
    sc.set_range(0, 3)
    assert sc.value == 0
    sc.action_jump("max")
    assert sc.value == 3


@pytest.mark.asyncio
async def test_traces_screen_mounts_with_no_runs(tmp_path: Path) -> None:
    """End-to-end: push the screen on a real Textual app with an empty repo."""
    from textual.app import App

    from tools.launchpad.tui.screens.traces import TracesScreen

    class _Harness(App):
        def on_mount(self) -> None:
            self.push_screen(TracesScreen(repo_root=tmp_path))

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        # The runs list should show the empty banner; toggling follow off
        # must not raise.
        await pilot.press("f")
        await pilot.press("f")
        await pilot.pause()
