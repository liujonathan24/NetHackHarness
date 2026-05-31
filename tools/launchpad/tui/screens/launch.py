"""Screen 1: LAUNCH — compose a LaunchSpec and fire an eval."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class LaunchScreen(Screen):
    """Stub for Screen 1: LAUNCH. See SPEC.md."""

    def compose(self) -> ComposeResult:
        yield Static("Launch screen (stub) — phase 3 wires the form + recent-runs rail.")
