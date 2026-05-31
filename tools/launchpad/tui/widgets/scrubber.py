"""Scrubber: integer range slider with keyboard support.

Posts a ``Scrubber.Changed(value)`` message when value changes. Keys:
- left/right    : -1 / +1
- shift+left/right : -10 / +10
- home/end      : min / max
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget


class Scrubber(Widget, can_focus=True):
    """Linear position scrubber rendered as ``─◀ ────●──── ▶─``."""

    DEFAULT_CSS = """
    Scrubber {
        height: 1;
        width: 1fr;
        padding: 0 1;
    }
    Scrubber:focus {
        background: $boost;
    }
    """

    BINDINGS = [
        Binding("left", "step(-1)", "back"),
        Binding("right", "step(1)", "fwd"),
        Binding("shift+left", "step(-10)", "back 10"),
        Binding("shift+right", "step(10)", "fwd 10"),
        Binding("home", "jump('min')", "start"),
        Binding("end", "jump('max')", "end"),
    ]

    value: reactive[int] = reactive(0)
    minimum: reactive[int] = reactive(0)
    maximum: reactive[int] = reactive(0)

    class Changed(Message):
        """Emitted whenever ``value`` changes (including programmatic)."""

        def __init__(self, value: int) -> None:
            super().__init__()
            self.value = value

    def __init__(
        self,
        minimum: int = 0,
        maximum: int = 0,
        value: int = 0,
        **kw: object,
    ) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.minimum = minimum
        self.maximum = max(maximum, minimum)
        self.value = max(minimum, min(value, self.maximum))

    def set_range(self, minimum: int, maximum: int) -> None:
        self.minimum = minimum
        self.maximum = max(maximum, minimum)
        self.value = max(self.minimum, min(self.value, self.maximum))

    def watch_value(self, _old: int, new: int) -> None:
        self.post_message(self.Changed(new))

    def action_step(self, delta: int) -> None:
        nv = max(self.minimum, min(self.maximum, self.value + delta))
        if nv != self.value:
            self.value = nv

    def action_jump(self, where: str) -> None:
        self.value = self.minimum if where == "min" else self.maximum

    def render(self) -> Text:
        width = max(10, self.size.width - 12)
        span = max(1, self.maximum - self.minimum)
        frac = (self.value - self.minimum) / span if span else 0.0
        pos = int(frac * (width - 1))
        bar = ["─"] * width
        if 0 <= pos < width:
            bar[pos] = "●"
        t = Text()
        t.append("◀ ", style="cyan")
        t.append("".join(bar), style="white")
        t.append(" ▶ ", style="cyan")
        t.append(f"{self.value}/{self.maximum}", style="bold")
        return t
