# Observation + history compaction

**Status:** Shipped v0.0.17–24. Reduces per-rollout token cost by **~90%**
(measured: `experiments/exp15_token_savings.py`, 60-turn synthetic).

## The problem

Before compaction, a 150-turn Qwen3.5-9B rollout burned **4.3M input tokens
= $0.79**. The bill is dominated by the same map grid being re-emitted in
the chat history every turn. Per-turn obs was ~27k tokens; the cumulative
chat history grew linearly in turns.

After compaction, the same regime burns ~10% of that.

## What got built

### Per-turn obs compaction (v0.0.17, v0.0.20, v0.0.21, v0.0.24)

In `nethack.py::format_observation_as_chat`:

1. **`_strip_blank_rows`** — drop empty tty rows + trim trailing whitespace.
2. **`_glyph_run_encode`** — replace `.....` / `#####` runs of length ≥5
   with `.{N}` / `#{N}`. The SYSTEM_PROMPT teaches the model to read this.
3. **`_inventory_fingerprint`** — emit "INVENTORY (unchanged)" between
   turns when the inventory hasn't changed.
4. **`_run_length_encode_messages`** — `"You hit the kobold." (x10)`.
5. **Adjacency + visible-glyph blocks** — pre-extracted "what's around me"
   so the model doesn't scan the map.
6. **Journal diff** — emit "(unchanged since last turn)" when the journal
   fingerprint matches the last render.

### History compaction (v0.0.18)

`NetHackVerifiersEnv.get_prompt_messages` overrides the verifiers default
to run `_compact_chat_history` on the chat history before each LM call:

- last `keep_full=5` turns: full fidelity (no change)
- turns 6..`drop_after=100`: replaced with one-line summary (turn label +
  any `[autohalt: ...]` prefix + the HP/Dlvl/Turn status line).
- turns > `drop_after`: dropped entirely, replaced by a single elision
  marker at the start of the message list.

### Periodic belief-state (v0.0.19)

Every `BELIEF_STATE_INTERVAL=25` turns, `env_response` calls
`SubLM.summarize(journal_notes, query="belief state at turn N")` and
stores the result as a `belief_state:tN` note in the journal. This is the
long-term memory that survives history compaction.

### Journal render cap (v0.0.22)

`Journal.render(max_chars=2000)` enforces a soft cap on per-turn journal
payload. `belief_state:` notes are pinned through the cap; other older
notes get elided behind a "[elided N older notes]" marker.

## Tunable knobs (v0.0.23)

All five compaction parameters are now `load_environment(...)` kwargs:

```python
load_environment(
    compact_obs=True,                # disable to compare against v0.0.15 baseline
    history_keep_full=5,             # how many recent turns stay full
    history_drop_after=100,          # turns older than this get dropped
    belief_state_interval=25,        # 0 = disable periodic distillation
    journal_render_max_chars=2000,   # soft cap per-turn journal block
)
```

Via the CLI:
```bash
prime eval jonathanliu/nethack -m Qwen/Qwen3.5-9B -n 1 -r 1 \
  -a '{"compact_obs": false}'   # A/B against baseline
```

## Verification

| What | How |
|------|-----|
| Token savings measured | `python experiments/exp15_token_savings.py` |
| Per-turn obs unit tests | `tests/test_obs_compaction.py` (14 tests) |
| History compaction unit tests | `tests/test_history_compaction.py` (7 tests) |
| Belief-state e2e | `tests/test_belief_state.py` (5 tests) |
| Adjacency/hostiles extraction | `tests/test_adjacent_hostiles.py` (7 tests) |
| Knobs reach the env | `tests/test_smoke.py::test_compaction_knobs_threaded_through` |

## Future work

- **Action-history footer** (survey rec #7): keep a compact "last 20 actions"
  line; not yet implemented.
- **Verbosity presets** (survey "Prompting-side knobs we should add"):
  `obs.verbosity = "minimal" | "standard" | "verbose"` that maps to known-
  good knob combinations.
- **`request_field` tool** (OpenHands-style condensation_request): let the
  LM ask for an elided detail back. Out of scope for v0; would need
  per-turn message replay infrastructure.
- **Real SubLM** for belief-state — currently `OfflineSubLM` returns
  templated stubs. Plug in prime-rl client to get real LM-written summaries.
