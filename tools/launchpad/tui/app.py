"""Textual App with four screens (Launch / Train / Harness / Traces).

Navigation:
    1 / 2 / 3 / 4   — direct jump to that screen
    tab             — cycle forward
    shift+tab       — cycle backward
    q               — quit
    ?               — help
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Static

from tools.launchpad.tui.screens.harness import HarnessScreen
from tools.launchpad.tui.screens.launch import LaunchScreen
from tools.launchpad.tui.screens.traces import TracesScreen
from tools.launchpad.tui.screens.train import TrainScreen

_ORDER = ("launch", "train", "harness", "traces")
_LABELS = {"launch": "1·Launch", "train": "2·Train", "harness": "3·Harness", "traces": "4·Traces"}


class TabBar(Static):
    """A one-line visible tab strip with the current screen highlighted."""

    DEFAULT_CSS = """
    TabBar {
        height: 1;
        background: $panel;
    }
    TabBar Static {
        padding: 0 2;
    }
    TabBar .tab-active {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    TabBar .tab-idle {
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="tab-bar")
        self._current = _ORDER[0]

    def compose(self) -> ComposeResult:
        with Horizontal():
            for name in _ORDER:
                yield Static(
                    _LABELS[name],
                    id=f"tab-{name}",
                    classes="tab-active" if name == self._current else "tab-idle",
                )

    def set_current(self, name: str) -> None:
        self._current = name
        for n in _ORDER:
            tab = self.query_one(f"#tab-{n}", Static)
            tab.set_classes("tab-active" if n == name else "tab-idle")


class LaunchpadApp(App):
    """Top-level Textual app."""

    TITLE = "NetHack Launchpad"
    SUB_TITLE = "evals · training · traces"

    BINDINGS = [
        Binding("1", "switch('launch')", "Launch"),
        Binding("2", "switch('train')", "Train"),
        Binding("3", "switch('harness')", "Harness"),
        Binding("4", "switch('traces')", "Traces"),
        Binding("tab", "cycle(1)", "next tab", show=True),
        Binding("shift+tab", "cycle(-1)", "prev tab", show=True),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
    ]

    SCREENS = {
        "launch": LaunchScreen,
        "train": TrainScreen,
        "harness": HarnessScreen,
        "traces": TracesScreen,
    }

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self._current = _ORDER[0]
        self._tab_bar = TabBar()

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._tab_bar
        yield Footer()

    def on_mount(self) -> None:
        self.push_screen(self._current)

    def action_switch(self, name: str) -> None:
        if name not in self.SCREENS or name == self._current:
            return
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self._current = name
        self.push_screen(name)
        try:
            self._tab_bar.set_current(name)
        except Exception:
            pass

    def action_cycle(self, delta: int) -> None:
        i = _ORDER.index(self._current)
        target = _ORDER[(i + delta) % len(_ORDER)]
        self.action_switch(target)

    def action_help(self) -> None:
        # Phase-3: modal cheatsheet.
        pass
