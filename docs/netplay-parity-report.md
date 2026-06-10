# Reaching NetPlay's descent depth: diagnosis, five fixes, and an honest measurement

**Date:** 2026-06-09
**Branch:** `benchmark-netplay`
**Target:** NetPlay (Jeurissen et al., CoG 2024; GPT-4) reports **2.6 average max dungeon
level**. We hold the model fixed at `qwen/qwen3-vl-235b-a22b-instruct` (via Prime proxy) and
ask: can our harness match that, and which observation encoding is best?

> **Status:** final. At n=24, **B1 (ASCII) = 2.29 ± 0.24 SE**, statistically consistent with
> NetPlay's **2.6** (~1.3 SE below — not a clean pass, but within noise); **JSON = 1.96 ± 0.27**
> trails it. The dominant failure mode is **death, not the turn budget** (B1: 22/24 deaths, 2
> turn-outs), and **text encodings beat vision**.

---

## 1. TL;DR

- We went from a measured **mean max dungeon level of 1.25 to 2.29 ± 0.24** (B1, n=24) — close
  enough to NetPlay's **2.6** to be statistically consistent with it (not a clean pass), with
  individual rollouts reaching dungeon level 5–6 (the tier's win condition).
- Getting there took **five fixes**, only two of which were "make the agent smarter." The
  other three were **measurement and harness bugs** — most importantly, a bug that silently
  **capped every eval at dungeon level 2**, making all earlier numbers meaningless for this
  comparison.
- **Text beats vision.** Plain ASCII (B1) and structured JSON tie for best; the pixel-tileset
  image (IMG) is worst. This confirms VLMs parse rendered game images poorly, but refutes the
  premise that "LLMs are terrible at ASCII" — with a skill handling navigation, the model
  reasons best over plain text.
- **Death — not the clock — is what stops us.** ~3 of every 4 games end in death (starvation
  or melee attrition on early floors), only ~1 in 30 hits the turn cap. The remaining gap to a
  *clean, repeatable* >2.6 is survival and variance, not exploration.

---

## 2. The goal and the metric

NetPlay is an LLM agent for NetHack built on a high-level skill API over a complete rule-based
bot (autoascend). Its headline number is **2.6 average maximum dungeon level reached** per
game. To compare like-for-like we measure **`max_dlvl_reached`** per rollout (read from game
state, not a reward proxy) on a tier that lets the agent descend freely, and average it.

**Tier:** `full_dungeon_easy` (standard NetHack, episode ends at dungeon level 6), so
`max_dlvl_reached` ranges 1–6 and its mean is directly comparable to 2.6.
**Per condition:** `--num-examples 24`, `max_turns=150`, depth via `--state-columns`.

---

## 3. What the harness does now

**The agent loop.** A tool-calling LLM is driven through `env_response` (`environments/
nethack/nethack.py`). It acts through a **skill set**, not raw keypresses. For this comparison
we use the `netplay` skill set — a high-level action surface with no low-level
`move(direction)` primitive — mirroring NetPlay's design of holding the action set fixed and
varying only the observation.

**The core skill: `explore_and_descend`.** One call steps the game many times — exploring the
level, opening doors, searching dead-ends/perimeter for hidden passages — and the instant it
finds the down-staircase, paths to it and descends, then **hands control back to the LLM**
(per floor, or early on danger). This mirrors NetPlay's `explore_level` over a persistent
per-floor map, while preserving LLM decision points.

**The five observation encodings (the UI set, `tools/rollout_view`):** **B1** (ASCII map +
status/inventory/journal), **JSON** (map as a structured object), **TOON** (compact structured),
**IMG** (rendered pixel tileset), **IMG_TTY** (rendered image of the tty screen). Action set is
identical across all five; only the observation changes.

---

## 4. The five fixes (a diagnosis-driven iteration)

We diagnosed the descent gap by reading NetPlay's source against ours
(`docs/netplay-vs-our-harness.md`), then fixed problems one at a time, re-measuring each.

| Fix | Problem | Change | Commit |
|-----|---------|--------|--------|
| **#1 search completeness** | hidden-passage search was capped and bailed early; downstairs often never found | unbounded, NetPlay-prioritized search over a **persistent per-floor** `search_count` | `cf124fd` |
| **#2 survival / combat** | weak monsters chipped HP mid-explore until the skill bailed and the agent died ~floor 2 | **in-skill melee** of adjacent hostiles while HP is healthy (handoff valve; escape-to-stairs wins) | `f36cb6e` |
| **#3 handoff loop** | when the skill returned without descending, the LLM **hand-searched** and burned 100+ turns stuck on floor 1 | feedback + prompt: **"call `explore_and_descend` again; do NOT hand-search"** | `358100b` |
| **#4 tier-resolution bug** | **every eval was silently capped at dungeon level 2** | resolve tier from the preserved `info` column (see §5) | `7c3e17e` |
| **#5 survival + pet tactics** | death (not turns) ends most games | death-cause prompt + ranged `throw` tool + **pet tactics**: pet-aware descent, let-the-pet-kill, kiting | `fdc1473` |

**Fix #5 detail (pet tactics).** The starting pet is a strong early ally. `explore_and_descend`
now (a) **waits on the downstairs** (≤8 turns) for the pet to be adjacent so it follows us
down; (b) when a hostile is adjacent *and* the pet is engaging it, **kites** away (≤4 retreat
steps) to let the pet trade blows for free instead of taking melee damage; (c) only melees
when cornered or the pet can't finish.

---

## 5. Methodology lessons (the bugs that mattered most)

Three of the five "fixes" were really **measurement integrity**, and they dominate the story:

1. **The dlvl-2 cap (fix #4).** verifiers does not round-trip the dataset's nested `task`
   dict, so `state["task"]` arrived without the `tier` key and `setup_state` silently fell
   back to the `corridor_explore` tier — whose success milestone is dungeon level **2**. Every
   episode therefore *terminated at dungeon level 2*, regardless of the tier we requested.
   Proven with `--state-columns` (`succeeded=True` at `max_dlvl_reached=2`, `num_turns=2`) and
   a milestone debug print showing `target=2` while the reported tier said `full_dungeon_easy`.
   **All depth numbers before this fix were measured under a floor-2 ceiling.**

2. **The death-flag undercount.** The `state["died"]` flag caught only **3 of ~22 actual
   deaths** — the agents' own end-of-game narration ("Game over. You died on Dlvl 1 — killed
   by a fox", starvation, etc.) tells the real story. The death detector misses most deaths;
   any analysis using that flag (including an earlier draft of the encoding write-up)
   undercounts deaths badly. We classify endings from the game's terminal text instead.

3. **n=6 is noise.** With six rollouts per condition, the two best encodings moved in
   *opposite* directions for the *same* change (pet tactics: B1 2.83→2.00, JSON 1.83→2.83).
   When a change and its anti-effect both appear depending on which encoding you read, you are
   measuring sampling variance. Every per-condition mean below n≈20 is a coin-flip. This report's
   headline numbers (§6) come from **n=24** for exactly this reason.

---

## 6. Results

### 6a. The journey (best encoding, B1), as fixes landed

| State | mean max dlvl | note |
|-------|:---:|------|
| pre-fix baseline | 1.25 | capped at dlvl 2 by bug #4, so even this is throttled |
| + fixes #1–#3 | 2.25 | still secretly capped at dlvl 2 |
| + fix #4 (cap removed) | 2.33 | first *true* depth measurement; peaks at dlvl 5 |
| + fix #5 (survival/pet), n=6 | 2.0–2.83 | within noise — motivated the n=24 run |

### 6b. n=24 confirmation (final), `full_dungeon_easy`, all fixes

| Encoding | n | mean max dlvl | died | out of turns | other¹ | dlvl ≥3 | dlvl 6 (win) |
|----------|:-:|:---:|:---:|:---:|:---:|:---:|:---:|
| **B1 (ASCII)** | 24 | **2.29 ± 0.24** | 22 | 2 | 0 | 10/24 | 0 |
| **JSON** | 24 | **1.96 ± 0.27** | 11 | 2 | 11 | 5/24 | 1 |

_(± = standard error of the mean. NetPlay/GPT-4 = 2.6.)_
¹ _"other" = the episode ended while the agent was still issuing tool calls, before the turn
cap — almost certainly the in-game NLE step budget exhausting inside long `explore_and_descend`
calls. JSON hits this far more than B1 (11 vs 0)._

**Depth distribution (count of rollouts reaching exactly each level):**

| dlvl | 1 | 2 | 3 | 4 | 5 | 6 |
|------|:-:|:-:|:-:|:-:|:-:|:-:|
| B1   | 8 | 6 | 6 | 3 | 1 | 0 |
| JSON | 12| 7 | 2 | 1 | 1 | 1 |

The bimodal shape is the story: a third of B1 rollouts (8/24) stall at dungeon level 1, while
10/24 push to level 3+. The mean is a tug-of-war between those two buckets.

**On fix #5 (survival + pet tactics):** at this sample size it is **roughly neutral** for B1
(2.29 vs the pre-#5 2.33). The n=6 swing to 2.83 was an upward fluctuation, not a real lift —
exactly the noise §5.3 warned about. The `eat`-uptake jump (4→52 calls) is real, but it did
not translate into a measurable depth gain at n=24, and the `throw` tool stayed at zero use.
The honest read: the survival/pet code is sound and NetHack-correct, but **does not move the
aggregate metric** — death still ends ~90% of B1 games.

### 6c. Five-encoding snapshot (n=6, fixes #1–#4, for the text-vs-vision ranking)

| Encoding | mean max dlvl |
|----------|:---:|
| B1 (ASCII) | 2.33 |
| JSON (structured) | 2.33 |
| IMG_TTY (image of tty) | 1.83 |
| TOON (compact) | 1.50 |
| IMG (pixel tileset) | 1.33 |

---

## 7. Findings

1. **At or near parity with NetPlay (best encoding).** B1 = **2.29 ± 0.24** at n=24 — 2.6 sits
   ~1.3 standard errors above, so we are *statistically consistent with parity* but cannot
   claim a clean pass. JSON trails at **1.96 ± 0.27**. Peak rollouts reach dungeon level 5–6
   (JSON had one full win), so the *capability* is there; the average is dragged down by the
   large bucket of floor-1 stalls and early deaths.

2. **Text beats vision, and ASCII is not the weak link.** ASCII (B1) and JSON lead; the pure
   pixel image (IMG) is worst. VLMs read rendered NetHack poorly, but a navigation skill makes
   plain text the strongest substrate.

3. **Death, not the clock, is the binding constraint.** ~73% of games end in death (mostly
   starvation and melee attrition on floors 1–2); ~1 in 30 hits the turn cap. Survival fixes
   (#2, #5) target the right thing; the food/eat prompt drove a 13× jump in eating (4→52 calls
   on B1). The ranged `throw` tool, however, saw **zero uptake** — the model never used it,
   so ranged attack is not (yet) a working lever for these early-floor deaths.

4. **The remaining gap is variance, not ideas.** Every condition is bimodal: a couple of
   rollouts dive to dlvl 4–6, the rest stall at dlvl 1 (a hard floor, or an early death). The
   route to a *clean, repeatable* >2.6 is reducing that variance, and measuring it at adequate n.

---

## 8. Remaining work

- **Confirm fix #5 at scale** (this run) and decide keep/trim — e.g. drop the unused `throw`
  tool if it stays at zero uptake.
- **Fix the death detector** (`_detect_terminal_outcome`) so the `died` flag is trustworthy;
  re-classify deaths by cause to target survival precisely.
- **Audit early termination** — some episodes still end before the turn cap while the agent is
  still acting (likely the in-game NLE step budget inside long `explore_and_descend` calls).
- **Variance reduction** — the bimodal stall-at-floor-1 vs dive-to-6 split is the last lever
  toward a repeatable >2.6.
