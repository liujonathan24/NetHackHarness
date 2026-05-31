"""ASCII map widget: render a NetHack ``raw_grid`` with light colorization.

Pure display, no async. Caller updates `grid` and the widget refreshes.
"""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

# Character -> rich style. Keep the map deliberately small so unknown glyphs
# fall through as plain text (NetHack uses dozens of glyphs).
_STYLE: dict[str, str] = {
    "@": "bold yellow",
    ">": "bold cyan",
    "<": "bold cyan",
    "$": "bold yellow",
    ".": "dim",
    "#": "grey50",
    "|": "white",
    "-": "white",
    "+": "green",
    "f": "bold magenta",
    "d": "bold magenta",
    "F": "bold red",
}


def format_status(status: dict[str, object] | None) -> Text:
    """Render the NetHack status line (HP / AC / Dlvl / hunger / gold)."""
    if not status:
        return Text("(no status)", style="dim italic")
    hp = status.get("hp", "?")
    max_hp = status.get("max_hp", "?")
    ac = status.get("ac", "?")
    dlvl = status.get("dlvl", "?")
    hunger = status.get("hunger", "")
    gold = status.get("gold", 0)
    t = Text()
    t.append(f"HP {hp}/{max_hp}", style="bold red")
    t.append("  AC ", style="grey50")
    t.append(str(ac), style="bold")
    t.append("  Dlvl ", style="grey50")
    t.append(str(dlvl), style="bold cyan")
    t.append(f"  ${gold}", style="bold yellow")
    if hunger:
        t.append(f"  {hunger}", style="magenta")
    return t


class AsciiMap(Widget):
    """Render a list[str] grid with per-glyph color."""

    DEFAULT_CSS = """
    AsciiMap {
        height: auto;
        width: auto;
        padding: 0 1;
    }
    """

    grid: reactive[tuple[str, ...]] = reactive(tuple, layout=True)

    def __init__(self, grid: list[str] | None = None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.grid = tuple(grid or ())

    def update_grid(self, grid: list[str]) -> None:
        """Replace the grid (cheap; reactive triggers refresh)."""
        self.grid = tuple(grid)

    def render(self) -> Text:
        if not self.grid:
            return Text("(no map)", style="dim italic")
        out = Text()
        for i, row in enumerate(self.grid):
            for ch in row:
                style = _STYLE.get(ch, "")
                out.append(ch, style=style)
            if i != len(self.grid) - 1:
                out.append("\n")
        return out
