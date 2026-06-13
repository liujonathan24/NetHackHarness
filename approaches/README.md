# Approaches

Four families of LLM-agent strategy for NetHack, each in its own folder, all
built on the **same shared core** and a common knowledge source — so they can be
compared apples-to-apples.

## Shared core (not duplicated per approach)
- **Engine + env** — `nethack_core/` (ctypes binding over the NetHack fork) and
  `environments/nethack/` (the verifiers `NetHackVerifiersEnv`, observations,
  skills, curriculum). The game engine is **frozen**; approaches only change the
  *harness* around it.
- **Skills** — `environments/nethack/nethack_harness/tools/skills.py` (move,
  attack, search, descend, `explore_and_descend`, …).
- **Knowledge source** — `wiki/` + `tools/build_wiki_index.py` + the
  `wiki_lookup` / `wiki_search` skills. **All approaches read from this wiki
  snapshot** for game knowledge (monsters, items, strategy).
- **Viewer** — `tools/rollout_view/` renders any approach's NDJSON traces.

## The approaches

| folder | idea | status |
|--------|------|--------|
| [`continuous_harness/`](continuous_harness/) | **Continual / self-improving harness.** A champion-vs-challenger loop where an LLM edits the harness's own *tooling and observation code* in isolated git worktrees, test-gated and depth-scored; engine frozen. (Primary; also includes the in-rollout teacher *refiner*.) | **implemented** |
| [`go_explore/`](go_explore/) | **Go-Explore.** Archive promising states and *return to them* to explore further, using the engine's in-memory `snapshot`/`restore`/`branch` API. `core.py` is the Monte-Carlo lookahead/branch primitive. | primitive implemented; driver next |
| [`voyager/`](voyager/) | **Voyager.** An automatic curriculum + a growing *skill library*: propose the next objective, write/compose a skill to achieve it (grounded in the wiki), verify, and keep it for reuse. | scaffold |
| [`rlm/`](rlm/) | **Recursive Language Models.** A top agent drives the game through a code/REPL interface and decomposes long-horizon reasoning by recursively calling sub-LMs (summarize / plan / recall) over context chunks. | scaffold |

## Running
Each folder has its own README with the exact command. They all expect the
workspace installed (`uv sync --extra dev --all-packages`) and the engine built
(`bash nethack_core/build_engine.sh`), and write NDJSON traces viewable with
`tools/rollout_view/live_server`.
