# Experiment log

Running notes on observation/skill-structure variants and harness infra.
One section per wave. Newer entries on top.

---

## Wave 1 — obs/skill-structure variants (2026-05-20 → in progress)

**Goal:** identify the best observation set/harness for our NetHack agent
given the working hypothesis that compaction is currently load-bearing for
both (a) staying within context and (b) keeping the LLM's attention on
signal. Compare paper-attributed baselines against the current default.

**Metric:** mean max-Dlvl reached over seeds 22–26 (5 seeds, preliminary
stage), 200-move budget. Side-metric: tokens/turn (≤1.5× B1 acceptable).
Primary model: Qwen3.5-9B. Top-3 winners promoted to Haiku stage on seeds
22–24 (3 seeds). The seed-count was deliberately cut (originally planned
for 20 + 5) to control wall-clock and inference cost; 5 seeds is
preliminary — high-confidence wins still need a follow-up wider sweep.

**Hub publish:** `jonathanliu/nethack@0.0.64` (2026-05-20). Required
because hosted eval pins the latest published version, not local code.

**Variants** (each a single `load_environment(variant=..., ...)` setting):

| code | source | what it changes |
|------|--------|-----------------|
| B0   | calibration | All compaction off — raw v0.0.15-era rendering. Establishes whether current compaction helps or hurts capability. Runs once. |
| B1   | current default | Standing baseline every other variant must beat. |
| G    | Glyphbox (Wang, 2026) | ASCII + adjacency + hostile-list + code-mode tool surface. |
| B    | BALROG (Paglieri et al., ICLR 2025) | No ASCII grid; natural-language scene description only. |
| N    | NetPlay (Jeurissen, CoG 2024) | Skill-only action surface (no `move(direction=…)` primitive). |
| R    | CPP/GPP summarize-and-reset | Belief state every 25 turns + hard-drop everything before last checkpoint. |
| P    | Continual Harness (arXiv:2605.09998) | Every 20 turns, inject a self-refinement directive prompting the agent to update its journal objective / record a lesson. |

**Decision rules:**

- Promote a variant when mean max-Dlvl > B1 with |Welch-t| ≥ 2 AND tokens/turn ≤ 1.5× B1.
- Wave-2 (informed) launches after top-3 are picked.
- Reject variants exceeding the token cap regardless of capability win — efficiency is a hard constraint.

**Infra changes shipped this wave** (commit checkpoints below):

- `environments/nethack/nethack.py`:
  - `variant` kwarg (`B0`/`B1`/`G`/`B`/`N`/`R`/`P`) selecting per-turn formatter.
  - `_format_obs_balrog` (variant B), `_format_obs_glyphbox` (G), `_format_obs_summarize_reset` (R).
  - `summarize_and_reset` kwarg + `_drop_before_last_belief` (variant R history pruning).
  - `continual` + `continual_lives` kwargs + `_continual_reset` for cross-episode play with persistent journal/belief state.
  - `trace_dir` kwarg + `_write_trace_entry` writing per-turn NDJSON (raw grid + structured obs + rendered_user_message + assistant_message + tool_calls + action + reward).
  - Variant P refinement directive already landed (see commit 77da8b4).
- `experiments/exp16_obs_variants.py` — matrix launcher: variant × model × seed, tagged `wave1/<variant>/<model>/seed<N>`, resumable, `--hosted`/`--dry-run`/`--local` modes.
- `tools/compare_evals.py` — tagged aggregation (`--tag wave1`) emitting `experiments/results/wave1_summary.md`: mean max-Dlvl ± SEM per variant, Welch-t vs B1, tokens/turn ratio, top-3 promotion list.

**Open questions / followups:**

- Hosted artifact flow: confirm `prime eval run --hosted` preserves env-written NDJSON under `trace_dir`. If not, fall back to local re-run of top-3 for trace fidelity.
- Variant R: the belief-state interval (25) was tuned for B1; may need to be retuned when chat history is hard-dropped.
- Variant P: the subagent flagged that the refine_interval=20 cadence is a guess; sweep 10/20/50 once primary results land.

**Status:** infra complete; matrix launched 2026-05-20; analysis at
`experiments/results/wave1_summary.md`.

### Wave-1 headline (5-seed preliminary, Qwen3.5-9B)

| variant | mean avg_score | n | one-liner |
|---|---|---|---|
| N (NetPlay skill-only) | **1.137** | 4 | High mean but bimodal — 2 outlier seeds drive it. Needs n=20 to confirm. |
| R (summarize-and-reset) | 0.111 | 4 | Capability parity with B1; cheaper history footprint. Ship-if-it-ties. |
| P (Continual Harness directive) | 0.103 | 3 | Indistinguishable from B1. Try max_turns=500 next. |
| B0 (no compaction) | 0.102 | 3 | Ties B1 — compaction is a token lever, not a capability lever. |
| G (Glyphbox + code-mode) | 0.095 | 1 | Underdetermined; 4 stuck >2h. Perf bug. |
| B1 (current default) | 0.082 | 4 | Baseline. |
| B (BALROG no-ASCII) | **0.056** | 5 | Dead. Stripping ASCII grid breaks the agent. d=−0.92 vs B1. |

Plots: `wave1_box.png`, `wave1_box_logy.png`, `wave1_cohens_d.png`.

**Verdict:** the ASCII grid is load-bearing (B kills capability). N is
the only variant with a positive directional signal, but high variance.
Compaction's role is cost, not capability, at 200 turns.

**Correction (2026-05-20, post-samples-pull):** `avg_score` is the
UNWEIGHTED reward-fn sum, not the rubric-weighted total. With proper
decomposition (`prime eval samples`):

- N seed 22: scout=0.155, descent=1, **success=1** → reward 2.155
- N seed 23: scout=0.257, descent=1, **success=1** → reward 2.257
- B1 seed 22, 24: all pure scout, zero descents/successes.

**N actually solved the corridor_explore milestone on 2/4 completed seeds.
B1 solved 0/4.** That's a 50% vs 0% success rate, not "small effect" —
the high mean and high variance are explained by N either succeeding
or failing entirely. Plots: `wave1_decomp_v2.png`, `wave1_success_rate.png`.

**Side-by-side gameplay videos** (rendered via
`tools/render_rollout_video.py` against `prime eval samples`):

- `videos/N22_vs_B1_22.gif`  same-seed head-to-head (both seed 22)
- `videos/N23_vs_B1_24.gif`  best-N vs best-B1

The videos show the actual ASCII map + status + tool call per turn.

**Followups:**
- Wider sweep on N (n=20) to nail its floor.
- Fix Anthropic-key wiring on Prime hosted runner — Haiku stage 12/12 FAILED.
- Profile `nethack_core.code_mode.run_user_code` — G rollouts taking >2h.
- Re-run P at max_turns=500 to test whether the refinement directive
  needs longer horizon to amortize.
- Wave-2 combo candidate: N+R (skill-only + history-reset).

---

# Wave-2: descent reliability (2026-05-28)

Goal: make dlvl-2 + success (`corridor_explore`) reliable, not lucky.

## Diagnosis (from real pulled rollouts)

Pulled per-turn samples for the descended N runs and the failures
(`prime eval samples`, decomposed the 4 reward fields). Findings:

| run | eval_id | score | descent | success | LM turns | game-T | outcome |
|-----|---------|-------|---------|---------|----------|--------|---------|
| N s22 | cz7wjzq818ckwdi1xdpksnoy | 2.155 | 1 | 1 | 61 | 63 | descended |
| N s23 | kpdsywnfm7vzqxcxvtw2kgkq | 2.257 | 1 | 1 | 53 | 54 | descended |
| N s26 | rsh5i07hwqajfe8avlqp99u1 | 0.097 | 0 | 0 | 133 | 309 | killed by newt |
| N s25 | fikki61ohiwxcoc3tifkm4fo | 0.039 | 0 | 0 | — | 1921 | starved (Fainting) |
| B1 s22 | p3s6kuijz0dwjlz21m8cxxo6 | 0.048 | 0 | 0 | 297 | 1522 | starved (Fainting) |
| B1 s23 | cwk591png0ex0i729b3jvjve | 0.054 | 0 | 0 | 165 | 629 | killed by kobold zombie |
| B1 s24 | nokl8nw88oatwao3fz0cjbfb | 0.115 | 0 | 0 | 183 | 568 | killed by fox |
| B1 s26 | esx38vdrxwu659zpwoslknwc | 0.109 | 0 | 0 | — | 1486 | starved |
| Haiku s22 | vwgp2g00lj2wx573384ol85p | 0.289 | 0 | 0 | 407 | 868 | killed kicking a wall |

**The failure mode is (a) never revealing/reaching `>`, then dying — almost
always by starvation (Fainting/Weak) or a weak monster while wandering.**
Concrete evidence: in EVERY failing rollout, `stairs DOWN` NEVER appears in
the `VISIBLE FEATURES` block (parsed per-turn) — the agents never even SEE
the down-stairs. Successful runs descend in <65 game-turns; every run that
passed ~300 game-turns died on dlvl-1. Time-on-level is the killer.

Mechanism (feedback histogram of failing runs): agents oscillate around
1–2 doorways/frontiers near the starting room — repeated "pathing to door
at (X,Y)", "Already at (X,Y)", and `search`/`pickup` loops — and never push
through to reveal the rest of the level. Nobody was confused about `<` vs
`>`; nobody failed to step onto known stairs. It's purely an exploration
+ survival-time problem.

**Harness bug found while stress-testing:** a scripted `find_and_descend`
loop on seed 22 froze permanently at one tile with the in-game clock stuck
(T:51 for 90+ calls). `find_and_descend`/`autoexplore` repeatedly choose a
1-step "far frontier" whose only unexplored neighbor is solid rock — a
*false frontier* — so the step is a no-op and no new tiles are revealed.
Real LM rollouts hit the same wedge and burn their whole budget on it.

## Fixes shipped (env v0.0.65)

1. **Deadlock-breaker (all variants, `nethack.py:env_response`).** Track the
   in-game clock + scout-delta after each exploration/move skill. If the
   clock is frozen AND no new tiles revealed for 2 consecutive calls, the
   harness auto-acts: kick an adjacent closed door `+` if present, else
   force an escalating `search(10–30x)` in place to reveal a hidden passage.
   This unwedges the false-frontier loop (verified: scripted loop now keeps
   advancing 66→67→68→71 instead of freezing at one tile).
2. **Descent-salience obs block (variants ND/FD).** A persistent
   `=== DESCENT STATUS ===` block at the top of every obs: either
   "DOWNSTAIRS: VISIBLE at (x,y) — find_and_descend NOW" or "DOWNSTAIRS:
   not found yet — find_and_descend to push into unrevealed territory; do
   NOT loop on search/pickup", plus a `CLOCK:` warning once T≥250 game-turns
   ("descend before hunger kills you"). Gated on `_descent_salient`;
   baselines unaffected (verified B1 obs unchanged, all 311 tests pass).
3. **New variants in `exp16_obs_variants.py`:**
   - **ND** = NetPlay skill set (best wave-1 variant, no low-level `move`)
     + descent-salience block. Isolates the obs delta vs N.
   - **FD** = find_and_descend autopilot: tightest skill surface
     (find_and_descend/autoexplore/move_to/descend/attack/search/kick/
     eat/pray/engrave_elbereth, no pickup/wiki — pickup was a turn-sink in
     failing traces) + descent-salience block.

## Validation (hosted Qwen3.5-9B, seeds 22–26, 200 turns) — IN FLIGHT

Launched on env v0.0.65 (Haiku still unavailable on runner → Qwen primary):

| variant | seed22 | seed23 | seed24 | seed25 | seed26 |
|---------|--------|--------|--------|--------|--------|
| ND | m8aujshel4rirw1vz6gr6qwk | zj09rpuhruimzfxd6xhw4no2 | v3h6eo8m4fpf4psvgziysyd4 | c03p4kfdm5zw73yxxo7bnqdq | zf64gmmhte3s6rhz50gf8ro5 |
| FD | a2cmfdj6on6xy7ixrqko4uki | zf443vtheorlpmcg1t0afqcb | xmdfqhn1ufnevarthooxere2 | zp6hgzc7ncplw5l4vat4jwcl | hjmmvlj3nrzcyn3k8x2w576u |
| B1 (control, same code) | a5wrtd06w4byrfmphhnt4s60 | ytnhyaucokdoz0qt4wtluzvv | gmqx5as0q09d7i0jab9ynhx5 | z9gw7fetvb8xxy56ro4rzkup | vbzs9917n8k1ozeokl4xj0sp |

Pull with `tools/render_rollout_video.load_hosted` or
`prime eval samples <id> -o json --plain`; decompose the
scout/descent/success/ascension fields. Target metric: fraction of seeds
with descent≥1 AND success==1.

---
