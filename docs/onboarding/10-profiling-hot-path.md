# Layer-1 profiling: where the time goes

**Status:** Measured Day 3 with `tools/profile_env.py`. Numbers below are
from Python 3.13 on an M-series Mac; expect similar relative ordering on
Linux + Intel.

## Measured throughput

```
NLE step (1 action)               0.016 ms/call   60,700 steps/sec
observations.shape()              0.258 ms/call    3,882 calls/sec
a_star (~5-step path)             0.036 ms/call   27,500 calls/sec
nearest_frontier (whole map)      0.250 ms/call    4,000 calls/sec
```

## What surprised us

1. **NLE 1.3 is ~4× faster than the 14k sps quoted in PufferLib literature.**
   60k+ sps on a single core means NLE is no longer the bottleneck for
   non-LM RL. The PufferLib 10× speedup claim was on a *NLE 1.0 baseline*;
   the gap has narrowed.
2. **`observations.shape()` is the layer-1 hot path** — 16× more expensive
   than the raw NLE step. Inside it the dominant costs are:
   - `parse_inventory` (54 inv slots, byte decode + 2 regexes per slot)
   - `render_map_view` (24*80 char decode + menu masking)
   - `extract_menu_region` (regex scan over each row)
3. **A\* is fast** — 27k calls/sec on small paths. Bigger paths cost more
   but the heuristic is admissible and the heap operations dominate.
4. **`nearest_frontier` is the slowest core primitive at 4k/sec** because
   it BFS's the whole grid; could be capped or cached.

## What this means for the project

- **For LM training**, env throughput is not the bottleneck. Inference is.
  Each `env_response` is ~1 ms; each LM forward pass is 100+ ms (4B model).
- **For non-LM PPO** (the PufferLib audience), 60k sps + 4k shape() calls/sec
  means single-env throughput is *4k/sec end-to-end*. Vectorizing across 16
  CPU workers gets us close to ~64k effective sps. Adding PufferLib's
  shared-memory vec would push that another ~10×.
- **The reward functions read pre-computed scalars** (`scout_delta`,
  `state["succeeded"]`, etc.) so they're free. Don't tune the rubric for
  perf.

## Optimization opportunities (not yet implemented)

In rough priority order:

1. **`parse_inventory` vectorization.** The 54-row byte decode + regex
   matches can be expressed as a single np operation over `inv_strs`
   (find first NUL per row → slice → decode). ~3× speedup expected.
2. **`render_map_view` short-circuit.** When no menu is open (the common
   case during exploration), skip the masking pass entirely. Already done
   conditionally; profile-confirm we hit the fast path.
3. **Frontier set caching.** `nearest_frontier` recomputes the entire
   frontier set every call. Cache it keyed by `id(chars)` and invalidate
   on env.step. ~4× speedup on autoexplore-heavy traces.
4. **Lazy `format_observation_as_chat`.** Don't render the chat block when
   we know we'll terminate this turn. Tiny saving but it's the rendered
   string that's the largest object in `state` so memory matters.
5. **PufferLib `PufferEnv` wrapper.** Layer-1 `NetHackCoreEnv` is already
   gymnasium-shaped; the wrapping is ~150 lines. Saved for week 3.

## How to verify / extend

```bash
source .venv/bin/activate
python tools/profile_env.py
```

To bench a specific function, append a `_bench("label", lambda: ..., n=N)`
line in `profile_env.py`. The harness is intentionally tiny — no plotting,
no decorator framework, just a clean printed table.

## References

- PufferLib 2.0 (Suarez et al., RLJ 2025) — the speed bar to beat.
- `tools/profile_env.py` — the actual benchmark script.
- `docs/onboarding/08-pathfinding-and-autoexplore.md` — where a_star and
  nearest_frontier come from.
