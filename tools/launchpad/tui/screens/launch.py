"""Screen 1: LAUNCH — compose a LaunchSpec and fire an eval.

Layout (see SPEC.md "Screen mockups"):

    Label / Model / Harness / Tier / Max turns / N / R / Tags
    [ Launch ] [ Launch & watch ] [ Dry run ] [ Save as TOML ]
    --- recent ----
    <recent runs list>

Footer keybindings:
    enter   Launch        (focus on a button activates it)
    ctrl+l  Launch
    ctrl+w  Launch & watch
    ctrl+d  Dry run
    ctrl+s  Save as TOML
    r       Refresh recent runs
    1..4    cycle screens (App-level)
    q       quit          (App-level)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import tomli_w
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Select, Static

from tools.launchpad.core import harness as harness_mod
from tools.launchpad.core import launcher, runs
from tools.launchpad.types import LaunchSpec, RunSummary

log = logging.getLogger(__name__)

_TIER_CHOICES: tuple[str, ...] = (
    "descend_to_dlvl_3",
    "corridor_explore",
    "scout_only",
    "ascension",
)
_MODEL_CHOICES: tuple[str, ...] = (
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4o-mini",
    "claude-opus-4-7",
    "claude-sonnet-4-7",
    "Qwen/Qwen2.5-7B-Instruct",
)


def _fmt_dur(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _fmt_metric(summary: RunSummary) -> str:
    m = summary.metrics
    parts: list[str] = []
    if "scout" in m:
        parts.append(f"scout {m['scout']:.2f}")
    if "descent" in m:
        parts.append(f"desc {m['descent']:.2f}")
    if not parts and "reward" in m:
        parts.append(f"r {m['reward']:.2f}")
    return "  ".join(parts) if parts else "—"


def _repo_root() -> Path:
    """Repo root: $LAUNCHPAD_REPO if set, else cwd."""
    env = os.environ.get("LAUNCHPAD_REPO")
    return Path(env).resolve() if env else Path.cwd().resolve()


class RecentRunsList(VerticalScroll):
    """Scrollable rail of recent runs (eval kind, newest first)."""

    DEFAULT_CSS = """
    RecentRunsList {
        height: 1fr;
        border: round $primary 30%;
        padding: 0 1;
    }
    """

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._empty = Static(
            Text(
                "No runs yet — launch one with `launchpad eval`.",
                style="dim italic",
            )
        )

    def populate(self, summaries: list[RunSummary]) -> None:
        # Clear children then re-mount. Static rows; no in-place editing needed.
        self.remove_children()
        if not summaries:
            self.mount(self._empty)
            return
        for s in summaries:
            self.mount(Static(self._format_row(s), classes="run-row"))

    @staticmethod
    def _format_row(s: RunSummary) -> Text:
        dot = {
            "running": ("● ", "yellow"),
            "done": ("● ", "green"),
            "failed": ("● ", "red"),
            "unknown": ("○ ", "grey50"),
        }.get(s.status, ("○ ", "grey50"))
        t = Text()
        t.append(dot[0], style=dot[1])
        t.append(f"{s.label:<32.32} ", style="bold")
        t.append(f"{s.status:<8} ", style="cyan")
        t.append(f"{_fmt_metric(s):<24} ", style="white")
        if s.finished_at and s.started_at:
            t.append(f"t={_fmt_dur(s.finished_at - s.started_at)}", style="grey70")
        elif s.n_rollouts:
            t.append(f"n={s.n_rollouts}", style="grey70")
        return t


class LaunchScreen(Screen):
    """Screen 1: LAUNCH — compose a LaunchSpec and fire an eval."""

    DEFAULT_CSS = """
    LaunchScreen {
        layout: vertical;
    }
    #form {
        height: auto;
        padding: 1 2;
        border: round $primary 30%;
    }
    .row {
        height: auto;
        width: 1fr;
        margin-bottom: 1;
    }
    .row Label {
        width: 14;
        content-align: left middle;
        color: $text-muted;
    }
    .row Input, .row Select {
        width: 1fr;
    }
    #buttons {
        height: 3;
        padding: 0 2;
    }
    #buttons Button {
        margin-right: 2;
    }
    #status_line {
        height: 1;
        padding: 0 2;
        color: $accent;
    }
    #recent_header {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    #recent_wrap {
        height: 1fr;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+l", "launch(False)", "Launch", show=True),
        Binding("ctrl+w", "launch(True)", "Launch & watch", show=True),
        Binding("ctrl+d", "dry_run", "Dry run", show=True),
        Binding("ctrl+s", "save_toml", "Save TOML", show=True),
        Binding("r", "refresh_runs", "Refresh", show=True),
    ]

    status_text: reactive[str] = reactive("")

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._repo = _repo_root()
        self._refresh_task: asyncio.Task[None] | None = None
        self._launch_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        # Discover harness names lazily; failure is non-fatal.
        try:
            harness_names = [h.name for h in harness_mod.list_harnesses()]
        except Exception as exc:  # noqa: BLE001 - cosmetic only
            log.warning("could not list harnesses: %s", exc)
            harness_names = []
        if not harness_names:
            harness_names = ["default"]

        with Vertical(id="form"):
            with Horizontal(classes="row"):
                yield Label("Label:")
                yield Input(
                    placeholder="wave3_E2_descend_smoke",
                    value=self._default_label(),
                    id="in_label",
                )
            with Horizontal(classes="row"):
                yield Label("Model:")
                yield Select(
                    [(m, m) for m in _MODEL_CHOICES],
                    value=_MODEL_CHOICES[0],
                    allow_blank=False,
                    id="in_model",
                )
                yield Label("Harness:")
                yield Select(
                    [(n, n) for n in harness_names],
                    value=harness_names[0],
                    allow_blank=False,
                    id="in_harness",
                )
            with Horizontal(classes="row"):
                yield Label("Tier:")
                yield Select(
                    [(t, t) for t in _TIER_CHOICES],
                    value=_TIER_CHOICES[0],
                    allow_blank=False,
                    id="in_tier",
                )
                yield Label("Max turns:")
                yield Input(value="200", id="in_max_turns")
            with Horizontal(classes="row"):
                yield Label("N ex:")
                yield Input(value="4", id="in_n")
                yield Label("Rollouts/ex:")
                yield Input(value="2", id="in_r")
                yield Label("Tags:")
                yield Input(placeholder="wave3,smoke", id="in_tags")

        with Horizontal(id="buttons"):
            yield Button("Launch", id="btn_launch", variant="primary")
            yield Button("Launch & watch", id="btn_launch_watch", variant="success")
            yield Button("Dry run", id="btn_dry", variant="default")
            yield Button("Save as TOML", id="btn_save", variant="default")

        yield Static("", id="status_line")
        yield Static("── recent " + "─" * 60, id="recent_header")
        with Vertical(id="recent_wrap"):
            yield RecentRunsList(id="recent")

    # ------------------------------------------------------------------- mount
    def on_mount(self) -> None:
        self.action_refresh_runs()

    # ----------------------------------------------------------- form -> spec
    def _default_label(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return f"launch_{stamp}"

    def _read_int(self, widget_id: str, default: int) -> int:
        try:
            return int(self.query_one(f"#{widget_id}", Input).value.strip() or default)
        except (ValueError, TypeError):
            return default

    def _read_str(self, widget_id: str, default: str = "") -> str:
        return self.query_one(f"#{widget_id}", Input).value.strip() or default

    def _read_select(self, widget_id: str, default: str) -> str:
        sel = self.query_one(f"#{widget_id}", Select)
        v = sel.value
        if v is None or v is Select.BLANK:
            return default
        return str(v)

    def _build_spec(self) -> LaunchSpec | None:
        label = self._read_str("in_label").strip()
        if not label:
            self._set_status("Label is required.", style="red")
            return None
        model = self._read_select("in_model", _MODEL_CHOICES[0])
        harness_name = self._read_select("in_harness", "default")
        tier = self._read_select("in_tier", _TIER_CHOICES[0])
        max_turns = self._read_int("in_max_turns", 200)
        n_ex = self._read_int("in_n", 1)
        r_ex = self._read_int("in_r", 1)
        tags_raw = self._read_str("in_tags")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        return LaunchSpec(
            label=label,
            model=model,
            harness=harness_name,
            env_args={"tier": tier, "max_turns": max_turns},
            num_examples=n_ex,
            rollouts_per_example=r_ex,
            tags=tags,
        )

    def _set_status(self, msg: str, *, style: str = "cyan") -> None:
        line = self.query_one("#status_line", Static)
        line.update(Text(msg, style=style))

    # ----------------------------------------------------------- button hooks
    @on(Button.Pressed, "#btn_launch")
    def _on_launch(self) -> None:
        self.action_launch(False)

    @on(Button.Pressed, "#btn_launch_watch")
    def _on_launch_watch(self) -> None:
        self.action_launch(True)

    @on(Button.Pressed, "#btn_dry")
    def _on_dry(self) -> None:
        self.action_dry_run()

    @on(Button.Pressed, "#btn_save")
    def _on_save(self) -> None:
        self.action_save_toml()

    # ----------------------------------------------------------- key actions
    def action_launch(self, watch: bool = False) -> None:
        spec = self._build_spec()
        if spec is None:
            return
        if self._launch_task is not None and not self._launch_task.done():
            self._set_status("A launch is already in flight.", style="yellow")
            return
        self._set_status(f"Launching {spec.label} …")
        self._launch_task = asyncio.create_task(self._do_launch(spec, watch))

    def action_dry_run(self) -> None:
        spec = self._build_spec()
        if spec is None:
            return
        try:
            argv = launcher.build_command(spec)
        except ValueError as exc:
            self._set_status(f"Dry run error: {exc}", style="red")
            return
        rendered = " ".join(argv)
        self._set_status(f"DRY: {rendered}")
        log.info("dry-run argv: %s", argv)

    def action_save_toml(self) -> None:
        spec = self._build_spec()
        if spec is None:
            return
        asyncio.create_task(self._do_save_toml(spec))

    def action_refresh_runs(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._do_refresh())

    # ---------------------------------------------------------- async workers
    async def _do_refresh(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            # runs.list_runs walks the filesystem; do it off the UI thread.
            summaries = await loop.run_in_executor(
                None, lambda: runs.list_runs(self._repo, kind="eval", limit=20)
            )
        except FileNotFoundError:
            summaries = []
        except Exception as exc:  # noqa: BLE001
            log.warning("list_runs failed: %s", exc)
            summaries = []
        try:
            rail = self.query_one("#recent", RecentRunsList)
        except Exception:  # noqa: BLE001 - screen torn down
            return
        rail.populate(summaries)

    async def _do_launch(self, spec: LaunchSpec, watch: bool) -> None:
        try:
            task_id = await launcher.launch_eval(spec, self._repo)
        except FileNotFoundError as exc:
            self._set_status(f"Cannot launch: {exc}", style="red")
            return
        except RuntimeError as exc:
            self._set_status(str(exc), style="yellow")
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("launch_eval failed")
            self._set_status(f"Launch failed: {exc}", style="red")
            return
        self._set_status(f"Launched task {task_id}", style="green")
        if watch:
            # Hand off to the Traces screen; it owns live attach.
            self.app.action_switch("traces")  # type: ignore[attr-defined]
        # Refresh the recent list once the run lands on disk.
        self.action_refresh_runs()

    async def _do_save_toml(self, spec: LaunchSpec) -> None:
        out_dir = self._repo / "tools" / "launchpad" / "specs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{spec.label}.toml"
        payload: dict[str, Any] = spec.model_dump()
        # tomli_w can't take None; LaunchSpec doesn't currently produce any but
        # be defensive about future fields.
        for k, v in list(payload.items()):
            if v is None:
                payload.pop(k)
        # env_args -> nested table is fine; tags list of str also fine.
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: out_path.write_bytes(tomli_w.dumps(payload).encode())
            )
        except OSError as exc:
            self._set_status(f"Save failed: {exc}", style="red")
            return
        self._set_status(f"Saved {out_path}", style="green")

    # --------------------------------------------------------- list selection
    @on(ListView.Selected)
    def _on_run_selected(self, event: ListView.Selected) -> None:
        # Reserved for v1.1: jumping into the Traces screen for the selected run.
        # For now, just log so we don't appear inert.
        item: ListItem = event.item
        log.info("recent run selected: %s", getattr(item, "id", item))
