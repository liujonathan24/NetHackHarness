"""KnobSlider: a one-line labelled horizontal slider for a difficulty knob.

Textual has no built-in slider, so this is a small focusable widget that renders
``name [████────] value`` and adjusts the value with ◀/▶ (or h/l, -/+) when
focused. On change it calls ``on_change(name, value)`` so the screen can push the
value into the engine.
"""

from __future__ import annotations

from typing import Callable, Optional

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

_BAR_WIDTH = 14


class KnobSlider(Widget):
    DEFAULT_CSS = """
    KnobSlider {
        height: 1;
        width: 100%;
    }
    KnobSlider:focus {
        background: $accent 30%;
        text-style: bold;
    }
    """

    can_focus = True
    value: reactive[float] = reactive(1.0)

    def __init__(
        self,
        name: str,
        value: float = 1.0,
        lo: float = 0.0,
        hi: float = 3.0,
        step: float = 0.25,
        on_change: Optional[Callable[[str, float], None]] = None,
    ) -> None:
        super().__init__()
        self.knob = name
        self.lo = lo
        self.hi = hi
        self.step = step
        self._on_change = on_change
        self.value = float(value)

    def render(self) -> Text:
        span = (self.hi - self.lo) or 1.0
        frac = max(0.0, min(1.0, (self.value - self.lo) / span))
        filled = int(round(frac * _BAR_WIDTH))
        bar = "█" * filled + "─" * (_BAR_WIDTH - filled)
        t = Text()
        t.append(f"{self.knob:<22}", style="bold" if self.has_focus else "")
        t.append(bar, style="cyan")
        t.append(f" {self.value:>5.2f}", style="yellow")
        return t

    def _set(self, v: float) -> None:
        v = max(self.lo, min(self.hi, round(v, 3)))
        if v != self.value:
            self.value = v
            if self._on_change is not None:
                self._on_change(self.knob, v)

    def watch_value(self) -> None:  # noqa: D401 - reactive hook
        self.refresh()

    def on_key(self, event) -> None:
        if event.key in ("right", "l", "plus", "+"):
            self._set(self.value + self.step)
            event.stop()
        elif event.key in ("left", "h", "minus", "-"):
            self._set(self.value - self.step)
            event.stop()
