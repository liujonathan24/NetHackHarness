"""Textual App with four screens (Launch / Train / Harness / Traces).

Tab cycling: keys `1`/`2`/`3`/`4`. `q` quits. `?` shows help.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from tools.launchpad.tui.screens.harness import HarnessScreen
from tools.launchpad.tui.screens.launch import LaunchScreen
from tools.launchpad.tui.screens.traces import TracesScreen
from tools.launchpad.tui.screens.train import TrainScreen


class LaunchpadApp(App):
    """Top-level Textual app."""

    TITLE = "NetHack Launchpad"
    SUB_TITLE = "evals · training · traces"

    BINDINGS = [
        Binding("1", "switch('launch')", "Launch"),
        Binding("2", "switch('train')", "Train"),
        Binding("3", "switch('harness')", "Harness"),
        Binding("4", "switch('traces')", "Traces"),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
    ]

    SCREENS = {
        "launch": LaunchScreen,
        "train": TrainScreen,
        "harness": HarnessScreen,
        "traces": TracesScreen,
    }

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        self.push_screen("launch")

    def action_switch(self, name: str) -> None:
        """Switch to a named screen (replaces the top of the stack)."""
        # Pop until base, then push fresh — simplest correct behaviour for stubs.
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen(name)

    def action_help(self) -> None:
        """Placeholder for the help screen."""
        # Phase-3: open a modal help screen.
        pass
