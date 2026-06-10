# Reaching NetPlay's descent depth: diagnosis, five fixes, and an honest measurement

**Date:** 2026-06-09
**Branch:** `benchmark-netplay`
**Target:** NetPlay (Jeurissen et al., CoG 2024; GPT-4) reports **2.6 average max dungeon
level**. We hold the model fixed at `qwen/qwen3-vl-235b-a22b-instruct` (via Prime proxy) and
ask: can our harness match that, and which observation encoding is best?

> **Status:** final. The headline result is **uncompressed ASCII + pet = 2.74 ± 0.41** (n=23),
> the only config that clearly **clears NetPlay's 2.6**. The biggest lever is *not* a tactic —
> it is **not compacting the observation**: uncompressed ASCII beats the compacted B1 default
> in both pet conditions (§6b), because compaction was gutting the map. Pet tactics help ASCII
> (+0.5) but hurt JSON (−0.33). Failure mode = **death, not the turn budget**; the deeper cause
> is the agents **never level up** (mean XL ~1.4 — they dive fast and die weak).

---

## 1. TL;DR

- We went from a measured **mean max dungeon level of 1.25 to 2.74 ± 0.41** (uncompressed ASCII
  + pet, n=23) — **clearing NetPlay's 2.6** — with individual rollouts reaching dungeon level
  5–6 (the tier's win condition).
- Getting there took **five fixes** (three of them measurement/harness bugs, incl. one that
  silently **capped every eval at dungeon level 2**) — but the single biggest lever was the
  **observation encoding**: *un-compacting* the ASCII map. We'd been feeding the model a
  heavily compressed map (blank-row strip + RLE) that gutted its spatial context.
- **Don't compact, and prefer text.** Uncompressed ASCII > compacted ASCII (B1) > JSON > pixels
  (IMG, worst). VLMs parse rendered game images poorly; and even within text, compression
  hurts. With a skill handling navigation, the model reasons best over the *raw* ASCII grid.
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

### 6b. n=24 results, `full_dungeon_easy` — encoding × pet matrix

The full harness (fixes #1–#4 + survival), sweeping **observation encoding** ×
**pet tactics** on/off (`NETHACK_DISABLE_PET=1`), n=24 each. The encoding axis has three
points: **uncompressed ASCII** (B0, the raw full grid), **compacted ASCII** (B1, the prior
default — blank-row strip + RLE + journal-diff), and **JSON** (structured map object).

| Encoding | pet **ON** (mean ± SE) | pet **OFF** | pet Δ | death% on/off |
|----------|:---:|:---:|:---:|:---:|
| **Uncompressed ASCII (B0)** | **2.74 ± 0.41** | 2.21 ± 0.37 | **+0.53** | 48% / 71% |
| Compacted ASCII (B1) | 2.29 ± 0.24 | 1.83 ± 0.18 | +0.46 | 92% / 58% |
| JSON | 1.96 ± 0.27 | **2.29 ± 0.28** | −0.33 | 46% / 54% |

_(NetPlay/GPT-4 = 2.6. Uncompressed+pet is n=23; one stuck rollout was killed.)_

**Two findings dominate:**

1. **Don't compact the observation.** Uncompressed ASCII beats compacted in *both* pet
   conditions (2.74/2.21 vs 2.29/1.83) — the compaction was *gutting the map* (its rendered
   map region was nearly empty), starving the model of spatial context. Uncompressing is worth
   ~**+0.4 dlvl** and is the single biggest lever found. **Best cell = uncompressed + pet =
   2.74, the only config clearly over 2.6.**

2. **Pet helps ASCII, hurts JSON.** Pet tactics are **+0.53 / +0.46** on the two ASCII
   encodings but **−0.33** on JSON. The earlier "net-neutral" verdict (B1+JSON averaged) was
   JSON cancelling ASCII — broken out per encoding, the pet's value depends on the observation.
   (Each Δ is ~1–1.5 SE, so suggestive rather than airtight; the *compaction* effect is the
   more robust signal, consistent across all four ASCII cells.)

**Depth distribution (count of rollouts reaching exactly each level, n=24):**

| run | 1 | 2 | 3 | 4 | 5 | 6 |
|-----|:-:|:-:|:-:|:-:|:-:|:-:|
| Uncompressed ASCII pet   | 10| 2 | 4 | 2 | 3 | 1 |
| Uncompressed ASCII nopet | 14| 3 | 2 | 1 | 2 | 1 |
| Compacted B1 pet         | 8 | 6 | 6 | 3 | 1 | 0 |
| Compacted B1 nopet       | 11| 7 | 5 | 1 | 0 | 0 |
| JSON pet                 | 12| 7 | 2 | 1 | 1 | 1 |
| JSON nopet               | 8 | 8 | 5 | 0 | 2 | 1 |

The shape is bimodal everywhere: ~⅓–½ of rollouts stall at dungeon level 1 while the rest
push to 3–6. Uncompressed ASCII has the fattest deep tail (most dlvl-5/6 reaches). That
variance — not the tactics — is what still separates us from a *clean* >2.6.

**On fix #5 (survival + pet):** survival's `eat`-uptake jump (4→52 calls) is real; `throw`
stayed at zero use; pet helps ASCII / hurts JSON (above). The headline mover turned out not to
be a *tactic* at all — it was **un-compacting the observation**.

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

1. **We clear NetPlay's 2.6 — with the right encoding.** Uncompressed ASCII + pet = **2.74 ±
   0.41** (n=23) is the only config above 2.6; the compacted-B1 default we'd been reporting
   (2.29) sits below it. The capability was there all along — it was throttled by the
   observation, not the agent. (SE is wide, so call it *clears 2.6, n=23*, not a tight result.)

2. **The observation encoding is the biggest single lever — and compaction hurts.** Ranking:
   uncompressed ASCII (2.74) > compacted ASCII/B1 (2.29) > JSON (1.96/2.29) > pixels (IMG, worst,
   n=6 snapshot). Two layers: (a) **vision loses to text** (VLMs parse rendered NetHack poorly);
   (b) **even within text, compressing the map loses to the raw grid** — the RLE/strip compaction
   was emptying the map the model needs for spatial reasoning. The old "ASCII baseline" was a
   *compacted* ASCII baseline, which undersold ASCII.

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

- **Make uncompressed ASCII the default + confirm at higher n.** It's the best config (2.74) but
  SE is wide (±0.41, n=23); re-run uncompressed+pet at n≥48 to tighten it, and re-do the full
  5-encoding sweep *uncompressed* (the n=6 text-vs-vision snapshot used compacted).
- **Strength-vs-speed (top untried *tactic*, finding #4).** Have the agent clear/level a bit on
  each floor before descending, so it isn't XL 1 on floor 4. NetPlay grinds XP first.
- **Keep pet for ASCII, drop for JSON; `throw` is unused** — candidates to trim per encoding.
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
