# Curriculum eval results — GLM 5.2

First experiment on the `curriculum` tier, run through the Prime Intellect eval
pipeline (`vf-eval`, Prime Inference) with **`z-ai/glm-5.2`**.

## Setup

- Model: `z-ai/glm-5.2` (Prime Inference, `https://api.pinference.ai/api/v1`)
- Env: `nethack` tier `curriculum` (female-neutral Valkyrie, full vision)
- Observation: **B0** (raw ASCII, non-compacted), interface `skill`
- 3 seeds × 2 rollouts = 6 rollouts, `max_turns=40`, temp 0.7, `max_tokens=4096`
- Eval wall time: 388 s (~6.5 min)

Command:

```bash
PYTHONPATH=environments/nethack vf-eval nethack --env-dir-path environments \
  -m z-ai/glm-5.2 -p prime -k PI_API_KEY --endpoints configs/endpoints.toml \
  -a '{"tier":"curriculum","variant":"B0","compact_obs":false,"max_turns":40}' \
  -n 3 -r 2 --max-concurrent 3 --num-workers 3 --max-tokens 4096 --save-results
```

## Results

**Success (reached the Elemental Planes): 6/6 = 100%.**

| metric | avg | std |
|---|---|---|
| success_reward (reached planes) | 1.000 | 0.000 |
| reward (total) | 55.05 | 1.16 |
| descent_reward | 48.50 | 0.50 |
| scout_reward | 5.55 | 0.68 |
| num_turns | 18.8 | 2.8 |
| descend_calls | 5.7 | 0.7 |
| ascend_calls | 6.5 | 0.5 |
| move/move_to calls | ~0 | — |
| truncated | 0.0 | — |

Per-rollout:

```
[0] success=1.0 reward=55.7 turns=16 descend=5 ascend=7 move=0
[1] success=1.0 reward=53.8 turns=16 descend=6 ascend=6 move=0
[2] success=1.0 reward=54.3 turns=23 descend=7 ascend=6 move=0
[3] success=1.0 reward=53.7 turns=19 descend=6 ascend=6 move=0
[4] success=1.0 reward=56.3 turns=17 descend=5 ascend=7 move=0
[5] success=1.0 reward=56.4 turns=22 descend=5 ascend=7 move=0
```

## Read

- Every rollout completed the full curriculum tour — DoD 1→3, the jump to deep
  Gehennom (with the stat upgrade), the bottom, then the climb back up into the
  Elemental Planes — using only `descend`/`ascend` (no navigation, `move`≈0).
  This is exactly the intended behavior: the curriculum exposes late-game
  content without the agent having to solve dungeon navigation first.
- `ascension_reward = 0`: reaching the planes is curriculum success; actually
  winning the whole game (ascending with the Amulet) is out of scope here.
- Raw artifacts: `outputs/curriculum_eval/evals/nethack--z-ai--glm-5.2/9063593a/`
  (`results.jsonl`, `metadata.json`, worker logs).

The 5 `Traceback` lines in the run log are the benign `multiprocess
resource_tracker` cleanup-at-exit warning (not rollout failures); all rollouts
completed (`is_truncated=0`).
