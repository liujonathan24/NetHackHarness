"""Screen 4: TRACES — dual-pane (Observer / LLM view) + scrubber + live."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class TracesScreen(Screen):
    """Stub for Screen 4: TRACES. See SPEC.md."""

    def compose(self) -> ComposeResult:
        yield Static("Traces screen (stub) — phase 3 wires dual-pane viewer + scrubber.")
