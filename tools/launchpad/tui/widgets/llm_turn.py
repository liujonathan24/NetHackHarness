"""LLMTurnView: render the system/user/assistant/tool_calls of one ``TraceTurn``.

Display-only. Use ``update_turn(turn)`` to swap content.
"""

from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from tools.launchpad.types import TraceTurn


class LLMTurnView(Widget):
    """Renders the LLM side of one turn (user message + assistant + tool calls)."""

    DEFAULT_CSS = """
    LLMTurnView {
        height: auto;
        width: auto;
        padding: 0 1;
    }
    """

    turn: reactive[TraceTurn | None] = reactive(None, layout=True)
    system_prompt: reactive[str] = reactive("", layout=True)

    def __init__(
        self,
        turn: TraceTurn | None = None,
        system_prompt: str = "",
        **kw: object,
    ) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.turn = turn
        self.system_prompt = system_prompt

    def update_turn(self, turn: TraceTurn | None) -> None:
        self.turn = turn

    def render(self) -> Group:
        if self.turn is None:
            return Group(Text("(no turn selected)", style="dim italic"))
        t = self.turn
        panels: list[Panel | Text] = []
        if self.system_prompt:
            panels.append(
                Panel(
                    Text(self.system_prompt, overflow="fold"),
                    title="system",
                    border_style="grey50",
                )
            )
        user_body = t.rendered_user_message or "(empty)"
        panels.append(
            Panel(
                Text(user_body, overflow="fold"),
                title=f"user (turn {t.turn})",
                border_style="cyan",
            )
        )
        assistant_body = t.assistant_message or "(empty)"
        panels.append(
            Panel(
                Text(assistant_body, overflow="fold"),
                title="assistant",
                border_style="green",
            )
        )
        if t.tool_calls:
            tc_text = Text()
            for i, tc in enumerate(t.tool_calls):
                if i:
                    tc_text.append("\n")
                tc_text.append(f"{tc.name or '?'}(", style="bold yellow")
                tc_text.append(tc.arguments or "", style="white")
                tc_text.append(")", style="bold yellow")
            panels.append(
                Panel(tc_text, title="tool_calls", border_style="yellow")
            )
        return Group(*panels)
