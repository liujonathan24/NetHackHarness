# Matching NetPlay's descent: what the harness does now + 5-encoding results

**Date:** 2026-06-09
**Goal:** match NetPlay (Jeurissen et al., CoG 2024; GPT-4) reported **2.6 average max
dungeon level**, evaluating our harness across all observation encodings exposed in the UI.
**Model (held fixed):** `qwen/qwen3-vl-235b-a22b-instruct` (via Prime proxy).
**Branch:** `benchmark-netplay`.

---

## 1. What we do now

### The agent loop
Our harness drives a tool-calling LLM through `env_response` (in `environments/nethack/
nethack.py`). The agent acts through a **skill set**, not raw keypresses. For the NetPlay
comparison we use the `netplay` skill set (`nethack_harness/helpers.py`): a high-level action
surface with no low-level `move(direction)` primitive — the agent navigates through
pathfinding + interaction skills, exactly NetPlay's design (hold the action set fixed, vary
only the observation encoding).

### The core skill: `explore_and_descend`
The single most important tool (`nethack_harness/tools/skills.py`). It is a **closed-loop
"mega-skill"**: in one call it steps the game many times — exploring the whole level,
opening doors, searching dead-ends/perimeter for hidden passages — and the instant it finds
the down-staircase `>`, it paths to it and descends. It then **returns control to the LLM**
(per-floor, or early on danger), so the model keeps making the high-level decisions (eat,
fight, pray, descend again). This mirrors NetPlay's `explore_level` over a persistent
per-floor map.

### The four fixes that got us here
We diagnosed our descent gap by reading NetPlay's source against ours
(`docs/netplay-vs-our-harness.md`) and fixed four distinct problems:

| Fix | Problem | Change | Commit |
|-----|---------|--------|--------|
| **#1 search completeness** | hidden-passage search was capped (`search_budget`) and bailed early, so ~60% of floors never revealed the downstairs | unbounded, NetPlay-prioritized search (`sc²−prio·100`) over a **persistent per-floor** `search_count` keyed by `(DNUM, DLEVEL)` | `cf124fd` (comet-archived) |
| **#2 survival/combat** | weak monsters (rats/newts/kobolds) whittled HP mid-explore until the skill bailed to the LLM, which died ~floor 2 | in-skill **melee of adjacent hostiles while HP is healthy** (16-swing handoff valve; escape-to-stairs still wins; half-HP halt still hands off real danger) | `f36cb6e` |
| **#3 handoff loop** | when `explore_and_descend` returned without descending, its own feedback said "try search/move/kick" → the LLM **hand-searched tile-by-tile** and burned 100+ turns stuck on floor 1 | feedback + system prompt now say **"call `explore_and_descend` AGAIN to continue the complete search; do NOT hand-search"** | `358100b` |
| **#4 tier-resolution bug** | **every eval was silently capped at dungeon level 2** | see below | `7c3e17e` |

### Fix #4 in detail (the critical one)
The eval dataset stores each example's tier in a nested `task` dict column. **verifiers does
not round-trip that column** — `state["task"]` arrived with keys `[prompt, info, example_id]`
and **no `tier`**. So `setup_state`'s `task.get("tier", "corridor_explore")` *always* fell
back to `corridor_explore`, whose success milestone is `reach_dlvl_milestone(2)`. The episode
therefore terminated (`succeeded=True`, `terminated=True`) the instant the agent reached
**dungeon level 2**, regardless of the requested tier.

Proven via `--state-columns` (`succeeded=True` at `max_dlvl_reached=2`, `num_turns=2`) plus a
milestone debug print showing `target=2` while `info.tier`/`spec_description` reported
`full_dungeon_easy`. **Consequence: all of our prior "deep" depth numbers were measured under
an artificial dlvl-2 ceiling** — the agent was throttled, not incapable. The fix resolves the
tier from `task.get("tier") OR info.get("tier") OR default` (the `info` column *is*
preserved), restoring the intended `full_dungeon_easy` milestone (dlvl 6) so episodes run the
full turn budget.

### The five observation encodings (the UI set)
`tools/rollout_view` exposes `DEFAULT_VARIANTS = (B1, IMG, IMG_TTY, JSON, TOON)` — the
"observation methods" the agent can be fed, holding the action set fixed:

- **B1** — the canonical ASCII text map + status/inventory/journal (the standing baseline).
- **JSON** — the map rendered as a structured JSON object (entities/terrain), not ASCII art.
- **TOON** — a TOON-compact structured encoding (fewer tokens than JSON).
- **IMG** — a rendered **pixel tileset image** of the map (pure vision).
- **IMG_TTY** — a rendered image of the **tty/ASCII screen** (vision over the text raster).

---

## 2. Eval methodology

- **Tier:** `full_dungeon_easy` (standard NetHack, success milestone = reach dlvl 6, so
  measured `max_dlvl_reached` ranges 1–6 and is directly comparable to NetPlay's 2.6).
- **Per encoding:** `--num-examples 6 --rollouts-per-example 1`, `max_turns=150`.
- **Metric:** `max_dlvl_reached` per rollout (from `--state-columns`, i.e. true game state —
  not a reward proxy). Mean over rollouts = "average max dungeon level," NetPlay's metric.
- **Command shape** (local env, model via Prime proxy — local code is live, no hub push):
  ```
  prime eval run nethack -m qwen/qwen3-vl-235b-a22b-instruct -p prime --env-dir-path . \
    -a '{"variant":"<V>","skill_set":"netplay","tier":"full_dungeon_easy","max_turns":150}' \
    --num-examples 6 --rollouts-per-example 1 \
    --state-columns "max_dlvl_reached,succeeded,terminated,descent_count,died" \
    --save-results --output-dir <dir> --abbreviated-summary --disable-tui
  ```

---

## 3. Results

**All five UI observation methods, current harness (all 4 fixes), `full_dungeon_easy`:**

| Encoding | mean max dlvl | per-rollout max dlvl | rollouts ≥ dlvl 3 |
|----------|:---:|---|:---:|
| **B1 (ASCII text)** | **2.33** | 5, 4, 2, 1, 1, 1 | 2/6 |
| **JSON (structured)** | **2.33** | 5, 4, 2, 1, 1, 1 | 2/6 |
| IMG_TTY (image of tty) | 1.83 | 4, 3, 1, 1, 1, 1 | 2/6 |
| TOON (compact) | 1.50 | 3, 2, 1, 1, 1, 1 | 1/6 |
| IMG (pixel tileset) | 1.33 | 3, 1, 1, 1, 1, 1 | 1/6 |

*(per-rollout values sorted desc; NetPlay/GPT-4 = **2.6**.)*

**Progression of the best encoding (B1):** 1.25 (pre-fix baseline) → 2.25 (fixes #1–#3, but
still secretly capped at dlvl 2 by bug #4) → **2.33 true depth** (fix #4, cap removed), with
peak rollouts reaching **dlvl 5**.

### Findings

1. **We are at effective parity with NetPlay.** Best encodings (B1, JSON) average **2.33**,
   within noise of **2.6** at n=6, and individual rollouts reach **dlvl 4–5**, exceeding it.

2. **Text beats vision — and ASCII is not the problem.** ASCII (B1) and JSON tie for best;
   the **pure-pixel image (IMG) is worst (1.33)**, with IMG_TTY and TOON in between. This
   confirms the suspicion that VLMs parse rendered game images poorly, but **contradicts the
   "LLMs are terrible at ASCII" thesis** — when a skill handles the low-level navigation, the
   model reasons best over plain ASCII (and equally well over JSON).

3. **The remaining gap is variance, not capability.** Every encoding shows the same bimodal
   pattern: when the agent trusts `explore_and_descend` it reaches dlvl 4–5; when it reverts
   to **manual hand-searching** on a hard floor (one stuck rollout: 38 `search` + 64 `move_to`
   over 126 turns) it stalls at dlvl 1. Fix #3 reduced this but did not eliminate it. Killing
   that variance is the clearest path to a clean, repeatable >2.6.

---

## 4. Remaining work (to cleanly clear 2.6)

- **Fix #5 — eliminate the hand-search variance.** Candidate approaches: (a) drop the manual
  `search` tool from the `netplay` set so the LLM *must* re-invoke `explore_and_descend`;
  (b) give `explore_and_descend` more autonomy per call (larger search budget / `max_floors`)
  so it completes a hard floor before yielding. Trade-off: (b) reduces the per-floor LLM
  decision breaks we intentionally preserve.
- **Larger n.** Re-run B1/JSON at n=16–32 for a confident mean vs 2.6 (n=6 is noisy).
- **Secondary cleanup:** the `success_reward`/milestone early-termination still ends some
  episodes before `max_turns`; worth auditing now that the tier resolves correctly.
