# PufferLib adapter: 10× speedup path for non-LM RL

**Status:** Shipped in `nethack_core/puffer_env.py` as of Day 3. Tested in
`tests/test_puffer_env.py`. PufferLib itself is *not* a hard dependency — the
adapter is gymnasium-shaped and PufferLib consumes it externally.

## Why this exists

Two audiences for the nethack-rl substrate:

1. **LM agents** (the headline). Inference dominates; env throughput doesn't
   matter beyond ~1 env/sec.
2. **Non-LM RL** (PufferLib, Sample Factory, anyone running PPO on NLE).
   Env throughput is the bottleneck. PufferLib's shared-memory vec backend
   gives ~10× synchronous speedup on NLE (Suarez et al., RLJ 2025).

The adapter lives in layer 1 so PufferLib users can take just `nethack-core`
without pulling in `verifiers` / `prime-rl` / OpenAI deps.

## Why no `pufferlib` install hook

PufferLib 3.0 depends on `raylib` (a C library for game rendering it uses for
the visual debugger). On macOS that's `brew install raylib`; on Ubuntu it's
`apt-get install libraylib-dev`. We don't want to force this on every user of
`nethack-core`, so we ship the adapter without a hard pufferlib dep.

PufferLib install path (do this manually if you want it):

```bash
# macOS:
brew install raylib
# Ubuntu/Debian:
sudo apt-get install -y libraylib-dev
# then:
uv pip install "pufferlib>=2.0"
```

## The adapter

Two layers:

```python
class _GymDictWrapper(gym.Env):
    """NetHackCoreEnv → standard gymnasium Env with Dict obs space."""

def to_gym_dict_env(inner: NetHackCoreEnv) -> gym.Env: ...
def make_for_puffer(tier_name: str, **kwargs) -> gym.Env: ...
```

The wrapper bridges two API conventions:

- **NetHackCoreEnv** requires `seed()` before `reset()` (deterministic by
  construction). It returns a `CoreObservation` dataclass.
- **gymnasium** calls `reset(seed=N, options=...)` in one shot and expects a
  dict obs.

`_GymDictWrapper.reset(seed=N)` translates: `self._inner.seed(N, N);
self._inner.reset() → dict`. If no seed is passed (some PufferLib paths
don't), we fall back to a deterministic-per-instance value computed from
`id(self)` so each vec worker gets a distinct but stable trajectory.

## Performance math

Per `tools/profile_env.py`:

| metric | single-env (synchronous) | with 16-worker shmem vec (projected) |
|---|---:|---:|
| NLE step | ~60k sps | ~960k sps |
| observations.shape (Python-side) | ~3.8k sps | ~60k sps |
| End-to-end PPO step | ~4k sps | ~64k sps |

The Python-side shape() call is the gating factor at synchronous throughput.
PufferLib's vec backend doesn't directly speed that up *but* runs 16 copies
of it in parallel, so wall-clock throughput scales near-linearly with CPU
count. Net is the same ~10× Suarez et al. report.

## Usage

Pure gymnasium:

```python
from nethack_core.puffer_env import make_for_puffer

env = make_for_puffer("mines_to_minetown")
obs, _ = env.reset(seed=42)
for _ in range(100):
    obs, r, term, trunc, _ = env.step(env.action_space.sample())
    if term or trunc:
        break
```

With PufferLib (once you've installed it):

```python
from pufferlib.environments.gymnasium import GymnasiumEnvironment
from pufferlib.vector import make_vec

def make_env():
    return make_for_puffer("mines_to_minetown")

vec_env = make_vec(make_env, num_envs=16, backend="shmem")
# vec_env now steps 16 envs in parallel via shared-memory IPC
```

## How to verify

```bash
uv run pytest tests/test_puffer_env.py -v
```

Five tests confirm the gym contract: Dict obs space, Discrete action space,
seed-determinism via `reset(seed=N)`, the 5-tuple step return, and
`to_gym_dict_env` over an externally-constructed `NetHackCoreEnv`.

## Future work

- **`pufferlib.environments.nethack` upstream.** Puffer already ships a
  first-party NetHack env. Replacing it (or contributing alongside) with
  this one would give Puffer users our ICLR-2026 obs fixes for free. Worth
  reaching out to Joseph Suarez before pushing a PR.
- **Native batched step.** Puffer's biggest wins come from envs that
  natively step many envs at once (Atari, Pokemon-Red). NLE doesn't, but
  if we ever wrap C-side NLE for thread-safe batched stepping, that's the
  unlock for >100k sps single-process.
- **Frame stack option.** PPO baselines often want a 4-frame stack of
  glyphs. Adding `frame_stack=4` to `make_for_puffer` would close that gap.
