"""Screen 2: TRAIN — RL or GEPA launch + live training metrics.

UI (see SPEC.md "Screen mockups"):

    ┌─ 2.TRAIN ─────────────────── mode: [RL] ──┐
    │ [ RL (prime rl) ] [ GEPA (prime gepa) ]   │
    │  <per-mode form for TrainSpec>            │
    │  [ Launch training ]                      │
    │  ─── live: <label> (step N/M) ─────────── │
    │     loss ▁▂▃ 0.42   kl ▁▁▂ 0.038          │
    │     eval-R ▁▃▅ 0.71                       │
    │     <tail of stdout>                      │
    │  [ Promote step <N> ]  [ Stop ]           │
    └───────────────────────────────────────────┘

Keybindings (per SPEC footer):
    r  → switch to RL mode
    g  → switch to GEPA mode
    enter → launch (when on the launch button or via shortcut `L`)
    L  → launch training
    p  → promote latest known step
    s  → stop running task
    1/2/3/4 are claimed by the parent App for screen switching.

All I/O (subprocess spawning, metric streaming, event streaming) is dispatched
via `asyncio.create_task`; nothing blocking happens on the UI thread.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static

from tools.launchpad.core import trainer as trainer_core
from tools.launchpad.tui.widgets.log_tail import LogTail
from tools.launchpad.tui.widgets.metric_chart import MetricChart
from tools.launchpad.types import (
    RLEvalSpec,
    RLHparams,
    TaskEvent,
    TrainMetric,
    TrainSpec,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_float(s: str, default: float) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _parse_int(s: str, default: int) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def _split_csv(s: str) -> list[str]:
    return [tok.strip() for tok in (s or "").split(",") if tok.strip()]


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------


class TrainScreen(Screen):
    """Screen 2: TRAIN — RL/GEPA mode toggle, TrainSpec form, live metrics."""

    BINDINGS = [
        Binding("r", "set_mode('rl')", "RL mode"),
        Binding("g", "set_mode('gepa')", "GEPA mode"),
        Binding("L", "launch", "Launch"),
        Binding("p", "promote", "Promote ckpt"),
        Binding("s", "stop", "Stop"),
    ]

    DEFAULT_CSS = """
    TrainScreen {
        layout: vertical;
    }
    #mode-bar {
        height: 3;
        padding: 0 1;
    }
    #mode-bar Button {
        margin: 0 1;
    }
    #form {
        height: auto;
        padding: 0 1;
    }
    #form Label {
        width: 18;
        content-align: left middle;
    }
    #form Input {
        width: 1fr;
    }
    .row {
        height: 3;
    }
    #launch-row {
        height: 3;
        padding: 0 1;
    }
    #live-header {
        padding: 1 1 0 1;
        text-style: bold;
    }
    #chart {
        height: auto;
        max-height: 8;
    }
    #log-tail {
        height: 1fr;
        min-height: 6;
    }
    #status-row {
        height: 3;
        padding: 0 1;
    }
    .pill {
        padding: 0 1;
        background: $panel;
    }
    .pill-active {
        background: $accent;
        color: $text;
    }
    """

    # Reactive: which mode the form/launch button targets.
    mode: reactive[str] = reactive("rl")

    # Reactive: active task id, latest known step, run state.
    task_id: reactive[str | None] = reactive(None)
    latest_step: reactive[int] = reactive(0)
    is_running: reactive[bool] = reactive(False)

    def __init__(self, repo_root: Path | None = None) -> None:
        super().__init__()
        # Repo root: walk up until we find pyproject.toml, fallback to cwd.
        self._repo_root: Path = repo_root or self._guess_repo_root()
        self._stream_tasks: list[asyncio.Task[None]] = []

    # ----------------------------------------------------------------- setup
    @staticmethod
    def _guess_repo_root() -> Path:
        here = Path(__file__).resolve()
        for parent in (here, *here.parents):
            if (parent / "pyproject.toml").is_file():
                return parent
        return Path.cwd()

    def compose(self) -> ComposeResult:
        # Mode toggle
        with Horizontal(id="mode-bar"):
            yield Button("RL (prime rl)", id="mode-rl", classes="pill pill-active")
            yield Button("GEPA (prime gepa)", id="mode-gepa", classes="pill")
            yield Static("", id="mode-spacer")

        # Form (rendered scrollable so it never overflows the screen)
        with VerticalScroll(id="form"):
            # Common fields
            with Horizontal(classes="row"):
                yield Label("Label")
                yield Input(value="qwen2.5-7b_descend_v3", id="f-label")
            with Horizontal(classes="row"):
                yield Label("Harness")
                yield Input(value="descend_aggressive", id="f-harness")

            # RL fields
            with Vertical(id="form-rl"):
                with Horizontal(classes="row"):
                    yield Label("Base model")
                    yield Input(value="Qwen/Qwen2.5-7B", id="f-base")
                with Horizontal(classes="row"):
                    yield Label("Tiers (csv)")
                    yield Input(
                        value="corridor_explore,descend_to_dlvl_3", id="f-tiers"
                    )
                with Horizontal(classes="row"):
                    yield Label("lr")
                    yield Input(value="1e-6", id="f-lr")
                with Horizontal(classes="row"):
                    yield Label("kl_coef")
                    yield Input(value="0.04", id="f-kl")
                with Horizontal(classes="row"):
                    yield Label("group_size")
                    yield Input(value="8", id="f-group")
                with Horizontal(classes="row"):
                    yield Label("rollouts/ex")
                    yield Input(value="4", id="f-rollouts")
                with Horizontal(classes="row"):
                    yield Label("max_turns")
                    yield Input(value="200", id="f-maxturns")
                with Horizontal(classes="row"):
                    yield Label("batch_size")
                    yield Input(value="64", id="f-batch")
                with Horizontal(classes="row"):
                    yield Label("eval every")
                    yield Input(value="200", id="f-evalevery")
                with Horizontal(classes="row"):
                    yield Label("eval n_examples")
                    yield Input(value="16", id="f-evaln")

            # GEPA fields (hidden in RL mode)
            with Vertical(id="form-gepa"):
                with Horizontal(classes="row"):
                    yield Label("Target")
                    yield Input(value="system_prompt", id="f-target")
                with Horizontal(classes="row"):
                    yield Label("Reward")
                    yield Input(value="descent", id="f-reward")
                with Horizontal(classes="row"):
                    yield Label("Population")
                    yield Input(value="8", id="f-pop")
                with Horizontal(classes="row"):
                    yield Label("Generations")
                    yield Input(value="6", id="f-gens")
                with Horizontal(classes="row"):
                    yield Label("Proposer model")
                    yield Input(value="claude-opus-4-7", id="f-proposer")

        # Launch row
        with Horizontal(id="launch-row"):
            yield Button("Launch training", id="btn-launch", variant="primary")
            yield Button("Stop", id="btn-stop", variant="error", disabled=True)

        # Live metrics
        yield Static("No active run — fill the form and press Launch.", id="live-header")
        yield MetricChart(
            series=("loss", "kl", "eval/reward", "eval/scout", "eval/descent"),
            width=48,
            id="chart",
        )
        yield LogTail(
            empty_message="(no stdout yet — launch a run to start streaming)",
            id="log-tail",
        )

        # Promote / status row
        with Horizontal(id="status-row"):
            yield Button(
                "Promote checkpoint", id="btn-promote", disabled=True
            )
            yield Static("", id="status-label")

    def on_mount(self) -> None:
        # Make sure the GEPA panel starts hidden when mode=='rl'.
        self._refresh_mode_panels()

    # ----------------------------------------------------------------- mode
    def watch_mode(self, _old: str, _new: str) -> None:
        self._refresh_mode_panels()

    def _refresh_mode_panels(self) -> None:
        try:
            rl_panel = self.query_one("#form-rl")
            gepa_panel = self.query_one("#form-gepa")
            rl_btn = self.query_one("#mode-rl", Button)
            gepa_btn = self.query_one("#mode-gepa", Button)
        except Exception:  # pragma: no cover — pre-mount calls
            return
        rl_panel.display = self.mode == "rl"
        gepa_panel.display = self.mode == "gepa"
        # Reflect active pill style via class swap (no inline color hacks).
        if self.mode == "rl":
            rl_btn.add_class("pill-active")
            gepa_btn.remove_class("pill-active")
        else:
            gepa_btn.add_class("pill-active")
            rl_btn.remove_class("pill-active")
        # Update sub-title hint.
        try:
            header = self.query_one("#live-header", Static)
            if not self.is_running:
                header.update(
                    f"mode: [{self.mode.upper()}] — fill the form and press Launch."
                )
        except Exception:
            pass

    def action_set_mode(self, mode: str) -> None:
        if mode not in ("rl", "gepa"):
            return
        self.mode = mode

    # ----------------------------------------------------------------- buttons
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "mode-rl":
            self.mode = "rl"
        elif bid == "mode-gepa":
            self.mode = "gepa"
        elif bid == "btn-launch":
            self.action_launch()
        elif bid == "btn-stop":
            self.action_stop()
        elif bid == "btn-promote":
            self.action_promote()

    # ----------------------------------------------------------------- spec
    def _build_spec(self) -> TrainSpec:
        """Read form fields into a TrainSpec for the current mode."""
        label = self.query_one("#f-label", Input).value.strip() or "untitled"
        harness = self.query_one("#f-harness", Input).value.strip() or "default"
        if self.mode == "rl":
            hp = RLHparams(
                lr=_parse_float(self.query_one("#f-lr", Input).value, 1e-6),
                kl_coef=_parse_float(self.query_one("#f-kl", Input).value, 0.04),
                group_size=_parse_int(self.query_one("#f-group", Input).value, 8),
                rollouts_per_example=_parse_int(
                    self.query_one("#f-rollouts", Input).value, 4
                ),
                max_turns=_parse_int(
                    self.query_one("#f-maxturns", Input).value, 200
                ),
                batch_size=_parse_int(self.query_one("#f-batch", Input).value, 64),
            )
            eval_spec = RLEvalSpec(
                every_steps=_parse_int(
                    self.query_one("#f-evalevery", Input).value, 200
                ),
                n_examples=_parse_int(
                    self.query_one("#f-evaln", Input).value, 16
                ),
                tiers=_split_csv(self.query_one("#f-tiers", Input).value),
            )
            return TrainSpec(
                mode="rl",
                label=label,
                harness=harness,
                base_model=self.query_one("#f-base", Input).value.strip()
                or "Qwen/Qwen2.5-7B",
                tiers=_split_csv(self.query_one("#f-tiers", Input).value),
                hparams=hp,
                eval=eval_spec,
            )
        # GEPA
        target_raw = self.query_one("#f-target", Input).value.strip() or "system_prompt"
        if target_raw not in ("system_prompt", "per_step_prompt", "both"):
            target_raw = "system_prompt"
        return TrainSpec(
            mode="gepa",
            label=label,
            harness=harness,
            target=target_raw,  # type: ignore[arg-type]
            reward=self.query_one("#f-reward", Input).value.strip() or "descent",
            population=_parse_int(self.query_one("#f-pop", Input).value, 8),
            generations=_parse_int(self.query_one("#f-gens", Input).value, 6),
            proposer_model=self.query_one("#f-proposer", Input).value.strip()
            or "claude-opus-4-7",
        )

    # ----------------------------------------------------------------- launch
    def action_launch(self) -> None:
        if self.is_running:
            self._set_status("A task is already running — Stop it first.", error=True)
            return
        try:
            spec = self._build_spec()
        except Exception as exc:  # pydantic ValidationError, ValueError, ...
            log.exception("build_spec failed")
            self._set_status(f"Invalid spec: {exc}", error=True)
            return
        # Reset live widgets.
        self.query_one("#chart", MetricChart).reset()
        self.query_one("#log-tail", LogTail).clear()
        self.latest_step = 0
        self._set_status(f"Launching {spec.mode.upper()} run: {spec.label}…")
        # Spawn the launcher and the two stream pumps.
        asyncio.create_task(self._do_launch(spec))

    async def _do_launch(self, spec: TrainSpec) -> None:
        try:
            if spec.mode == "rl":
                tid = await trainer_core.launch_rl(spec, self._repo_root)
            else:
                tid = await trainer_core.launch_gepa(spec, self._repo_root)
        except FileNotFoundError as exc:
            self._set_status(f"Cannot launch: {exc}", error=True)
            return
        except (ValueError, OSError) as exc:
            log.exception("launch failed")
            self._set_status(f"Launch failed: {exc}", error=True)
            return

        self.task_id = tid
        self.is_running = True
        self._set_status(f"Running task {tid} (mode={spec.mode}).")
        try:
            self.query_one("#btn-launch", Button).disabled = True
            self.query_one("#btn-stop", Button).disabled = False
            self.query_one("#btn-promote", Button).disabled = False
            self.query_one("#live-header", Static).update(
                f"live: {spec.label} ({tid}) — step 0"
            )
        except Exception:
            pass

        # Fan out: one task per stream. They terminate when the process exits.
        self._stream_tasks.append(
            asyncio.create_task(self._pump_metrics(tid))
        )
        self._stream_tasks.append(
            asyncio.create_task(self._pump_events(tid))
        )

    async def _pump_metrics(self, tid: str) -> None:
        try:
            chart = self.query_one("#chart", MetricChart)
        except Exception:
            return
        try:
            async for metric in trainer_core.stream_metrics(tid):
                chart.push(metric)
                if metric.step > self.latest_step:
                    self.latest_step = metric.step
                    self._refresh_live_header(tid)
        except (KeyError, asyncio.CancelledError):
            return
        except Exception:  # pragma: no cover — defensive
            log.exception("metric pump crashed for %s", tid)

    async def _pump_events(self, tid: str) -> None:
        try:
            tail = self.query_one("#log-tail", LogTail)
        except Exception:
            return
        try:
            async for event in trainer_core.stream_events(tid):
                self._handle_event(tail, event)
        except (KeyError, asyncio.CancelledError):
            return
        except Exception:  # pragma: no cover
            log.exception("event pump crashed for %s", tid)
        finally:
            self.is_running = False
            try:
                self.query_one("#btn-launch", Button).disabled = False
                self.query_one("#btn-stop", Button).disabled = True
            except Exception:
                pass

    def _handle_event(self, tail: LogTail, event: TaskEvent) -> None:
        if event.kind in ("stdout", "stderr"):
            line = str(event.payload.get("line", ""))
            tail.append(line, kind=event.kind)
        elif event.kind == "finished":
            exit_code = event.payload.get("exit_code", "?")
            tail.append(f"[finished] exit_code={exit_code}", kind="info")
            self._set_status(f"Task finished (exit_code={exit_code}).")

    # ----------------------------------------------------------------- live header
    def watch_latest_step(self, _old: int, _new: int) -> None:
        if self.task_id is not None:
            self._refresh_live_header(self.task_id)

    def _refresh_live_header(self, tid: str) -> None:
        try:
            header = self.query_one("#live-header", Static)
            label = self.query_one("#f-label", Input).value.strip() or tid
            header.update(f"live: {label} ({tid}) — step {self.latest_step}")
        except Exception:
            pass

    # ----------------------------------------------------------------- stop / promote
    def action_stop(self) -> None:
        if self.task_id is None:
            self._set_status("No active task to stop.", error=True)
            return
        ok = trainer_core.stop_task(self.task_id)
        if ok:
            self._set_status(f"Sent SIGTERM to {self.task_id} (5s grace).")
        else:
            self._set_status(
                f"Could not stop {self.task_id} (already exited?)", error=True
            )

    def action_promote(self) -> None:
        """Promote the latest known step as a checkpoint reference.

        v1: posts a `PromoteCheckpoint` message-style status update. The
        downstream "Launch" tab listens for promotion events; until that wiring
        lands we just surface it in the status bar and the log tail. Persisting
        the promote is a CLI concern (`launchpad eval --resume-from <ckpt>`).
        """
        if self.task_id is None:
            self._set_status("No active task to promote.", error=True)
            return
        step = self.latest_step
        if step <= 0:
            self._set_status(
                "No step seen yet — wait for the first metric, then promote.",
                error=True,
            )
            return
        label = self.query_one("#f-label", Input).value.strip() or self.task_id
        msg = f"Promoted checkpoint: {label} @ step {step} (task={self.task_id})"
        self._set_status(msg)
        try:
            self.query_one("#log-tail", LogTail).append(msg, kind="info")
        except Exception:
            pass

    # ----------------------------------------------------------------- status helper
    def _set_status(self, text: str, *, error: bool = False) -> None:
        try:
            widget = self.query_one("#status-label", Static)
        except Exception:
            return
        widget.update(text)
        widget.styles.color = "red" if error else "white"

    # ----------------------------------------------------------------- cleanup
    async def on_unmount(self) -> None:
        for task in self._stream_tasks:
            task.cancel()
        self._stream_tasks.clear()
