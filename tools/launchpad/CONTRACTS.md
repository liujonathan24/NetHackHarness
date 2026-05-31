# nethack-launchpad — Phase-3 Implementer Contracts

Phase-3 implementers wire one module at a time. **Read only this file plus the
module you own.** Every public function below is defined as a stub (raising
`NotImplementedError`) with the exact signature you must preserve.

The CLI surface (`cli.py`) and TUI screens (`tui/`) are thin wrappers that call
into `core/*`. If a contract here changes, update this file in the same commit.

---

## 0. Shared types (`tools/launchpad/types.py`)

All cross-module data is pydantic v2. Construct fresh instances rather than
mutating. JSON via `.model_dump()` / `.model_dump_json()`.

```python
class LaunchSpec(BaseModel):
    label: str
    model: str
    harness: str = "default"
    env_args: dict[str, Any] = {}
    num_examples: int = 1
    rollouts_per_example: int = 1
    tags: list[str] = []
    local: bool = False                # True -> vf-eval; False -> prime eval
    prime_hosted: bool = True          # only consulted when local=False
    max_concurrent: int = 1
    extra_args: list[str] = []

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
    tiers: list[str] = []
    n_examples: int = 16

class TrainSpec(BaseModel):
    mode: Literal["rl", "gepa"]
    label: str
    harness: str = "default"
    # RL fields:
    base_model: str | None = None
    tiers: list[str] = []
    hparams: RLHparams | None = None
    filtering: RLFiltering | None = None
    eval: RLEvalSpec | None = None
    # GEPA fields:
    target: Literal["system_prompt", "per_step_prompt", "both"] | None = None
    reward: str | None = None
    population: int | None = None
    generations: int | None = None
    proposer_model: str | None = None

class RunSummary(BaseModel):
    run_id: str
    kind: Literal["eval", "train"]
    label: str
    model: str | None = None
    harness: str | None = None
    tags: list[str] = []
    status: Literal["running", "done", "failed", "unknown"] = "unknown"
    started_at: float | None = None      # unix seconds
    finished_at: float | None = None
    metrics: dict[str, float] = {}
    trace_dir: str | None = None
    n_rollouts: int = 0
    source_path: str | None = None

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
    enabled: list[str] = []
    disabled: list[str] = []
    overrides: dict[str, dict[str, Any]] = {}   # keyed by tool name

class HarnessConfig(BaseModel):
    name: str
    extends: str | None = "default"
    system_prompt: SystemPromptOverlay = ...
    per_step_prompt: PerStepPromptOverlay = ...
    tools: ToolsOverlay = ...
    rewards: dict[str, float] = {}             # weight overrides
    source_path: str | None = None

class ToolCallRecord(BaseModel):
    name: str | None
    arguments: str | None                      # JSON-encoded string

class TraceTurn(BaseModel):
    # Mirrors the 16-field NDJSON schema written by _write_trace_entry in
    # environments/nethack/nethack.py (lines 1964-1981).
    turn: int = 0
    t_wall: float = 0.0
    variant: str = ""
    raw_grid: list[str] = []
    status: dict[str, Any] = {}
    dlvl: int | None = None
    hp: int | None = None
    max_hp: int | None = None
    max_dlvl_reached: int | None = None
    continual_life: int = 1
    rendered_user_message: str = ""
    assistant_message: str = ""
    tool_calls: list[ToolCallRecord] = []
    action_indices: list[int] = []
    reward: float = 0.0
    messages: list[str] = []

class TaskEvent(BaseModel):
    task_id: str
    kind: Literal["stdout", "stderr", "status", "trace_turn", "metric", "finished"]
    t_wall: float
    payload: dict[str, Any] = {}

class TrainMetric(BaseModel):
    task_id: str
    step: int
    t_wall: float
    name: str            # e.g. "loss", "kl", "eval/scout", "eval/descent"
    value: float
```

**Stability:** never rename or remove a field. Add optional fields with
sensible defaults instead.

---

## 1. `core.runs` — discovery & summarization

Read-only. Walks `experiments/results/**` for eval JSON artifacts and
`runs/**` for train artifacts.

```python
def list_runs(root: Path, kind: str | None = None,
              tag: str | None = None, limit: int = 20) -> list[RunSummary]
def get_run(root: Path, run_id: str) -> RunSummary
def compare_runs(root: Path, run_a: str, run_b: str,
                 metric: str = "scout") -> dict[str, float]
def latest_run(root: Path, kind: str | None = None) -> RunSummary
def iter_trace_files(summary: RunSummary) -> Iterable[Path]
```

**Errors:**
- `list_runs` raises `FileNotFoundError` if `root/experiments` is missing.
- `get_run` raises `KeyError` if the id is unknown.
- `compare_runs` raises `KeyError` (unknown id) or `ValueError` (metric absent).
- `latest_run` raises `LookupError` if no runs match.
- `iter_trace_files` yields nothing (no raise) when `trace_dir` is None/missing.

**Return shape:** `compare_runs` returns `{"a": float, "b": float, "delta": b-a}`.

**Ordering:** `list_runs` is newest-first by `started_at` (None sorts last).

---

## 2. `core.traces` — NDJSON reader

Owns the read side of the trace format documented in
`environments/nethack/nethack.py` `_write_trace_entry` (lines 1907-1986).
Filename pattern: `<trace_dir>/<run_id>.ndjson`, one JSON object per line.

```python
def read_trace(path: Path) -> list[TraceTurn]
def stream_trace(path: Path) -> Iterator[TraceTurn]
def get_turn(path: Path, turn_index: int) -> TraceTurn
def trace_summary(path: Path) -> dict[str, float | int]
def clear_cache() -> None
```

**Errors:**
- All readers raise `FileNotFoundError` for a missing path.
- `get_turn` raises `IndexError` for out-of-range `turn_index` (0-indexed by
  file order, NOT by `TraceTurn.turn`).
- Malformed JSON lines are SKIPPED with `warnings.warn` (never raise) —
  the trace writer wraps itself in a bare `except`, so corruption is rare
  but possible at process kill.

**Return shape:** `trace_summary` returns
`{"n_turns": int, "total_reward": float, "max_dlvl": int, "final_hp": int}`,
all zero if the file is empty.

**Caching:** `read_trace` MAY cache by `(path, mtime, size)`. `clear_cache()`
must be idempotent.

---

## 3. `core.harness` — TOML CRUD + preview

```python
def harnesses_dir() -> Path
def list_harnesses() -> list[HarnessConfig]
def load_harness(name: str) -> HarnessConfig
def save_harness(cfg: HarnessConfig) -> Path
def create_harness(name: str, extends: str = "default") -> HarnessConfig
def edit_harness(name: str) -> int
def diff_harness(name: str, against: str = "default") -> str
def validate_harness(name: str) -> list[str]
def preview_harness(name: str, state: dict | None = None) -> str
```

**Directory contract:**
`harnesses_dir()` returns `tools/launchpad/harnesses/` (relative to this
package), creating it if absent. Files are `<name>.toml`.

**`extends` resolution:**
`load_harness(name)` resolves `extends` recursively (cycle -> `ValueError`).
Child overlays merge per-section over the parent (`replace` > `append` >
`patch` for system_prompt; list-union with `disabled` masking for tools;
dict-update for rewards & per_step_prompt fields).

**Errors:**
- `load_harness`: `FileNotFoundError` (missing file) | `ValueError` (parse /
  validation / cycle).
- `save_harness`: `ValueError` if `cfg.name` contains `/` or `\`.
- `create_harness`: `FileExistsError` (name taken) | `FileNotFoundError`
  (extends target missing).
- `edit_harness`: `FileNotFoundError` if missing. Returns editor exit code.
  Uses `$EDITOR`, falling back to `nano`.
- `diff_harness`: never raises; missing files produce an empty side of the diff.
- `validate_harness`: `ValueError` on parse/schema failure; returns
  human-readable warnings (e.g. unknown tool names) for non-fatal issues.

**`preview_harness`:**
Returns a string identical in shape to a `TraceTurn.rendered_user_message`.
If `state` is None, use a synthetic Dlvl-1 sample so the call is deterministic.
Implementation MUST go through the same overlay path the runtime will use
(i.e. set `NETHACK_HARNESS=<name>` and call into the env's formatter), not
duplicate prompt rendering here.

---

## 4. `core.launcher` — eval subprocess management

Builds `prime eval run` argv per the convention in
`experiments/exp16_obs_variants.py` (see PRIME CLI discovery).

```python
def build_command(spec: LaunchSpec, output_dir: Path | None = None) -> list[str]

async def launch_eval(spec: LaunchSpec, repo_root: Path,
                      output_dir: Path | None = None) -> str
async def stream_events(task_id: str) -> AsyncIterator[TaskEvent]
def stop_task(task_id: str) -> bool
def list_tasks() -> list[str]
async def wait_for(task_id: str, timeout_s: float | None = None) -> int
```

**Command shape:**

- `spec.local=False, spec.prime_hosted=True` (default):
  ```
  prime eval run nethack --model <m> --env-args <compact-json>
    -n <N> -r <R> --max-concurrent <C>
    --hosted --eval-name <slugified-label>
  ```
  Slug rule: replace `/` with `-` (per exp16 convention).
  MUST NOT include `--save-results / --output-dir / --abbreviated-summary`
  (hosted rejects them).

- `spec.local=False, spec.prime_hosted=False`:
  ```
  prime eval run nethack --model <m> --env-args <compact-json>
    -n <N> -r <R> --max-concurrent <C>
    --save-results --output-dir <output_dir> --abbreviated-summary
  ```
  `output_dir` is REQUIRED here — `build_command` raises `ValueError` if
  `output_dir is None and not spec.prime_hosted`.

- `spec.local=True`: `vf-eval nethack ...` (exact shape TBD by implementer
  matching local `vf-eval` CLI).

**`env_args` JSON:**
`json.dumps(spec.env_args, separators=(",", ":"))`. Inject `explicit_seeds`
only if caller put them in `env_args`; do not synthesize seeds here.

**Child env:**
`launch_eval` sets `NETHACK_HARNESS=<spec.harness>` in the child env. All
other inherited env vars pass through unchanged.

**Process tracking:**
`task_id` is `f"{spec.label}_{int(time.time())}"`. Two concurrent launches
with the same `label` raise `RuntimeError`. `list_tasks()` returns live ids.
`stop_task` sends SIGTERM, then SIGKILL after 5s grace; returns True on kill.

**`stream_events`:**
Yields `TaskEvent` with `kind ∈ {stdout, stderr, status, finished}` (parsing
of `trace_turn` events is the responsibility of `core.live`). The async
iterator closes when the process exits and emits a final `kind="finished"`
event with `payload={"exit_code": int}`.

**Errors:**
- `launch_eval`: `FileNotFoundError` (prime/vf-eval not on PATH),
  `RuntimeError` (duplicate label).
- `stream_events`, `wait_for`: `KeyError` for unknown `task_id`.
- `wait_for`: `asyncio.TimeoutError` if `timeout_s` elapses.

---

## 5. `core.trainer` — RL / GEPA subprocess management

```python
def materialize_rl_toml(spec: TrainSpec, dest: Path) -> Path
async def launch_rl(spec: TrainSpec, repo_root: Path) -> str
async def launch_gepa(spec: TrainSpec, repo_root: Path) -> str
async def stream_metrics(task_id: str) -> AsyncIterator[TrainMetric]
async def stream_events(task_id: str) -> AsyncIterator[TaskEvent]
def stop_task(task_id: str) -> bool
```

**`materialize_rl_toml`:**
Translates `TrainSpec` (mode=rl) -> a `prime rl`-compatible TOML at `dest`.
Raises `ValueError` if `spec.mode != "rl"` or required fields
(`base_model`, `hparams`) are missing.

**`launch_rl`:**
Spawns `prime rl <toml>` (which is the deprecated-alias form; equivalent to
`prime train <toml>`). Sets `NETHACK_HARNESS=<spec.harness>`. Returns
`task_id`. Raises `ValueError` if `spec.mode != "rl"`.

**`launch_gepa`:**
Spawns:
```
prime gepa run nethack --env-args <compact-json> --model <proposer_model>
  --reflection-model <proposer_model> --max-calls <generations*population>
  --num-train <n> --num-val <n> --run-dir <runs/gepa/<label>>
```
No `--hosted` (GEPA is local-only). Returns `task_id`. Raises `ValueError`
if `spec.mode != "gepa"`.

**`stream_metrics`:**
Parses the subprocess's stdout for scalar metrics (`loss`, `kl`, `eval/*`,
GEPA reward population stats) and yields `TrainMetric`. Closes when the
process exits.

**`stream_events`:** parallel raw-output stream (same shape as
`core.launcher.stream_events`).

**Errors:** same conventions as `core.launcher` — `FileNotFoundError` on
missing `prime`, `KeyError` on unknown `task_id`.

---

## 6. `core.live` — live attach (local watch + hosted poll)

```python
async def watch_trace_dir(trace_dir: Path) -> AsyncIterator[tuple[Path, TraceTurn]]
async def watch_file(path: Path) -> AsyncIterator[TraceTurn]
async def poll_hosted(eval_id: str, interval_s: float = 2.0) -> AsyncIterator[TaskEvent]
async def tail_task(task_id: str) -> AsyncIterator[str]
```

**`watch_trace_dir`:**
1. Emits every existing `.ndjson` line (oldest -> newest) first.
2. Then uses `watchfiles` to follow the dir; emits `(path, turn)` for each
   new file and for each appended line.
   Cancel the awaiting task to stop. Raises `FileNotFoundError` if
   `trace_dir` doesn't exist at call time.

**`watch_file`:**
Same model, single file. Tolerates partial trailing line (in-flight write):
hold incomplete bytes until `\n` arrives.

**`poll_hosted`:**
Polls `prime eval samples <eval_id> --output json` every `interval_s`.
Yields a `TaskEvent` (`kind="trace_turn"` with payload from the sample, OR
`kind="status"` for progress) per new sample. Raises `FileNotFoundError`
if `prime` not on PATH.

**`tail_task`:**
Yields raw stdout lines for a live task (looks up `task_id` in both
launcher and trainer registries). Raises `KeyError` if unknown to both.

---

## 7. `core.git` — minimal git wrappers

```python
def current_branch(repo_root: Path) -> str   # "" on non-repo / detached -> "HEAD"
def short_sha(repo_root: Path) -> str        # "" on non-repo / no commits
def is_dirty(repo_root: Path) -> bool        # True if porcelain non-empty
def diff_file(repo_root: Path, path: Path) -> str  # `git diff HEAD -- <path>`
```

All run `git` with `cwd=repo_root, text=True`. None raise on non-zero exit;
they return empty / False instead. Used by the TUI footer pill and
`harness diff`.

---

## 8. Cross-cutting conventions

- **`repo_root`** is always an absolute `Path` to the dir containing
  `experiments/`, `environments/`, and this `tools/` tree. Callers pass it
  explicitly; modules MUST NOT call `Path.cwd()` or read `$LAUNCHPAD_REPO`
  themselves (CLI layer resolves that once).
- **Subprocesses** use `asyncio.create_subprocess_exec` (never `shell=True`).
  Always pipe stdout/stderr; consume in background tasks so the pipe never
  blocks.
- **Logging:** modules log via `logging.getLogger(__name__)`. No print().
- **No global state** outside the launcher/trainer task registries and the
  `core.traces` cache.
- **Imports:** core modules must not import from `tui/` (one-way dependency).
