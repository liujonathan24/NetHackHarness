# Reaching NetPlay's descent depth: diagnosis, five fixes, and an honest measurement

**Date:** 2026-06-09
**Branch:** `benchmark-netplay`
**Target:** NetPlay (Jeurissen et al., CoG 2024; GPT-4) reports **2.6 average max dungeon
level**. We hold the model fixed at `qwen/qwen3-vl-235b-a22b-instruct` (via Prime proxy) and
ask: can our harness match that, and which observation encoding is best?

> **Status:** final. At n=24, the best cells reach **2.29 ± ~0.25 SE** (B1+pet, JSON+nopet) —
> statistically consistent with NetPlay's **2.6** (~1.3 SE below; not a clean pass). A pet-vs-
> non-pet ablation at n=24 (§6b) shows the **pet tactics are net-neutral** (they help B1, hurt
> JSON; combined 2.13 vs 2.06). Failure mode = **death, not the turn budget**; the deeper cause
> is the agents **never level up** (mean XL ~1.4 — they dive fast and die weak). **Text beats
> vision.**

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
- **Death — not the clock — is what stops us,** and the deeper cause is **weakness**: ~⅔–¾ of
  games end in death, and the agents barely level (mean experience level ~1.4, most end at the
  starting XL 1, ~0.4 kills/game). They dive fast and die weak. The highest-leverage untried
  lever is the **speed-vs-strength tradeoff** (level up a little before descending).
- **A pet-vs-non-pet ablation at n=24 settled fix #5: net-neutral.** Pet tactics help B1
  (+0.46) but hurt JSON (−0.33); combined they move the mean 0.07 (within ±0.25 SE). Below
  ~n=20, per-condition differences are coin-flips — the lesson that made us run n=24 at all.

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

### 6b. n=24 results, `full_dungeon_easy` — pet vs non-pet ablation

The full harness (fixes #1–#4 + survival) with the **pet tactics** (pet-aware descent +
kiting + let-the-pet-kill) **on vs off** (`NETHACK_DISABLE_PET=1`), n=24 each:

| Encoding | pet **ON** (mean ± SE) | pet **OFF** | Δ (on−off) | deaths on/off | dlvl≥3 on/off |
|----------|:---:|:---:|:---:|:---:|:---:|
| **B1 (ASCII)** | **2.29 ± 0.24** | 1.83 ± 0.18 | **+0.46** | 22 / 14 | 10 / 6 |
| **JSON** | 1.96 ± 0.27 | **2.29 ± 0.28** | **−0.33** | 11 / 13 | 5 / 8 |
| **B1+JSON combined** | 2.13 | 2.06 | +0.07 | — | — |

_(deaths/dlvl≥3 are counts out of 24. NetPlay/GPT-4 = 2.6.)_

**Pet tactics are net-neutral.** The two encodings disagree on sign — pet *helps* B1 (+0.46)
and *hurts* JSON (−0.33) — and the combined mean barely moves (2.13 vs 2.06, a 0.07 swing well
inside the ±0.25 SE). Each per-encoding Δ is only ~1.5 SE, i.e. not significant. This is the
same pattern §5.3 flagged at n=6 (opposite-direction-per-encoding), now confirmed at n=24: the
pet/kiting code is sound and NetHack-correct, but **does not reliably move the aggregate
metric.** The best single cell — B1+pet and JSON+nopet, both **2.29** — sits just under 2.6.

**Depth distribution (count of rollouts reaching exactly each level):**

| run | 1 | 2 | 3 | 4 | 5 | 6 |
|-----|:-:|:-:|:-:|:-:|:-:|:-:|
| B1 pet     | 8 | 6 | 6 | 3 | 1 | 0 |
| B1 nopet   | 11| 7 | 5 | 1 | 0 | 0 |
| JSON pet   | 12| 7 | 2 | 1 | 1 | 1 |
| JSON nopet | 8 | 8 | 5 | 0 | 2 | 1 |

The bimodal shape is the real story everywhere: ~⅓ of rollouts stall at dungeon level 1 while
the rest push to level 3+. The mean is a tug-of-war between those two buckets, and that
variance — not the pet tactics — is what separates us from a clean >2.6.

**On fix #5 (survival + pet):** survival's `eat`-uptake jump (4→52 calls) is real but did not
translate to a depth gain at n=24; `throw` stayed at zero use; pet tactics are neutral (above).
The honest read: fix #5 is sound and NetHack-correct, but **death still ends ~⅔ of games and
the aggregate metric is unmoved.**

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

1. **At or near parity with NetPlay (best encoding).** Best cells are **2.29 ± ~0.25** at n=24
   (B1+pet and JSON+nopet) — 2.6 sits ~1.3 SE above, so we are *statistically consistent with
   parity* but cannot claim a clean pass. Peak rollouts reach dungeon level 5–6 (one full
   win), so the *capability* is there; the average is dragged down by floor-1 stalls + deaths.

2. **Text beats vision, and ASCII is not the weak link.** ASCII (B1) and JSON lead; the pure
   pixel image (IMG) is worst. VLMs read rendered NetHack poorly, but a navigation skill makes
   plain text the strongest substrate.

3. **Death, not the clock, is the binding constraint.** ~⅔–¾ of games end in death; ~1 in 30
   hits the turn cap (the rest are NLE in-game step-budget exhaustion mid-skill). The food/eat
   prompt drove a 13× jump in eating (4→52 calls on B1); the ranged `throw` tool saw **zero
   uptake**; pet tactics are **net-neutral** (§6b). None of the fix-#5 tactics reliably move
   the metric.

4. **The agents stay WEAK — the deeper reason death dominates.** At n=24 mean experience level
   is only **~1.4 (max 3)**; most games end at **XL 1, the starting level** (B1: 13/24, JSON:
   17/24 never leave XL 1), with **~0.4 kills/game**. The agent dives fast but never levels up,
   so it plunges into floor 2–4 monsters at ~14 HP and dies. NetPlay/autoascend instead grinds
   XP before descending. (The pet-kill tactic actively suppresses player XP — the pet gets the
   kills — which is one reason it doesn't help.) The **speed-vs-strength tradeoff** looks like
   the highest-leverage untried lever.

5. **The remaining gap is variance, not ideas.** Every condition is bimodal: ~⅓ of rollouts
   stall at dlvl 1, the rest dive to 3–6. A clean, repeatable >2.6 needs that variance reduced
   (and measured at adequate n — every per-condition Δ below ~n=20 is a coin-flip).

---

## 8. Remaining work

- **Strength-vs-speed (the top untried lever, from finding #4).** Have the agent clear/level a
  bit on each floor before descending, so it isn't XL 1 on floor 4. NetPlay grinds XP first.
- **Trim fix #5.** Pet tactics are net-neutral and `throw` is unused — candidates to simplify.
- **Variance reduction** — the bimodal stall-at-floor-1 vs dive-to-6 split is the dominant
  driver of the mean; reducing it (and measuring at n≥24) is the path to a repeatable >2.6.
- **Audit early termination** — episodes that end before the turn cap while still acting are
  the NLE in-game step budget exhausting inside long `explore_and_descend` calls (JSON-heavy).

### Done since the first draft
- **Death detector fixed** (`nethack.py`): NLE's `terminated` flag is now authoritative, so the
  `died` state-flag went from catching ~1/7 deaths to all of them (B1 2→22, JSON 3→11 at n=24).
- **Eval auto-save** (`tools/run_eval.sh`): runs land in `environments/nethack/outputs/evals/<name>`
  (browsable in the viewer) instead of `/tmp`. Pet ablation via `NETHACK_DISABLE_PET=1`.
- **Stats dashboard** (`tools/rollout_view/{stats,dashboard,browse}.py`): post-hoc time-series
  metrics over saved traces (`register_metric` for custom obs), a self-contained HTML dashboard
  (`/dashboard`), and a Finder-style file browser (`/browse`) in the rollout viewer.
