# Code mode: Track B (v0.2 — wired)

**Status:** Wired end-to-end as of 2026-05-15 evening.
- `nethack_core/code_mode.py` — sandboxed runtime + namespace + AST validator.
- `nh.move/attack/descend/search/pickup/move_to/autoexplore` now dispatch the
  underlying skill and queue actions in `nh._log`.
- `environments/nethack/nethack.py::env_response` routes `code(source=...)`
  tool calls through `run_user_code` and applies `actions_taken` via the
  same step loop as skill mode.
- `load_environment(interface="code")` swaps the 14 skill tools for a single
  `code` tool. `interface="skill"` (default) keeps the old behaviour.
- Tests: `tests/test_code_mode.py` (15) + `experiments/exp13_code_mode.py`
  (regression: 4 skill calls collapse to 1 code call doing equivalent work).

## Why this matters for Alex

Track B in the plan is "RLM-native code mode as headline interface." The
research story is: NetHack agents that write Python loops calling sub-LMs
for `summarize`, `plan`, `recall` instead of issuing individual tool calls.
This directly applies Alex's Recursive Language Models (arXiv 2512.24601)
to long-horizon embodied agents.

The v0 substrate ships now so the verifiers wiring + sub-LM integration is
a one-week task in Week 2, not a from-scratch design.

## The architecture

```python
@dataclass
class CodeModeResult:
    stdout: str
    error: Optional[str] = None
    actions_taken: list[int] = field(default_factory=list)

def run_user_code(source, env, structured_obs, journal=None,
                  timeout_seconds=5) -> CodeModeResult: ...
```

Three components:

1. **AST validator** (`validate_source`): rejects imports, dunder access,
   and a denylist of names (`exec`, `eval`, `open`, `__import__`, ...).
   Port of glyphbox's pre-execution check.
2. **Runtime** (`run_user_code`): exec()s in a namespace with `nh`, the
   curated game-state object, plus `Direction` and `Position` helpers, plus
   a hand-picked `__builtins__` subset (no file I/O, no introspection).
3. **SIGALRM cap**: 5s default. Unix-only; on Windows we skip the cap and
   rely on the AST validator to keep things bounded (Windows users get a
   degraded safety story, documented).

## What v0 ships

- `nh.status` / `nh.inventory` / `nh.map_view` / `nh.character` — read-only
  views of the structured observation.
- `nh.add_note(key, text)` / `nh.recall(query)` — journal access (works
  when a Journal is passed to `run_user_code`).
- `nh.wiki_lookup(entity)` — substring index lookup.
- Constants: `Direction.N`, `Direction.NE`, ... and `Position(x, y)`.

## What's wired vs what's still ahead

**Wired (this version):**
- All env-stepping primitives (`nh.move/attack/descend/search/pickup/move_to/autoexplore`)
  go through the same `SkillRegistry` as skill mode and append actions to
  `nh._log`. After `run_user_code` returns, the env steps each action and
  the next observation reflects the full batched effect.
- `nh.add_note/recall/wiki_lookup/wiki_search` (no-step skills, mutate state
  directly).

**Still ahead (Track B v0.3):**
- **Sub-LM tools** (`summarize`, `plan`, `recall_lm`) — pending prime-rl
  inference server access. The RLM-native pieces of Track B.
- **Action queue ordering vs observation staleness** — currently all queued
  actions execute *after* user code returns, so user code can't observe
  intermediate state mid-loop. This is intentional (avoids re-rendering
  the obs, which would burn tokens). For agents that need to react mid-loop,
  the v0.3 plan exposes a `nh.peek_status()` that re-reads blstats only.

## Example: what the agent could write today

```python
# inspect inventory before deciding strategy
hp = nh.status["hitpoints"]
max_hp = nh.status["max_hitpoints"]

if hp < max_hp * 0.5:
    nh.add_note("strategy", "low HP, prioritize healing potions")
    p = nh.wiki_lookup("altar")
    if p:
        print("altar lore:", p.short(200))
else:
    nh.add_note("strategy", "healthy, push for stairs")
```

This is one tool call that does 4 things. The corresponding skill-mode
trace would be: `status_check` → `recall` (or 4 separate `add_note` + 1
`wiki_lookup`). Code mode is ~3× token-efficient for compositional
reasoning.

## What's safe and what isn't

**Safe (validator blocks):**
- `import os`, `from sys import argv`
- `exec("...")`, `eval("...")`, `compile("...")`
- `().__class__`, `__builtins__`, `__import__`

**Safe (namespace doesn't expose):**
- `open()`, file I/O, network, subprocess

**NOT safe (yet, but planned):**
- Infinite loops without an inner I/O call. SIGALRM catches infinite
  pure-Python loops up to 5s, but on Windows we currently can't enforce.
  Future: thread + watchdog timer.
- Resource exhaustion (huge list comprehensions). Not validated; would
  crash the python process. Future: memory cap via `resource.setrlimit`.

For non-adversarial agents (which is all we have), this is fine. If we
ever serve untrusted code, layer a real sandbox (Docker, gVisor, ...) on
top.

## How to verify

```bash
uv run pytest tests/test_code_mode.py -v
```

11 tests cover validator rejections (imports, dunder, forbidden names),
runtime behavior (stdout capture, exception capture), namespace exposure
(status/inventory/character/wiki/journal), and the builtins denylist.

## Future work

The Week-2 plan in the project plan covers the wiring:

1. **Action queue + flush.** `nh.move()` / `nh.attack()` append to an
   internal list; `run_user_code` returns them in `actions_taken`; the
   verifiers env applies them post-execution. Same loop semantics as the
   skill-mode dispatch.
2. **Sub-LM tools.** `nh.summarize(slice, query)` routes through prime-rl's
   inference server. The "RLM" half of Track B.
3. **`interface="code"` switch.** Make code-mode the default in
   `load_environment(interface="code")` once Alex green-lights, with
   `interface="skill"` preserved as a comparability flag.
4. **Belief-state distillation.** Automatic `nh.summarize` call at chapter
   boundaries (level transitions) that replaces stale context.
