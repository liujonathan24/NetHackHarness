# RLM — Recursive Language Models

A long-horizon agent that drives NetHack through a **code/REPL interface** and
decomposes reasoning by **recursively calling sub-LMs** over chunks of context
(after the Recursive Language Models line of work; cf. the BALROG RLM env).

## Idea
- The top agent doesn't emit one tool call per turn. It writes Python against an
  `nh` namespace (the existing **code-mode**: `nh.move/attack/descend/autoexplore`,
  a queryable `nh.map`, `nh.add_note/recall`, `nh.wiki_lookup`) and plays many
  steps inside one reasoning session.
- When context or sub-problems get large, it calls **sub-LMs** —
  `nh.summarize(slice)`, `nh.plan(objective)`, `nh.recall_lm(query)` — i.e. the
  model recursively invokes itself over a slice/sub-task and uses the result.
  These hooks already exist in code-mode (`SubLM`: `summarize`/`plan`/`recall_lm`).

## Maps onto this repo
- Interface = `interface="code"` (`nethack_harness/tools/code_mode.py`, the `nh`
  namespace + `code(source=...)` tool).
- Recursive calls = a real `SubLM` backend (GLM via Prime Inference) wired into
  `run_user_code(..., sub_lm=...)` instead of the offline stub.
- Knowledge = `nh.wiki_lookup` / `nh.wiki_search` (shared wiki snapshot).
- Memory across the long session = the journal (`nh.add_note`/`nh.recall`) +
  belief-state summaries.

## Status
Scaffold. Planned entry point: `python -m approaches.rlm.rlm` — a code-mode
rollout with a live GLM sub-LM backend, writing an NDJSON trace.
