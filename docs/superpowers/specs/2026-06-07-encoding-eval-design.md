---
comet_change: encoding-eval
role: technical-design
canonical_spec: openspec
---

# Encoding-eval — technical design

> Canonical requirements: the OpenSpec delta spec under
> `openspec/changes/encoding-eval/specs/encoding-eval/`. This is the *how*.

## Summary

A benchmark harness that runs the same NetHack task across the observation
encodings (ASCII / IMG / IMG_TTY / JSON / TOON, with `map_detail`) and models
(≥1 instruct LLM, ≥1 VLM), and produces a per-encoding comparison reusing the
existing eval instrument. It also makes rollouts **replayable** in both a
human-viewable and the exact LLM-input form (image preserved for the pixel
encodings) — capturing the data now, with the rich viewer deferred to Group B.

## Confirmed parameters (from design brainstorming)

| Decision | Choice |
| --- | --- |
| Orchestration | **Reuse the existing vf-eval/prime runner** per cell (gen config → invoke → load samples). The framework owns the rollout loop. |
| Aggregation | **Pure / mock-testable**: samples → `summarize_eval` + `progression_*`. |
| Replay log | **Extend the per-turn NDJSON trace** with `rendered_user_content` (full multimodal); one source of truth. |
| Image capture | **Separate PNG files** under `outputs/evals/<run>/images/`, referenced by path. |
| Default models | **Qwen3.5 instruct + Qwen3.5-VL**, fully configurable. |
| Table | **JSON (canonical) + markdown (human)** under `outputs/evals/`. |
| Viewer | **Minimal renderer behind a documented seam**; rich viewer = Group B `tools/launchpad`. |

## Components

### 1. Aggregation (pure) — new module under `tools/`

`aggregate(cells: dict[str, list[sample]]) -> table` where each `sample` is the
rollout dict `summarize_eval` already consumes (`reward`, `scout_reward`,
`descent_reward`, `seed`, optional `trace`). Per cell it calls
`tools.eval_instrument.summarize_eval` + `nethack_harness.prompt.balrog`
`progression_score`/`progression_tier`, and derives max-dlvl, steps-to-first-
descent, and tokens/turn from sample/trace metadata. `$/run` is `None`
(rendered "n/a") when usage is absent — never fabricated. Returns a structured
table (encoding × metric). No model calls → unit-tested on synthetic samples.

### 2. Orchestration — new module under `tools/`

For each `(variant, map_detail, model)` cell: render a per-cell
`configs/eval`-style config (env id + the env's `variant`/`map_detail` kwargs +
model), invoke the existing eval runner (vf-eval/prime), and collect samples via
`load_hosted_eval_samples` (hosted) or `attach_local_traces` (local NDJSON). The
runner invocation goes through a small injectable seam so tests use a **stub
runner** (assert each cell dispatched with the right variant/detail; no real
model calls). The matrix (encodings × models) is config data, not code.

### 3. Replay capture — extend the trace + reuse the recorder

- `_write_trace_entry` (`nethack_harness/helpers.py`) + its `env_response` call
  site: today it stores `rendered_user_message` (flattened text). Add
  `rendered_user_content` = the full per-turn content (`str` for text encodings;
  the `[image_url, text]` list for image encodings). For image content, write the
  PNG to `outputs/evals/<run>/images/<seed>_<turn>.png` and store its **relative
  path** in the entry (not the base64), keeping NDJSON lines small. Existing
  consumers that read `rendered_user_message` are unaffected.
- Human-viewable timeline: the harness opts the rollout into `legacy/replay.py`
  `TrajectoryRecorder` (rendered tty frames), so game state is replayable
  regardless of encoding.

### 4. Minimal renderer + integration seam — new module under `tools/`

A documented on-disk format (the extended NDJSON trace + the images dir + the
`Trajectory` json) and a marked entry point `render_replay(run_dir, *, form)`
where `form ∈ {human, llm}`. Ships a **minimal** renderer (a plain text/HTML
dump: per turn, the game-state frame for `human`, and the message text + an
`<img>`/path for `llm`). The rich viewer is a Group B task in `tools/launchpad`
reading the same format — no re-capture.

### 5. VLM config

`configs/eval/qwen-3-5-vl.toml` mirroring the existing TOML shape (model,
num_examples, rollouts_per_example, max_tokens, `[[eval]]` env_id), so IMG/IMG_TTY
are exercisable.

## Data flow

```
matrix config (encodings × models)
        │  per cell: variant + map_detail + model
        ▼
 orchestration ── invoke vf-eval/prime runner ──▶ samples (+ NDJSON trace, images/)
        │                                                     │
        │                                          rendered_user_content + PNG paths
        ▼                                                     ▼
 aggregation (pure) ── summarize_eval + progression_* ──▶ table (JSON + markdown)
        │                                            replay: render_replay(run, form=human|llm)
        ▼                                                     │
 outputs/evals/<run>/{table.json, table.md, traces, images/}  └── Group B viewer (later)
```

## Risks / Trade-offs

- [Real runs need keys/budget] → build + unit-test on mocks; the paid matrix is an
  operational step. The orchestration's runner seam lets tests stub it.
- [Token/$ accounting varies by provider] → derive from sample usage metadata;
  mark unavailable rather than guess (spec scenario).
- [Trace bloat from images] → PNGs on disk, paths in NDJSON.
- [Viewer scope creep] → ship only the minimal renderer; rich viewer is Group B.

## Testing strategy

- Aggregation: synthetic samples for several encodings → assert table shape,
  metric values, summarize_eval/progression used, `$/run` = n/a when usage absent.
- Orchestration: stub runner → assert each cell dispatched with the right
  variant/map_detail; matrix is config-driven (add/remove encoding w/o code).
- Replay capture: a multimodal turn writes `rendered_user_content` + a PNG file
  (image not elided); the minimal renderer reproduces text-form and image-form
  per turn from a recorded fixture; documented seam keys present.

## Out of scope

Running the paid real benchmark (operational follow-up); the rich Group B viewer;
RL training; any change to an encoding's rendered output.
