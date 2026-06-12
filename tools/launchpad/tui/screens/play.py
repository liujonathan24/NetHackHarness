"""Screen 5: PLAY — interactive test-play over the fork engine.

Backed by ``EngineEnv`` (the modifiable game), this screen lets you:
  * adjust difficulty knobs with the sidebar sliders,
  * press Reset to regenerate the level with the current knobs and a chosen seed,
    then see the floor layout (revealed),
  * type NetHack commands in the input box to play (each character is one action),
  * toggle between the glyph/char floor map and the raw tty view.

The engine lives outside the harness's nle path, so generation knobs like
room_density actually reshape the generated floor on Reset.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from tools.launchpad.tui.widgets.ascii_map import AsciiMap, format_status
from tools.launchpad.tui.widgets.knob_slider import KnobSlider

# nethack_core lives under environments/nethack and isn't an installed package
# on the launchpad path; add it so EngineEnv is importable.
_ROOT = pathlib.Path(__file__).resolve().parents[4]
_NETHACK = _ROOT / "environments" / "nethack"
if str(_NETHACK) not in sys.path:
    sys.path.insert(0, str(_NETHACK))

from nethack_core.engine_env import EngineEnv  # noqa: E402

# Per-knob slider ranges (lo, hi, step); default for any unlisted knob.
_RANGES = {
    "reveal_map": (0.0, 1.0, 1.0),
    "vision_radius": (0.0, 15.0, 1.0),
    "room_density": (0.0, 1.5, 0.05),
}
_DEFAULT_RANGE = (0.0, 3.0, 0.25)


@contextlib.contextmanager
def _silence_engine_stdio():
    """Redirect C-level fd 1/2 to /dev/null around engine calls.

    The NetHack engine writes to C stdout/stderr (e.g. "Cannot read termcap
    database; using dumb terminal settings."). Inside a Textual app that output
    corrupts the rendered screen — so we silence it at the file-descriptor level
    (Python-level redirect_stdout is not enough; the writes come from C).
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    old1, old2 = os.dup(1), os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(old1, 1)
        os.dup2(old2, 2)
        os.close(devnull)
        os.close(old1)
        os.close(old2)


def _grid_to_rows(grid) -> list[str]:
    """Convert a 2-D uint8 array to printable rows."""
    rows = []
    for row in grid:
        rows.append("".join(chr(int(c)) if 32 <= int(c) < 127 else " " for c in row))
    return rows


def _status_dict(blstats) -> dict:
    """Minimal status from blstats (NLE layout)."""
    b = [int(x) for x in blstats]
    return {
        "hp": b[10], "max_hp": b[11], "ac": b[16],
        "dlvl": b[12], "gold": b[13],
    }


class PlayScreen(Screen):
    """Interactive test-play with live difficulty knobs + regenerate."""

    BINDINGS = [
        Binding("ctrl+r", "regen", "Reset/Regenerate"),
        Binding("ctrl+t", "toggle_view", "tty/map"),
        Binding("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    PlayScreen { layout: horizontal; }
    PlayScreen #main { width: 1fr; height: 100%; padding: 1 1; }
    PlayScreen #status { height: 1; }
    PlayScreen #map { height: 1fr; }
    PlayScreen #cmd { dock: bottom; }
    PlayScreen #sidebar {
        width: 40; min-width: 32; height: 100%;
        border-left: solid $accent; padding: 1 1;
    }
    PlayScreen .title { text-style: bold underline; color: $accent; }
    PlayScreen #sliders { height: 1fr; }
    PlayScreen #seed-row { height: 3; }
    PlayScreen #reset { width: 100%; }
    """

    # Vanilla knob defaults (mirrors the engine's NLE_TUNE_FIELDS X-macro:
    # all scales 1.0; vision_radius/reveal_map are 0.0 sentinels). Used to build
    # the sliders before a game is started; resynced from the engine on mount.
    _NON_UNIT_DEFAULTS = {"vision_radius": 0.0, "reveal_map": 0.0}

    def __init__(self) -> None:
        super().__init__()
        # Loading the engine library + reading the knob catalog is cheap and
        # touches no terminal state. Starting a game (reset) manipulates the
        # tty, so it is deferred to on_mount — doing it in __init__ corrupts
        # Textual's compose.
        with _silence_engine_stdio():
            self.env = EngineEnv()
            self._catalog = self.env.tune.catalog()
        self._view = "map"  # or "tty"
        self._obs = None
        self._defaults = {n: self._NON_UNIT_DEFAULTS.get(n, 1.0) for n in self._catalog}
        self._defaults["reveal_map"] = 1.0  # show the floor by default in the tool
        self._tune = dict(self._defaults)

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield Static("", id="status")
            yield AsciiMap(id="map")
            yield Input(placeholder="type NetHack commands, Enter to play (e.g. jjjl)", id="cmd")
        with Vertical(id="sidebar"):
            yield Static("Difficulty knobs (◀ ▶ to adjust)", classes="title")
            with VerticalScroll(id="sliders"):
                for name in self._catalog:
                    lo, hi, step = _RANGES.get(name, _DEFAULT_RANGE)
                    yield KnobSlider(
                        name, value=self._defaults[name], lo=lo, hi=hi, step=step,
                        on_change=self._on_knob,
                    )
            with Horizontal(id="seed-row"):
                yield Input(value="42", id="seed")
            yield Button("Reset / Regenerate floor", id="reset", variant="primary")

    def on_mount(self) -> None:
        self._regen()

    # ----- knob + reset -----

    def _on_knob(self, name: str, value: float) -> None:
        self._tune[name] = value
        # Live (non-generation) knobs also take effect immediately.
        try:
            self.env.set_tune(**{name: value})
        except Exception:
            pass
        self._render()

    def action_regen(self) -> None:
        self._regen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reset":
            self._regen()

    def _seed(self) -> int:
        try:
            return int(self.query_one("#seed", Input).value or "42")
        except ValueError:
            return 42

    def _regen(self) -> None:
        seed = self._seed()
        with _silence_engine_stdio():
            obs, _meta = self.env.reset(seeds=(seed, seed), tune=dict(self._tune))
            self._obs = obs
            # let vision/reveal settle so the floor shows
            for _ in range(2):
                self._obs, _done, _info = self.env.step(ord("."))
        self._render()

    # ----- play + render -----

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "cmd":
            return
        cmds = event.value
        event.input.value = ""
        with _silence_engine_stdio():
            for ch in cmds:
                self._obs, _done, _info = self.env.step(ord(ch))
        self._render()

    def action_toggle_view(self) -> None:
        self._view = "tty" if self._view == "map" else "map"
        self._render()

    def _render(self) -> None:
        if self._obs is None:
            return
        grid = self._obs.tty_chars if self._view == "tty" else self._obs.chars
        self.query_one("#map", AsciiMap).update_grid(_grid_to_rows(grid))
        status = format_status(_status_dict(self._obs.blstats))
        view = "tty" if self._view == "tty" else "floor map"
        self.query_one("#status", Static).update(
            status.append(f"   [{view}]  seed {self._seed()}")
        )

    def on_unmount(self) -> None:
        try:
            self.env.close()
        except Exception:
            pass
