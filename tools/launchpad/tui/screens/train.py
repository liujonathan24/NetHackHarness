"""Screen 2: TRAIN — RL or GEPA launch + live training metrics."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class TrainScreen(Screen):
    """Stub for Screen 2: TRAIN. See SPEC.md."""

    def compose(self) -> ComposeResult:
        yield Static("Train screen (stub) — phase 3 wires the RL/GEPA form + live charts.")
