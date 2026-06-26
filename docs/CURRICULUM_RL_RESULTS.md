# Curriculum RL experiments — Go-Explore & Voyager (real primitives only)

These runs use the **faithful** curriculum: the agent gets **no descend/ascend
skill** and no auto-descend. It plays a female-neutral Valkyrie with full vision
and may only use real game commands (compass moves, run-macros, search, and the
real stair commands `>` / `<`). The cross-branch jump (Dungeons-of-Doom 3 ↔
Gehennom 48) is **internal**: it fires only when the hero genuinely stands on the
boundary stair (`nle_hero_on_stair`) and takes the real `>`/`<`. The agent must
find and use the real stairs itself.

Curriculum = a 6-floor down / 6-floor up tour:

```
floor:   1     2     3            4      5      6
level:  DoD1  DoD2  DoD3  --jump--> Geh48  Geh49  Geh50    (then climb back up)
```

Metric: **deepest curriculum floor reached** (how far down, 1–6) and
**floors climbed back up** from the bottom — tracked over time.

## Go-Explore (`approaches/go_explore/curriculum_go_explore.py`) — DONE

Pure exploration over real primitives (run-macros to traverse corridors; takes a
stair in the tour direction whenever it lands on one). 2000 iters × 60
explore-steps, seeds 19/2/9.

| seed | deepest floor | climbed back | reached bottom |
|------|---------------|--------------|----------------|
| 19   | 2 / 6 | 0 | no |
| 2    | 2 / 6 | 0 | no |
| 9    | 2 / 6 | 0 | no |

Depth over time (seed 19): floor 2 by iter ~50, then **flat** through iter 2000
(cells grow 10→95 but it never finds the next level's down stair).

**Finding:** Go-Explore on pure random primitives hits the **navigation wall** —
it explores a level but rarely random-walks onto the exact down-stair tile to
descend further, so it plateaus at floor 2. This matches prior harness findings
(LLM/RL methods tie a random walk at ~dlvl 1 without a navigation skill). Raw
per-seed time series: `outputs/curriculum_experiments/go_explore/`.

## Voyager (`approaches/voyager/curriculum_voyager.py`) — READY, BLOCKED ON CREDS

An LLM (GLM 5.2 via Prime Inference) with full vision and a faithful tool set:
`move_to(x,y)` (A* navigation over the real map — real moves, **never**
auto-descends), `stairs_down`/`stairs_up` (real `>`/`<`, only work while standing
on the stair), `search`. The LLM sees every visible `>`/`<`, navigates onto one,
and takes it — composing descent from primitives it isn't handed (the Voyager
idea).

**Status: blocked.** The Prime inference token in `~/.prime/config.json`
(`pit_…`, dated Jun 15) has **expired** — the API now returns
`401 "Invalid or expired token, or user not part of team"`. (Earlier in the
session the same key worked.) Refresh it, then:

```bash
PI_API_KEY=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.prime/config.json')))['api_key'])") \
OMP_NUM_THREADS=1 TMPDIR=/scratch/gpfs/ZHUANGL/jl0796/jl_agent_tmp \
python approaches/voyager/curriculum_voyager.py --seeds 19 2 9 --max-turns 60 \
  --model z-ai/glm-5.2 --out outputs/curriculum_experiments/voyager
```

Expectation: with full vision + A* navigation, Voyager should reach and take each
down stair (descending through the jump into Gehennom) far deeper than Go-Explore,
and then climb back up — the intended down-and-up curriculum traversal.
