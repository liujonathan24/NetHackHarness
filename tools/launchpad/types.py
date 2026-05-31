"""Pydantic models shared across launchpad core, CLI, and TUI.

All models are immutable-by-convention (callers should construct fresh instances
rather than mutating). JSON serialization via `.model_dump()` / `.model_dump_json()`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Launch / train specs
# ---------------------------------------------------------------------------


class LaunchSpec(BaseModel):
    """Spec for a single eval launch (local or hosted via prime eval)."""

    label: str
    model: str
    harness: str = "default"
    env_args: dict[str, Any] = Field(default_factory=dict)
    num_examples: int = 1
    rollouts_per_example: int = 1
    tags: list[str] = Field(default_factory=list)
    local: bool = False  # True -> vf-eval; False -> prime eval (hosted unless prime_hosted=False)
    prime_hosted: bool = True
    max_concurrent: int = 1
    extra_args: list[str] = Field(default_factory=list)


class RLHparams(BaseModel):
    lr: float = 1e-6
    kl_coef: float = 0.04
    group_size: int = 8
    rollouts_per_example: int = 4
    max_turns: int = 200
    batch_size: int = 64


class RLFiltering(BaseModel):
    min_difficulty: float = 0.0
    max_difficulty: float = 1.0
    oversample_hard: bool = False


class RLEvalSpec(BaseModel):
    every_steps: int = 200
    tiers: list[str] = Field(default_factory=list)
    n_examples: int = 16


class TrainSpec(BaseModel):
    """Spec for a training run — either RL (`prime rl`/`prime train`) or GEPA."""

    mode: Literal["rl", "gepa"]
    label: str
    harness: str = "default"

    # RL fields
    base_model: str | None = None
    tiers: list[str] = Field(default_factory=list)
    hparams: RLHparams | None = None
    filtering: RLFiltering | None = None
    eval: RLEvalSpec | None = None

    # GEPA fields
    target: Literal["system_prompt", "per_step_prompt", "both"] | None = None
    reward: str | None = None
    population: int | None = None
    generations: int | None = None
    proposer_model: str | None = None


# ---------------------------------------------------------------------------
# Run summaries (parsed from experiments/results/*)
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    """One eval or train run, as enumerated by `core.runs.list_runs`."""

    run_id: str
    kind: Literal["eval", "train"]
    label: str
    model: str | None = None
    harness: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: Literal["running", "done", "failed", "unknown"] = "unknown"
    started_at: float | None = None  # unix seconds
    finished_at: float | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    trace_dir: str | None = None
    n_rollouts: int = 0
    source_path: str | None = None  # results JSON / dir on disk


# ---------------------------------------------------------------------------
# Harness config (the TOML schema for tools/launchpad/harnesses/*.toml)
# ---------------------------------------------------------------------------


class SystemPromptOverlay(BaseModel):
    mode: Literal["replace", "append", "patch"] = "replace"
    text: str = ""


class PerStepPromptOverlay(BaseModel):
    template: str = "B1_minimal"
    include_inventory: bool = True
    include_messages_n: int = 3
    include_adjacent: bool = True
    include_visible: bool = True
    map_window: tuple[int, int] = (21, 13)
    ascii_legend: bool = False


class ToolsOverlay(BaseModel):
    enabled: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)
    overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # ^ keyed by tool name, e.g. {"move": {"description_override": "..."}}


class HarnessConfig(BaseModel):
    """In-memory representation of one harness TOML."""

    name: str
    extends: str | None = "default"
    system_prompt: SystemPromptOverlay = Field(default_factory=SystemPromptOverlay)
    per_step_prompt: PerStepPromptOverlay = Field(default_factory=PerStepPromptOverlay)
    tools: ToolsOverlay = Field(default_factory=ToolsOverlay)
    rewards: dict[str, float] = Field(default_factory=dict)  # weight overrides
    source_path: str | None = None


# ---------------------------------------------------------------------------
# Trace turn (matches the NDJSON schema written by environments/nethack/nethack.py)
# ---------------------------------------------------------------------------


class ToolCallRecord(BaseModel):
    name: str | None
    arguments: str | None  # JSON-encoded string, as the env writes it


class TraceTurn(BaseModel):
    """One NDJSON line from `<trace_dir>/<run_id>.ndjson`."""

    turn: int = 0
    t_wall: float = 0.0
    variant: str = ""
    raw_grid: list[str] = Field(default_factory=list)
    status: dict[str, Any] = Field(default_factory=dict)
    dlvl: int | None = None
    hp: int | None = None
    max_hp: int | None = None
    max_dlvl_reached: int | None = None
    continual_life: int = 1
    rendered_user_message: str = ""
    assistant_message: str = ""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    action_indices: list[int] = Field(default_factory=list)
    reward: float = 0.0
    messages: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Live / async task events
# ---------------------------------------------------------------------------


class TaskEvent(BaseModel):
    """One streamed event from a running subprocess (launcher or trainer)."""

    task_id: str
    kind: Literal["stdout", "stderr", "status", "trace_turn", "metric", "finished"]
    t_wall: float
    payload: dict[str, Any] = Field(default_factory=dict)


class TrainMetric(BaseModel):
    """One training-loop scalar parsed from `prime rl` / `prime gepa` output."""

    task_id: str
    step: int
    t_wall: float
    name: str  # e.g. "loss", "kl", "eval/scout", "eval/descent"
    value: float
