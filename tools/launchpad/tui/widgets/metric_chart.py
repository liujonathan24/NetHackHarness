"""MetricChart — minimal ASCII sparkline widget for streaming TrainMetric values.

Designed for the TRAIN screen's "live" panel. Holds a small in-memory ring of
recent values per metric name and re-renders on `push`/`extend`. Rendering is
pure-Python (no third-party sparkline lib) so it works over plain SSH.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from tools.launchpad.types import TrainMetric

# Unicode "block" sparkline characters, low -> high.
_BLOCKS: str = " ▁▂▃▄▅▆▇█"


def _sparkline(values: list[float], width: int) -> str:
    """Render `values` as a sparkline at most `width` columns wide."""
    if not values:
        return ""
    # Sample down to `width` if necessary by simple right-truncation (we want
    # the most-recent slice, which is what users care about).
    if len(values) > width:
        values = values[-width:]
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0:
        # Flat line: pick a mid block.
        return _BLOCKS[len(_BLOCKS) // 2] * len(values)
    out: list[str] = []
    for v in values:
        norm = (v - lo) / span
        idx = int(round(norm * (len(_BLOCKS) - 1)))
        idx = max(0, min(len(_BLOCKS) - 1, idx))
        out.append(_BLOCKS[idx])
    return "".join(out)


class MetricChart(Static):
    """Sparkline rendering of one or more named metric series.

    Usage:
        chart = MetricChart(series=("loss", "kl", "eval/reward"), width=40)
        chart.push(metric)        # one TrainMetric
        chart.extend(iterable)    # many

    The widget is fully synchronous; async producers should call `push` from
    their event loop (each call is O(1) + an O(width) re-render).
    """

    # Bumping this forces a re-render via Textual's reactive system.
    revision: reactive[int] = reactive(0)

    DEFAULT_CSS = """
    MetricChart {
        height: auto;
        width: 100%;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        series: Iterable[str] = ("loss", "kl", "eval/reward"),
        *,
        width: int = 40,
        history: int = 256,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._series_order: list[str] = list(series)
        self._width: int = max(8, int(width))
        self._history: int = max(self._width, int(history))
        self._data: dict[str, deque[float]] = {
            s: deque(maxlen=self._history) for s in self._series_order
        }

    # ------------------------------------------------------------------ API
    def push(self, metric: TrainMetric) -> None:
        """Append one metric value. Unknown series names are silently ignored."""
        buf = self._data.get(metric.name)
        if buf is None:
            return
        buf.append(float(metric.value))
        self.revision += 1

    def extend(self, metrics: Iterable[TrainMetric]) -> None:
        for m in metrics:
            buf = self._data.get(m.name)
            if buf is not None:
                buf.append(float(m.value))
        self.revision += 1

    def reset(self) -> None:
        for buf in self._data.values():
            buf.clear()
        self.revision += 1

    def set_width(self, width: int) -> None:
        self._width = max(8, int(width))
        self.revision += 1

    # ---------------------------------------------------------------- render
    def watch_revision(self, _old: int, _new: int) -> None:
        self.update(self._build_renderable())

    def on_mount(self) -> None:  # type: ignore[override]
        # Static's renderable is set via `update`; without an initial call the
        # placeholder text isn't rendered.
        self.update(self._build_renderable())

    def _build_renderable(self) -> Text:
        text = Text()
        any_data = False
        for name in self._series_order:
            buf = self._data[name]
            if not buf:
                line = Text.assemble(
                    (f"{name:>12} ", "dim"),
                    ("(no data yet)", "dim italic"),
                )
            else:
                any_data = True
                spark = _sparkline(list(buf), self._width)
                last = buf[-1]
                line = Text.assemble(
                    (f"{name:>12} ", "bold"),
                    (spark, "cyan"),
                    (f"  {last:.4g}", "white"),
                )
            text.append_text(line)
            text.append("\n")
        if not any_data:
            text.append("(waiting for metrics)", style="dim italic")
        return text
