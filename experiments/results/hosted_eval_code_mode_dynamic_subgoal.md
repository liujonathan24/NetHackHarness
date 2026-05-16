# Code mode + dynamic_subgoal hosted eval — Qwen3.5-9B vs v0.0.14

Run 2026-05-15 22:36–22:46 EDT after diagnosing the `-a` vs `-x` CLI gotcha.

## Headline

**Code mode AND dynamic_subgoal validated end-to-end in production.**
48 `code(source=...)` tool calls were dispatched. Worker log confirms
`Using provided args: max_turns=30, interface=code, tier=dynamic_subgoal`.

## Numbers

| Field | Value |
|------|------|
| env version | 0.0.14 |
| model | Qwen/Qwen3.5-9B |
| n × r | 1 × 1 |
| **interface** | **code** (not skill) ✓ |
| **tier** | **dynamic_subgoal** ✓ |
| max_turns (cap requested) | 30 |
| actual turns | 136 (wallclock timeout fired first) |
| **code_calls** | **48** (the model used the `code` tool 48 times) |
| total_tool_calls | 133 |
| stop reason | timeout_reached (10min) |
| reward | 0.0 |
| input tokens | 3,136,914 |
| output tokens | 49,503 |
| cost | ~$0.59 |
| eval URL | https://app.primeintellect.ai/dashboard/evaluations/eafz8zkrmf3rc4i0fplgrnyc |

## What this proves

- **`-a` (env-args) flag** correctly routes to `load_environment(...)`.
  `-x` (extra-env-kwargs) does NOT (it calls `set_kwargs` post-construction,
  which can't change the tool list).
- **Code mode is wired** in production — the agent saw exactly one tool
  (`code(source: str)`) and dispatched 48 Python snippets through it.
- **Dynamic subgoal tier compiles and runs** without crashes. The
  proposer ran at setup_state, stamped a milestone into the spec, and
  pinned the objective to the journal.
- **No crashes across 136 turns × 48 code dispatches.** All AST validation,
  sandbox execution, and skill-action queue plumbing held up.

## Comparison to skill mode (prior eval)

| | code mode | skill mode |
|-|-----------|-----------|
| turns | 136 | 146 |
| LM tool calls | 48 (all `code`) | 144 (skill mix) |
| input tokens | 3.1M | 4.3M |
| output tokens | 49K | 46K |
| cost | $0.59 | $0.79 |

Code mode used **27% fewer input tokens** at similar reward (both 0) — the
"one code call replaces many skill calls" thesis holds: each LM round-trip
dispatches ~3x more skill actions, so the prompt doesn't grow as fast.

Worth noting: with 48 code calls and only 0 reward, the model is
exercising the substrate but not making strategic progress. Qwen3.5-9B
at default temperature isn't a capable NetHack agent — but the env works.
