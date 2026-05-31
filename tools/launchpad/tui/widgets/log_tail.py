"""LogTail — append-only streaming text widget.

Backs the TRAIN screen's stdout/stderr tail. Bounded ring so a runaway log
doesn't blow up memory.
"""

from __future__ import annotations

from collections import deque

from rich.console import Group
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class LogTail(Static):
    """Rolling tail of log lines. Newest at the bottom."""

    DEFAULT_CSS = """
    LogTail {
        height: auto;
        width: 100%;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    """

    revision: reactive[int] = reactive(0)

    def __init__(
        self,
        *,
        max_lines: int = 200,
        empty_message: str = "(no output yet)",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._lines: deque[tuple[str, str]] = deque(maxlen=max(8, int(max_lines)))
        self._empty_message = empty_message

    def append(self, line: str, *, kind: str = "stdout") -> None:
        """Append one line (kind ∈ {'stdout','stderr','info'}) and re-render."""
        self._lines.append((kind, line.rstrip("\n")))
        self.revision += 1

    def clear(self) -> None:
        self._lines.clear()
        self.revision += 1

    def on_mount(self) -> None:  # type: ignore[override]
        # Static's renderable is set via `update`; without an initial call the
        # placeholder text isn't rendered.
        self.update(self._build_renderable())

    def watch_revision(self, _old: int, _new: int) -> None:
        self.update(self._build_renderable())

    def _build_renderable(self) -> Group:
        if not self._lines:
            return Group(Text(self._empty_message, style="dim italic"))
        text = Text()
        for kind, line in self._lines:
            style = {
                "stderr": "red",
                "stdout": "white",
                "info": "cyan",
            }.get(kind, "white")
            text.append(line + "\n", style=style)
        return Group(text)
