# AGENTS.md

Project: nethack-rl — training-grade NetHack environment for LM agents,
shipped as `jonathanliu/nethack` on the Prime Intellect Hub.

## Where to start

1. **`WAKE_UP.md`** — current state + first-5-minutes paste-ready commands.
2. **`SESSION_SUMMARY.md`** — full writeup of what's shipped.
3. **`README.md`** — overview + file map.
4. **`docs/EVAL_RECIPES.md`** — vf-eval / prime-eval reference.
5. **`docs/HUB_VERSIONS.md`** — what each Hub release fixed.
6. **`docs/onboarding/`** — 14 walkthrough docs, one per shipped fix.

## Critical conventions

- **uv workspace install is non-editable.** After editing `nethack_core/` or
  `environments/nethack/`, run `uv sync --extra dev --all-packages
  --reinstall-package nethack --reinstall-package nethack-core` before
  pytest, otherwise pytest imports the stale installed copy. See
  [feedback memory](/Users/Fritz/.claude/projects/-Users-Fritz-Downloads-files/memory/feedback_uv_workspace_non_editable.md).

- **Hub install bundles `nethack_core` into the env directory.** Run
  `python tools/bundle_for_hub.py` before `prime env push`. The bundled
  `environments/nethack/nethack_core/` is a build artifact; the source of
  truth is the workspace-root `nethack_core/`.

- **`nethack_core` never imports `verifiers` or `pufferlib`.** Both
  consumers live in their own files. Don't break this.

- **Verifiers contract is fragile.** The pydantic ToolCall shape changed
  twice between releases. Tests in `tests/test_rollout_simulator.py::
  test_pydantic_*` lock the current contract. If verifiers breaks again,
  add a regression test FIRST, then fix.

## Hub deployment

```bash
python tools/bundle_for_hub.py
cd environments/nethack && prime env push --visibility=PRIVATE --auto-bump
```

Each Hub push triggers 4 integration tests. Track outcomes via:
```bash
prime env status jonathanliu/nethack
```

## Skills/tools to know

The user is Jonathan Lin (jl0796@princeton.edu), an RL residency at Prime
Intellect. The collaborator is Alex Zhang (Recursive Language Models, NetHack
prior work). Project plan lives at:
`/Users/Fritz/.claude/plans/wiggly-dreaming-bengio.md`
