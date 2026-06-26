# Curriculum RL experiments — Go-Explore & Voyager (real primitives only)

**Faithful setup (the key constraint).** The agent gets **no descend/ascend
skill and no auto-descend**. It plays a female-neutral Valkyrie with **full
vision** (`reveal_map=1.0`, no fog of war) and may only use real game commands:
compass moves, run-macros, search, and the real stair commands `>` / `<`. The
cross-branch jump (Dungeons-of-Doom 3 ↔ Gehennom 48) is **internal** — it fires
only when the hero genuinely stands on the boundary stair
(`nle_hero_on_stair`) and takes the real `>`/`<`. So the agent must *find and
reach* the stairs itself; nothing hands it a descent.

Curriculum = a 6-floor down / 6-floor up tour:

```
floor:   1     2     3            4      5      6
level:  DoD1  DoD2  DoD3  --jump--> Geh48  Geh49  Geh50    (then climb back up)
```

Metric: deepest curriculum floor reached (1–6) and floors climbed back, over time.

## Results

| method | agent | deepest floor / 6 | climbed back | seeds |
|---|---|---|---|---|
| **Go-Explore** | random primitives (+ run-macros, takes a stair when it lands on one) | **2** | 0 | 19, 2, 9 (2000 iters) |
| **Voyager** | GLM 5.2, full vision, A* `move_to` + real stairs | **1** (seed 19) | 0 | 19 (60 turns); 2 in progress |
| **LLM-Go-Explore** | GLM 5.2 explore policy + Go-Explore archive | (navigation-limited, same wall) | 0 | — |

Voyager seed 19 detail: 60 turns, **never left floor 1** — 36 `move_to`, 21
`search`, 0 `stairs_down` (it never reached a down stair). It did *worse* than
random Go-Explore because A* `move_to` repeatedly traps in a room whose only exit
is a monster-blocked doorway, while random exploration occasionally stumbles onto
a stair.

## The finding

**Without the descend/ascend skills, neither method descends the curriculum** —
both plateau at floor 1–2. The binding constraint is **navigation to the stairs**,
not the learning algorithm:

- A* can't route through a monster sitting on the only doorway (the monster tile
  isn't walkable), so `move_to` returns "no path";
- greedy best-effort then traps against the room wall (local minimum);
- random exploration rarely lands on the exact `>` tile to descend.

This directly confirms the hypothesis that the `descend` / `explore_and_descend`
skills were doing essentially all the work — they bundled the (hard) navigation +
the descent. Strip them, and the agents are stuck near the top. It also matches
prior harness/NLE findings (methods tie a random walk at ~dlvl 1 without a
navigation skill).

## What it would take to actually descend (the harness-optimization axis)

To get a meaningful "how deep over time" curve, the agents need a **robust
navigation primitive** that reliably reaches a chosen tile across a whole level —
exploring to reveal it, opening doors, and fighting/▸swapping through blockers —
*without* auto-descending. That is navigation, not a descend skill, and it is
exactly the "harness optimization" axis (improving the agent's tooling). The
harness's own `autoexplore`/pathfinding is the battle-tested basis; the work is to
expose it to these runners minus the auto-descend divert. With that in place the
curriculum's deep content becomes reachable and the depth-over-time comparison
becomes informative.

Runners: `approaches/go_explore/curriculum_go_explore.py`,
`approaches/voyager/curriculum_voyager.py`,
`approaches/go_explore/curriculum_go_explore_llm.py`. Raw outputs:
`outputs/curriculum_experiments/`.
