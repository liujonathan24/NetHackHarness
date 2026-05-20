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

**Status:** infra complete; experiments not yet launched.

---
