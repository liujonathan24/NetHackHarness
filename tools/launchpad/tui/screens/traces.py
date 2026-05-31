"""Screen 4: TRACES — dual-pane (Observer / LLM view) + scrubber + live follow.

Layout (per SPEC.md "Screen mockups"):

    +-- runs rail ---+-- header --------------------------------------+
    |  ListView      |  run: <label> · rollout N/total · LIVE pill    |
    |  (RunSummary)  +-- scrubber ------------------------------------+
    |                |  ◀ ──●── ▶   step T/N   t:<wall>               |
    +-- rollouts ----+-- Observer ---------+-- LLM view --------------+
    |  ListView      |  status            |  system                   |
    |  (trace files) |  raw_grid          |  user (turn N)            |
    |                |  reward            |  assistant                |
    |                |                    |  tool_call                |
    +----------------+--------------------+---------------------------+
    | footer: keybindings                                             |
    +----------------------------------------------------------------+

Keybindings (per SPEC footer):
    left / right          : step ±1
    shift+left/right      : step ±10
    j / k                 : next / prev rollout
    f                     : toggle live follow
    g                     : goto-turn (prompt)
    home / end            : first / last turn
    r                     : refresh runs list

All I/O is async — `core.runs.list_runs`, `core.traces.read_trace`, and
`core.live.watch_file` are dispatched via `asyncio.create_task` and never
block the UI thread.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, Label, ListItem, ListView, Static

from tools.launchpad.core import live as live_mod
from tools.launchpad.core import runs as runs_mod
from tools.launchpad.core import traces as traces_mod
from tools.launchpad.tui.widgets import AsciiMap, LLMTurnView, LogTail, Scrubber
from tools.launchpad.types import RunSummary, TraceTurn


def format_status(status: dict | None) -> Text:
    """Compact one-liner derived from a TraceTurn's status dict."""
    if not status:
        return Text("(no status)", style="grey50")
    hp = status.get("hp")
    max_hp = status.get("max_hp")
    parts: list[str] = []
    if hp is not None and max_hp is not None:
        parts.append(f"HP {hp}/{max_hp}")
    elif hp is not None:
        parts.append(f"HP {hp}")
    for key, label in (("ac", "AC"), ("dlvl", "Dlvl"), ("gold", "$"), ("hunger", "")):
        v = status.get(key)
        if v is None or v == "":
            continue
        parts.append(f"{label}{':' if label and label != '$' else ''}{v}" if label else str(v))
    return Text("  ".join(parts) if parts else "(no status)", style="white")

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    """Best-effort repo root: env override > cwd."""
    env = os.environ.get("LAUNCHPAD_REPO")
    if env:
        return Path(env)
    return Path.cwd()


class _GotoTurnModal(ModalScreen[int]):
    """Tiny modal prompting for a 1-indexed turn number."""

    DEFAULT_CSS = """
    _GotoTurnModal {
        align: center middle;
    }
    _GotoTurnModal > Vertical {
        background: $panel;
        border: round $primary;
        padding: 1 2;
        width: 40;
        height: auto;
    }
    """

    BINDINGS = [Binding("escape", "dismiss(None)", "cancel")]

    def __init__(self, total: int) -> None:
        super().__init__()
        self._total = total

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Goto turn (1..{self._total}):")
            yield Input(placeholder=str(self._total), id="goto-input")

    @on(Input.Submitted, "#goto-input")
    def _on_submit(self, event: Input.Submitted) -> None:
        try:
            n = int(event.value.strip())
        except ValueError:
            self.dismiss(None)
            return
        self.dismiss(max(1, min(self._total, n)) - 1)


class TracesScreen(Screen):
    """Screen 4: TRACES — rail + scrubber + dual-pane Observer / LLM view."""

    DEFAULT_CSS = """
    TracesScreen {
        layout: vertical;
    }
    #traces-body {
        height: 1fr;
    }
    #rail {
        width: 28;
        background: $panel;
        border-right: solid $primary-darken-2;
    }
    #rail ListView {
        height: 1fr;
        border-bottom: solid $primary-darken-2;
    }
    #rail .rail-label {
        padding: 0 1;
        background: $boost;
        color: $text;
    }
    #main {
        width: 1fr;
    }
    #header-bar {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text;
    }
    #panes {
        height: 1fr;
    }
    #observer-pane {
        width: 1fr;
        border-right: solid $primary-darken-2;
    }
    #llm-pane {
        width: 1fr;
    }
    .pane-title {
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    #status-line {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text;
    }
    #reward-line {
        height: 1;
        padding: 0 1;
        color: $accent;
    }
    #empty-banner {
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
    }
    LogTail#follow-log {
        height: 4;
    }
    """

    BINDINGS = [
        Binding("left", "step(-1)", "step ←"),
        Binding("right", "step(1)", "step →"),
        Binding("shift+left", "step(-10)", "jump 10 ←"),
        Binding("shift+right", "step(10)", "jump 10 →"),
        Binding("home", "jump_first", "first"),
        Binding("end", "jump_last", "last"),
        Binding("j", "rollout(1)", "rollout ↓"),
        Binding("k", "rollout(-1)", "rollout ↑"),
        Binding("f", "toggle_follow", "follow"),
        Binding("g", "goto_turn", "goto-turn"),
        Binding("r", "refresh_runs", "refresh"),
    ]

    follow: reactive[bool] = reactive(True)

    # ------------------------------------------------------------------ ctor
    def __init__(self, repo_root: Path | None = None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self._repo_root = repo_root or _repo_root()
        self._runs: list[RunSummary] = []
        self._selected_run: RunSummary | None = None
        self._rollout_files: list[Path] = []
        self._rollout_entries: list[tuple[Path, int]] = []
        self._selected_rollout_idx: int = -1
        self._turns: list[TraceTurn] = []
        self._current_idx: int = 0
        self._live_task: asyncio.Task[None] | None = None
        self._loader_task: asyncio.Task[None] | None = None
        self._refresh_task: asyncio.Task[None] | None = None

    # --------------------------------------------------------------- compose
    def compose(self) -> ComposeResult:
        with Horizontal(id="traces-body"):
            with Vertical(id="rail"):
                yield Static("runs ▾", classes="rail-label")
                yield ListView(id="runs-list")
                yield Static("rollouts ▾", classes="rail-label")
                yield ListView(id="rollouts-list")
            with Vertical(id="main"):
                yield Static("(no run selected)", id="header-bar")
                yield Scrubber(id="scrubber")
                with Horizontal(id="panes"):
                    with Vertical(id="observer-pane"):
                        yield Static("Observer", classes="pane-title")
                        yield Static("(no status)", id="status-line")
                        yield VerticalScroll(AsciiMap(id="map"))
                        yield Static("", id="reward-line")
                    with Vertical(id="llm-pane"):
                        yield Static("LLM view", classes="pane-title")
                        yield VerticalScroll(LLMTurnView(id="llm"))
                yield LogTail(max_lines=64, empty_message="(follow off)", id="follow-log")

    # ----------------------------------------------------------------- mount
    def on_mount(self) -> None:
        self._refresh_task = asyncio.create_task(self._reload_runs())

    def on_unmount(self) -> None:
        self._cancel_live()
        for t in (self._loader_task, self._refresh_task):
            if t and not t.done():
                t.cancel()

    # ----------------------------------------------------- runs / rollout I/O
    async def _reload_runs(self) -> None:
        """Re-enumerate runs from disk (async wrapper around sync core.runs)."""
        try:
            runs = await asyncio.to_thread(
                runs_mod.list_runs, self._repo_root, None, None, 50
            )
        except FileNotFoundError as exc:
            log.info("no runs dir yet: %s", exc)
            runs = []
        except Exception:  # pragma: no cover - defensive
            log.exception("list_runs failed")
            runs = []
        self._runs = runs
        self._render_runs_list()

    def _render_runs_list(self) -> None:
        lv = self.query_one("#runs-list", ListView)
        lv.clear()
        if not self._runs:
            lv.append(ListItem(Label("(no runs yet — launch one with `launchpad eval`)")))
            return
        for r in self._runs:
            label_text = self._format_run_row(r)
            lv.append(ListItem(Label(label_text)))

    def _format_run_row(self, r: RunSummary) -> Text:
        line = Text()
        if r.status == "running":
            line.append("● ", style="bold red")
        elif r.status == "done":
            line.append("✓ ", style="green")
        elif r.status == "failed":
            line.append("✗ ", style="bold red")
        else:
            line.append("· ", style="grey50")
        line.append(r.label, style="bold")
        reward = r.metrics.get("scout") or r.metrics.get("reward")
        if reward is not None:
            line.append(f"  {float(reward):.2f}", style="cyan")
        return line

    def _render_rollouts_list(self) -> None:
        lv = self.query_one("#rollouts-list", ListView)
        lv.clear()
        if not self._rollout_entries:
            lv.append(ListItem(Label("(no rollouts)")))
            return
        total = len(self._rollout_entries)
        for i, (p, sample_idx) in enumerate(self._rollout_entries):
            if p.suffix == ".json":
                label = f"rollout {i + 1}/{total} · sample {sample_idx} (legacy)"
            else:
                label = f"rollout {i + 1}/{total} · {p.name}"
            lv.append(ListItem(Label(label)))

    # ----------------------------------------------------------- list events
    @on(ListView.Selected, "#runs-list")
    def _on_run_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(self._runs):
            return
        self._selected_run = self._runs[idx]
        files = list(runs_mod.iter_trace_files(self._selected_run))
        # Expand legacy samples JSON into one entry per sample.
        from tools.launchpad.core.legacy_trace import count_samples, is_legacy_samples_file
        self._rollout_entries: list[tuple[Path, int]] = []
        for p in files:
            if p.suffix == ".json" and is_legacy_samples_file(p):
                n = count_samples(p)
                for i in range(n):
                    self._rollout_entries.append((p, i))
            else:
                self._rollout_entries.append((p, 0))
        self._rollout_files = [e[0] for e in self._rollout_entries]
        self._render_rollouts_list()
        self._update_header()
        if self._rollout_entries:
            self.query_one("#rollouts-list", ListView).index = 0
            self._select_rollout(0)
        else:
            self._turns = []
            self._current_idx = 0
            self._refresh_panes()

    @on(ListView.Selected, "#rollouts-list")
    def _on_rollout_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(self._rollout_files):
            return
        self._select_rollout(idx)

    def _select_rollout(self, idx: int) -> None:
        self._selected_rollout_idx = idx
        self._cancel_live()
        if self._loader_task and not self._loader_task.done():
            self._loader_task.cancel()
        path, sample_idx = self._rollout_entries[idx]
        self._loader_task = asyncio.create_task(self._load_turns(path, sample_idx))

    async def _load_turns(self, path: Path, sample_idx: int = 0) -> None:
        try:
            turns = await asyncio.to_thread(traces_mod.read_trace, path, sample_idx)
        except FileNotFoundError:
            turns = []
        except Exception:  # pragma: no cover - defensive
            log.exception("read_trace failed for %s", path)
            turns = []
        self._turns = turns
        self._current_idx = max(0, len(turns) - 1) if self.follow else 0
        self._refresh_panes()
        if self.follow:
            self._start_live(path)

    # ------------------------------------------------------------ live mode
    def _start_live(self, path: Path) -> None:
        self._cancel_live()
        self._live_task = asyncio.create_task(self._follow(path))
        self._log_follow(f"[live] following {path.name}")

    def _cancel_live(self) -> None:
        if self._live_task and not self._live_task.done():
            self._live_task.cancel()
        self._live_task = None

    async def _follow(self, path: Path) -> None:
        try:
            async for turn in live_mod.watch_file(path):
                # Avoid double-counting the historical replay returned by
                # `watch_file` (it emits existing turns first). If the turn we
                # got matches one we already have, skip; otherwise append.
                if self._turns and turn.turn <= self._turns[-1].turn:
                    continue
                self._turns.append(turn)
                if self.follow:
                    self._current_idx = len(self._turns) - 1
                self._refresh_panes()
        except asyncio.CancelledError:
            raise
        except FileNotFoundError:
            self._log_follow(f"[live] file gone: {path.name}")
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("live follow failed")
            self._log_follow(f"[live] error: {exc!r}")

    def _log_follow(self, line: str) -> None:
        try:
            self.query_one("#follow-log", LogTail).append(line, kind="info")
        except Exception:
            pass

    # ----------------------------------------------------------- rendering
    def _update_header(self) -> None:
        hdr = self.query_one("#header-bar", Static)
        if self._selected_run is None:
            hdr.update("(no run selected)")
            return
        r = self._selected_run
        n_roll = max(len(self._rollout_files), r.n_rollouts)
        roll = self._selected_rollout_idx + 1 if self._selected_rollout_idx >= 0 else 0
        pill = "  LIVE" if (self.follow and self._live_task is not None) else ""
        hdr.update(
            Text.assemble(
                ("run: ", "grey50"),
                (r.label, "bold"),
                ("  rollout ", "grey50"),
                (f"{roll}/{n_roll}", "bold"),
                (pill, "bold red"),
            )
        )

    def _refresh_panes(self) -> None:
        scrubber = self.query_one("#scrubber", Scrubber)
        scrubber.set_range(0, max(0, len(self._turns) - 1))
        if not self._turns:
            scrubber.value = 0
            self.query_one("#map", AsciiMap).update_grid([])
            self.query_one("#status-line", Static).update("(no turns yet)")
            self.query_one("#reward-line", Static).update("")
            self.query_one("#llm", LLMTurnView).update_turn(None)
            self._update_header()
            return
        self._current_idx = max(0, min(self._current_idx, len(self._turns) - 1))
        scrubber.value = self._current_idx
        turn = self._turns[self._current_idx]
        self.query_one("#map", AsciiMap).update_grid(turn.raw_grid)
        self.query_one("#status-line", Static).update(format_status(turn.status))
        rwd = Text()
        rwd.append(f"reward: {turn.reward:+.3f}", style="bold yellow")
        if turn.dlvl is not None:
            rwd.append(f"   dlvl {turn.dlvl}", style="cyan")
        self.query_one("#reward-line", Static).update(rwd)
        self.query_one("#llm", LLMTurnView).update_turn(turn)
        self._update_header()

    # ----------------------------------------------------- scrubber bridge
    @on(Scrubber.Changed)
    def _on_scrub(self, event: Scrubber.Changed) -> None:
        if 0 <= event.value < len(self._turns) and event.value != self._current_idx:
            self._current_idx = event.value
            # Manual scrub disengages follow per SPEC.
            if self.follow:
                self.follow = False
                self._log_follow("[live] follow off (manual scrub)")
            self._refresh_panes()

    # ----------------------------------------------------- actions (keys)
    def action_step(self, delta: int) -> None:
        if not self._turns:
            return
        new_idx = max(0, min(len(self._turns) - 1, self._current_idx + delta))
        if new_idx != self._current_idx:
            self._current_idx = new_idx
            if self.follow and new_idx != len(self._turns) - 1:
                self.follow = False
            self._refresh_panes()

    def action_jump_first(self) -> None:
        if self._turns:
            self.follow = False
            self._current_idx = 0
            self._refresh_panes()

    def action_jump_last(self) -> None:
        if self._turns:
            self._current_idx = len(self._turns) - 1
            self._refresh_panes()

    def action_rollout(self, delta: int) -> None:
        if not self._rollout_files:
            return
        new = max(0, min(len(self._rollout_files) - 1, self._selected_rollout_idx + delta))
        if new == self._selected_rollout_idx:
            return
        self.query_one("#rollouts-list", ListView).index = new
        self._select_rollout(new)

    def action_toggle_follow(self) -> None:
        self.follow = not self.follow
        if self.follow:
            if self._turns:
                self._current_idx = len(self._turns) - 1
                self._refresh_panes()
            if self._selected_rollout_idx >= 0:
                self._start_live(self._rollout_files[self._selected_rollout_idx])
        else:
            self._cancel_live()
            self._log_follow("[live] follow off")
            self._update_header()

    def action_refresh_runs(self) -> None:
        if self._refresh_task and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._reload_runs())

    def action_goto_turn(self) -> None:
        if not self._turns:
            return

        def _set(result: int | None) -> None:
            if result is None:
                return
            self._current_idx = result
            if self.follow and result != len(self._turns) - 1:
                self.follow = False
            self._refresh_panes()

        self.app.push_screen(_GotoTurnModal(len(self._turns)), _set)
