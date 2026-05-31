"""Typer CLI surface — Surface A from SPEC.md.

All subcommand bodies are NotImplementedError stubs. Phase-3 implementers wire
each one to the corresponding `core.*` module per CONTRACTS.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="launchpad",
    help="NetHack Launchpad: evals, training, traces — CLI + TUI.",
    no_args_is_help=False,
)


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


@app.command("eval")
def cmd_eval(
    model: str = typer.Option(..., "--model", help="Model id (e.g. gpt-4.1-mini)."),
    harness: str = typer.Option("default", "--harness", help="Harness name from tools/launchpad/harnesses/."),
    tier: Optional[str] = typer.Option(None, "--tier", help="env_args.tier."),
    n: int = typer.Option(1, "-n", "--num-examples"),
    r: int = typer.Option(1, "-r", "--rollouts-per-example"),
    max_concurrent: int = typer.Option(1, "--max-concurrent"),
    label: Optional[str] = typer.Option(None, "--label"),
    tag: list[str] = typer.Option([], "--tag", help="Repeatable; or pass a comma list."),
    local: bool = typer.Option(False, "--local", help="Use vf-eval instead of prime eval."),
    hosted: bool = typer.Option(True, "--hosted/--no-hosted", help="When using prime eval."),
    watch: bool = typer.Option(False, "--watch", help="Launch, then auto-attach TUI."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Launch one eval. See core.launcher.launch_eval."""
    raise NotImplementedError("cli.cmd_eval — wire to core.launcher.launch_eval")


# ---------------------------------------------------------------------------
# train
# ---------------------------------------------------------------------------


train_app = typer.Typer(help="RL / GEPA training launchers.")
app.add_typer(train_app, name="train")


@train_app.command("rl")
def cmd_train_rl(
    base: str = typer.Option(..., "--base"),
    harness: str = typer.Option("default", "--harness"),
    tier: list[str] = typer.Option([], "--tier"),
    hparams: Optional[Path] = typer.Option(None, "--hparams"),
    label: Optional[str] = typer.Option(None, "--label"),
) -> None:
    """Launch an RL training run via `prime rl`. See core.trainer.launch_rl."""
    raise NotImplementedError("cli.cmd_train_rl — wire to core.trainer.launch_rl")


@train_app.command("gepa")
def cmd_train_gepa(
    harness: str = typer.Option("default", "--harness"),
    target: str = typer.Option("system_prompt", "--target"),
    reward: str = typer.Option("descent", "--reward"),
    generations: int = typer.Option(6, "--generations"),
    population: int = typer.Option(8, "--population"),
    proposer_model: Optional[str] = typer.Option(None, "--proposer-model"),
    label: Optional[str] = typer.Option(None, "--label"),
) -> None:
    """Launch a GEPA run via `prime gepa`. See core.trainer.launch_gepa."""
    raise NotImplementedError("cli.cmd_train_gepa — wire to core.trainer.launch_gepa")


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


runs_app = typer.Typer(help="Inspect past runs.")
app.add_typer(runs_app, name="runs")


@runs_app.command("ls")
def cmd_runs_ls(
    kind: Optional[str] = typer.Option(None, "--kind", help="eval|train"),
    tag: Optional[str] = typer.Option(None, "--tag"),
    limit: int = typer.Option(20, "--limit"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List runs. See core.runs.list_runs."""
    raise NotImplementedError("cli.cmd_runs_ls — wire to core.runs.list_runs")


@runs_app.command("show")
def cmd_runs_show(
    run_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show one run. See core.runs.get_run."""
    raise NotImplementedError("cli.cmd_runs_show — wire to core.runs.get_run")


@runs_app.command("compare")
def cmd_runs_compare(
    run_a: str = typer.Argument(...),
    run_b: str = typer.Argument(...),
    metric: str = typer.Option("scout", "--metric"),
) -> None:
    """Compare two runs. See core.runs.compare_runs."""
    raise NotImplementedError("cli.cmd_runs_compare — wire to core.runs.compare_runs")


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------


@app.command("trace")
def cmd_trace(
    run_id: Optional[str] = typer.Argument(None),
    rollout: Optional[int] = typer.Option(None, "--rollout"),
    turn: Optional[int] = typer.Option(None, "--turn"),
    latest: bool = typer.Option(False, "--latest"),
    live: bool = typer.Option(False, "--live"),
) -> None:
    """Open the TUI Traces screen on a run. See tui.app.LaunchpadApp.open_trace."""
    raise NotImplementedError("cli.cmd_trace — wire to tui.app + core.traces")


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


harness_app = typer.Typer(help="Manage harness TOML overlays.")
app.add_typer(harness_app, name="harness")


@harness_app.command("ls")
def cmd_harness_ls() -> None:
    """List harnesses. See core.harness.list_harnesses."""
    raise NotImplementedError("cli.cmd_harness_ls — wire to core.harness.list_harnesses")


@harness_app.command("new")
def cmd_harness_new(
    name: str = typer.Argument(...),
    extends: str = typer.Option("default", "--extends"),
) -> None:
    """Create a new harness overlay. See core.harness.create_harness."""
    raise NotImplementedError("cli.cmd_harness_new — wire to core.harness.create_harness")


@harness_app.command("edit")
def cmd_harness_edit(name: str = typer.Argument(...)) -> None:
    """Open a harness TOML in $EDITOR. See core.harness.edit_harness."""
    raise NotImplementedError("cli.cmd_harness_edit — wire to core.harness.edit_harness")


@harness_app.command("diff")
def cmd_harness_diff(name: str = typer.Argument(...)) -> None:
    """Diff a harness vs default. See core.harness.diff_harness."""
    raise NotImplementedError("cli.cmd_harness_diff — wire to core.harness.diff_harness")


@harness_app.command("preview")
def cmd_harness_preview(
    name: str = typer.Argument(...),
    state: Optional[Path] = typer.Option(None, "--state"),
) -> None:
    """Render the turn-0 LLM view. See core.harness.preview_harness."""
    raise NotImplementedError("cli.cmd_harness_preview — wire to core.harness.preview_harness")


@harness_app.command("validate")
def cmd_harness_validate(name: str = typer.Argument(...)) -> None:
    """Validate a harness TOML. See core.harness.validate_harness."""
    raise NotImplementedError("cli.cmd_harness_validate — wire to core.harness.validate_harness")


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------


@app.command("export")
def cmd_export(
    run_id: str = typer.Argument(...),
    out: Path = typer.Option(..., "--out"),
) -> None:
    """Export a rollout to mp4 via tools/render_rollout_video.py."""
    raise NotImplementedError("cli.cmd_export — wire to render_rollout_video")


@app.command("stop")
def cmd_stop(task_id: str = typer.Argument(...)) -> None:
    """Stop a running task. See core.launcher.stop_task / core.trainer.stop_task."""
    raise NotImplementedError("cli.cmd_stop — wire to core.launcher.stop_task")


@app.command("tail")
def cmd_tail(task_id: str = typer.Argument(...)) -> None:
    """Stream stdout for a running task. See core.live.tail_task."""
    raise NotImplementedError("cli.cmd_tail — wire to core.live.tail_task")
