"""Screen 3: HARNESS — browse harness TOMLs, edit in ``$EDITOR``, diff vs default.

Layout (matches the ASCII mockup in ``SPEC.md`` section "Screen mockups"):

    +----------------------+----------------------------------------------------+
    | harnesses (rail)     |  [ Edit in $EDITOR ]  [ Diff vs default ]          |
    |  * default           |  -- system_prompt (mode: replace) ----------       |
    |    descend_aggr *    |  ...                                               |
    |    journal_heavy     |  -- per_step_prompt ------------------------       |
    |  [+ new]             |  ...                                               |
    |                      |  -- tools -----------------------------------      |
    |                      |  ...                                               |
    |                      |  -- rewards (overrides) ---------------------      |
    |                      |  ...                                               |
    |                      |  -- PREVIEW: what the LLM sees on turn 0 ----      |
    |                      |  [scrollable; re-renders on save]                  |
    +----------------------+----------------------------------------------------+
    | e:edit  d:diff  n:new  r:reload  j/k:select  q:quit                      |
    +-------------------------------------------------------------------------+

Empty-state behaviour: if ``harnesses_dir()`` has no TOMLs the rail renders
"No harnesses yet — try `launchpad harness new <name>`" and the preview pane
stays empty. The screen never blocks the UI thread:

  - Loading the harness list is cheap (sync) but the call is dispatched off
    the compose path via ``call_after_refresh`` so first paint is instant.
  - ``edit_harness`` shells out via ``subprocess`` *inside* a worker thread
    started with ``app.run_worker(..., thread=True)`` so the event loop keeps
    pumping while ``$EDITOR`` owns the terminal. On worker completion we
    re-read the file and refresh the preview.
  - ``preview_harness`` runs in an asyncio task (``asyncio.to_thread``) so
    even a slow runtime renderer never freezes the screen > 16 ms.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Static

from tools.launchpad.core import harness as H
from tools.launchpad.tui.widgets.llm_turn import LLMTurnView
from tools.launchpad.types import HarnessConfig, TraceTurn

if TYPE_CHECKING:
    from textual.worker import Worker

log = logging.getLogger(__name__)


# Sentinel rail entry — selecting it opens the "create new harness" prompt.
_NEW_ROW = "<new>"
_DEFAULT_NAME = "default"


class HarnessScreen(Screen):
    """Screen 3: HARNESS.

    Public reactive state:
        selected_name   currently-highlighted harness in the rail
        dirty           True if the on-disk file has been edited since last load
    """

    BINDINGS = [
        Binding("e", "edit", "Edit in $EDITOR"),
        Binding("d", "diff", "Diff vs default"),
        Binding("n", "new", "New harness"),
        Binding("r", "reload", "Reload"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    HarnessScreen {
        layout: vertical;
    }
    HarnessScreen #body {
        height: 1fr;
        width: 100%;
    }
    HarnessScreen #rail {
        width: 28;
        min-width: 22;
        border-right: solid $accent;
        padding: 1 1;
    }
    HarnessScreen #rail-title, HarnessScreen #pane-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    HarnessScreen #rail-list {
        height: 1fr;
    }
    HarnessScreen #pane {
        width: 1fr;
        padding: 1 2;
    }
    HarnessScreen #buttons {
        height: 3;
        padding: 0 0 1 0;
    }
    HarnessScreen #buttons Button {
        margin: 0 1 0 0;
    }
    HarnessScreen .section-title {
        text-style: bold underline;
        color: $accent;
        padding: 1 0 0 0;
    }
    HarnessScreen #diff-panel {
        height: auto;
        max-height: 14;
        border: solid $warning;
        padding: 0 1;
        margin: 1 0;
        display: none;
    }
    HarnessScreen #diff-panel.visible {
        display: block;
    }
    HarnessScreen #status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    selected_name: reactive[str | None] = reactive(None)
    dirty: reactive[bool] = reactive(False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._harnesses: list[HarnessConfig] = []
        self._current: HarnessConfig | None = None
        self._rail_rev: int = 0
        # Created in compose(); we keep handles so action_* can target them.
        self._rail: ListView | None = None
        self._title: Static | None = None
        self._system_pane: Static | None = None
        self._per_step_pane: Static | None = None
        self._tools_pane: Static | None = None
        self._rewards_pane: Static | None = None
        self._diff_panel: Static | None = None
        self._preview: LLMTurnView | None = None
        self._status: Static | None = None

    # ------------------------------------------------------------------ compose

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="rail"):
                yield Static("harnesses", id="rail-title")
                self._rail = ListView(id="rail-list")
                yield self._rail
            with VerticalScroll(id="pane"):
                self._title = Static("(no harness loaded)", id="pane-title")
                yield self._title
                with Horizontal(id="buttons"):
                    yield Button("Edit in $EDITOR", id="btn-edit", variant="primary")
                    yield Button("Diff vs default", id="btn-diff")
                    yield Button("New", id="btn-new")
                yield Static("system_prompt", classes="section-title")
                self._system_pane = Static("")
                yield self._system_pane
                yield Static("per_step_prompt", classes="section-title")
                self._per_step_pane = Static("")
                yield self._per_step_pane
                yield Static("tools", classes="section-title")
                self._tools_pane = Static("")
                yield self._tools_pane
                yield Static("rewards (overrides)", classes="section-title")
                self._rewards_pane = Static("")
                yield self._rewards_pane
                self._diff_panel = Static("", id="diff-panel")
                yield self._diff_panel
                yield Static(
                    "PREVIEW: what the LLM sees on turn 0",
                    classes="section-title",
                )
                self._preview = LLMTurnView()
                yield self._preview
        self._status = Static("", id="status")
        yield self._status
        yield Footer()

    # ------------------------------------------------------------------ mount

    def on_mount(self) -> None:
        # Defer the initial load until after first paint so the screen
        # appears instantly even on slow disks.
        self.call_after_refresh(self._reload_rail)

    # ------------------------------------------------------------------ data ops

    def _reload_rail(self) -> None:
        """(Re)populate the rail from ``list_harnesses()``."""
        try:
            self._harnesses = H.list_harnesses()
        except OSError as exc:
            log.warning("could not list harnesses: %s", exc)
            self._harnesses = []
        if self._rail is None:
            return
        # ListView.clear() is async; remove children synchronously so the
        # rebuild below can't race with stale IDs. Suffix each ID with a
        # revision counter so even a fast double-reload stays unique.
        for child in list(self._rail.children):
            child.remove()
        self._rail_rev += 1
        rev = self._rail_rev
        if not self._harnesses:
            self._rail.append(
                ListItem(
                    Static(
                        "No harnesses yet —\n"
                        "try `launchpad harness new <name>`",
                        markup=False,
                    ),
                    id=f"row-empty-{rev}",
                )
            )
            self._set_status("No harnesses found.")
            self._clear_pane()
            return
        for cfg in self._harnesses:
            label = f"* {cfg.name}" if cfg.name == _DEFAULT_NAME else f"  {cfg.name}"
            self._rail.append(
                ListItem(
                    Static(label, markup=False),
                    id=f"row-{cfg.name}-{rev}",
                )
            )
        self._rail.append(
            ListItem(Static("[+ new]", markup=False), id=f"row-new-{rev}")
        )
        # If nothing selected yet, default to the first real entry.
        if self.selected_name is None:
            self.selected_name = self._harnesses[0].name
        # Sync rail highlight with selected_name.
        self._highlight_selected()

    def _highlight_selected(self) -> None:
        if self._rail is None or self.selected_name is None:
            return
        for i, cfg in enumerate(self._harnesses):
            if cfg.name == self.selected_name:
                self._rail.index = i
                break

    def _load_selected(self) -> None:
        """Load the current ``selected_name`` and refresh all panes."""
        name = self.selected_name
        if not name or name == _NEW_ROW:
            return
        try:
            self._current = H.load_harness(name)
        except (FileNotFoundError, ValueError) as exc:
            self._set_status(f"load failed: {exc}")
            self._current = None
            return
        self.dirty = False
        self._render_panes()
        # Preview can be slow (it may try to import the nethack runtime);
        # run it off the event loop so the UI stays responsive.
        asyncio.create_task(self._refresh_preview_async(name))

    async def _refresh_preview_async(self, name: str) -> None:
        try:
            text = await asyncio.to_thread(H.preview_harness, name)
        except (FileNotFoundError, ValueError) as exc:
            text = f"(preview failed: {exc})"
        if self._preview is None or self.selected_name != name:
            return
        synthetic_turn = TraceTurn(turn=0, rendered_user_message=text)
        system = (
            self._current.system_prompt.text if self._current is not None else ""
        )
        self._preview.system_prompt = system
        self._preview.update_turn(synthetic_turn)

    # ------------------------------------------------------------------ render panes

    def _clear_pane(self) -> None:
        if self._title is not None:
            self._title.update("(no harness loaded)")
        for pane in (
            self._system_pane,
            self._per_step_pane,
            self._tools_pane,
            self._rewards_pane,
        ):
            if pane is not None:
                pane.update("")
        if self._diff_panel is not None:
            self._diff_panel.remove_class("visible")
            self._diff_panel.update("")
        if self._preview is not None:
            self._preview.update_turn(None)

    def _render_panes(self) -> None:
        cfg = self._current
        if cfg is None or self._title is None:
            return
        suffix = " (dirty)" if self.dirty else ""
        self._title.update(f"{cfg.name}{suffix}")

        sp = cfg.system_prompt
        if self._system_pane is not None:
            self._system_pane.update(
                f"mode: {sp.mode}\n\n{sp.text or '(empty)'}"
            )

        psp = cfg.per_step_prompt
        if self._per_step_pane is not None:
            self._per_step_pane.update(
                "\n".join(
                    [
                        f"template = {psp.template}",
                        f"include_inventory  = {psp.include_inventory}",
                        f"include_messages_n = {psp.include_messages_n}",
                        f"include_adjacent   = {psp.include_adjacent}",
                        f"include_visible    = {psp.include_visible}",
                        f"map_window         = {list(psp.map_window)}",
                        f"ascii_legend       = {psp.ascii_legend}",
                    ]
                )
            )

        tools = cfg.tools
        if self._tools_pane is not None:
            enabled = " ".join(tools.enabled) or "(none)"
            disabled = " ".join(tools.disabled) or "(none)"
            overrides_lines = []
            for tool_name, overrides in tools.overrides.items():
                for k, v in overrides.items():
                    overrides_lines.append(f"  {tool_name}.{k} = {v!r}")
            overrides_text = "\n".join(overrides_lines) if overrides_lines else ""
            tools_body = f"enabled : {enabled}\ndisabled: {disabled}"
            if overrides_text:
                tools_body += f"\noverrides:\n{overrides_text}"
            self._tools_pane.update(tools_body)

        if self._rewards_pane is not None:
            if not cfg.rewards:
                self._rewards_pane.update("(none — inherits defaults)")
            else:
                self._rewards_pane.update(
                    "\n".join(f"{k:<12} ×{v}" for k, v in cfg.rewards.items())
                )

    # ------------------------------------------------------------------ actions

    def action_reload(self) -> None:
        """Re-scan ``harnesses_dir()`` and refresh the selected harness."""
        self._reload_rail()
        if self.selected_name:
            self._load_selected()
        self._set_status("reloaded")

    def action_cursor_down(self) -> None:
        if self._rail is not None:
            self._rail.action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._rail is not None:
            self._rail.action_cursor_up()

    def action_diff(self) -> None:
        """Toggle the diff-vs-default panel."""
        if self._current is None or self._diff_panel is None:
            return
        if "visible" in self._diff_panel.classes:
            self._diff_panel.remove_class("visible")
            self._diff_panel.update("")
            return
        if self._current.name == _DEFAULT_NAME:
            self._diff_panel.update("(this IS default — nothing to diff)")
        else:
            try:
                text = H.diff_harness(self._current.name, against=_DEFAULT_NAME)
            except (FileNotFoundError, ValueError) as exc:
                text = f"(diff failed: {exc})"
            self._diff_panel.update(text or "(no differences)")
        self._diff_panel.add_class("visible")

    def action_new(self) -> None:
        """Create a uniquely-named harness extending default."""
        existing = {c.name for c in self._harnesses}
        base = "harness_new"
        candidate = base
        n = 1
        while candidate in existing:
            n += 1
            candidate = f"{base}_{n}"
        try:
            H.create_harness(candidate, extends=_DEFAULT_NAME)
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            self._set_status(f"create failed: {exc}")
            return
        self.selected_name = candidate
        self._reload_rail()
        self._load_selected()
        self._set_status(f"created {candidate}")

    def action_edit(self) -> None:
        """Shell out to ``$EDITOR`` in a worker thread, then refresh."""
        if self._current is None:
            self._set_status("no harness selected")
            return
        name = self._current.name
        self._set_status(f"editing {name} in $EDITOR …")
        # thread=True so blocking subprocess.run doesn't stall the event loop.
        self.app.run_worker(
            self._edit_worker(name),
            name=f"edit-{name}",
            thread=False,
            exclusive=True,
        )

    async def _edit_worker(self, name: str) -> None:
        try:
            rc = await asyncio.to_thread(H.edit_harness, name)
        except FileNotFoundError as exc:
            self._set_status(f"editor failed: {exc}")
            return
        self._set_status(f"$EDITOR exited (rc={rc}); reloading")
        self.dirty = False
        self._load_selected()

    # ------------------------------------------------------------------ events

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-edit":
            self.action_edit()
        elif event.button.id == "btn-diff":
            self.action_diff()
        elif event.button.id == "btn-new":
            self.action_new()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if item is None or item.id is None:
            return
        # IDs look like "row-<name>-<rev>" or "row-new-<rev>" / "row-empty-<rev>".
        if not item.id.startswith("row-"):
            return
        body = item.id[len("row-") :]
        # Strip trailing "-<rev>" once.
        if "-" in body:
            name_part, _, _ = body.rpartition("-")
        else:
            name_part = body
        if name_part in ("new", "empty", ""):
            return
        if name_part != self.selected_name:
            self.selected_name = name_part

    def watch_selected_name(self, _old: str | None, new: str | None) -> None:
        if new and new != _NEW_ROW:
            self._load_selected()

    def watch_dirty(self, _old: bool, _new: bool) -> None:
        # Title contains a "(dirty)" suffix; just re-render.
        self._render_panes()

    # ------------------------------------------------------------------ helpers

    def _set_status(self, msg: str) -> None:
        if self._status is not None:
            self._status.update(msg)


__all__ = ["HarnessScreen"]
