"""Screen 3: HARNESS — browse/edit harness TOMLs, shell out to $EDITOR."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class HarnessScreen(Screen):
    """Stub for Screen 3: HARNESS. See SPEC.md."""

    def compose(self) -> ComposeResult:
        yield Static("Harness screen (stub) — phase 3 wires the rail + preview pane.")
