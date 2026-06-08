---
change: pysc2-interface
design-doc: docs/superpowers/specs/2026-06-07-pysc2-interface-design.md
base-ref: 54a7238ce0d611de274e43dcb975b0788fd1fcdc
---

# pysc2-interface + rollout views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A typed `nethack_interface` package (RL-ready ObservationSpec/ActionSpec/Env wrapper) + a shared HTML rollout-view layer serving a replay viewer and a live rollout stepper.

**Architecture:** `nethack_interface` wraps `nethack_core` with a flat typed `Observation` (from `build_map_model`), an `ActionSpec` derived from the `SkillRegistry` schemas, and a `NetHackInterface.step/reset` that executes typed actions via `skills.call` (parity) + raw via `env.step`. A shared `rollout_view` HTML core (`render_turn`/`render_run`) is used by a static replay export (over the encoding-eval `REPLAY_LOG_KEYS` seam) and a localhost live stepper (manual + model modes).

**Tech Stack:** Python, pytest. Reuses `nethack_core` (map_model/observations/env), `nethack_harness.tools.skills`, the encoding-eval trace seam, `tools/launchpad`. Live server: stdlib `http.server` (no new deps).

---

## Environment & test invocation (read first)

- On the build-isolation branch off `main`. Tests: `cd environments/nethack && python -m pytest ../../tests/<file> -p no:cacheprovider -q --no-header`. New tests in repo-root `tests/`.
- `nethack_interface` is a NEW repo-root package (importable as `nethack_interface`); `tools/` is importable as `tools.*`. Add `nethack_interface` to `[tool.uv.workspace] members` in repo-root `pyproject.toml`.
- **Known baseline:** 7 pre-existing failures (test_rewards/test_integration pollution). New tests pass in isolation; full-suite failures ⊆ those 7.
- **Commit path-scoped.** Build order: interface (Tasks 1–4) → HTML core + replay (Task 5) → live stepper (Task 6) → verify (Task 7).

## Grounded facts

- `nethack_core.map_model.build_map_model(raw_obs) -> MapModel` (player, entities[Entity{kind,x,y,description,species,is_pet,obj_class,detail}], grid). `observations.StructuredObservation` (status, inventory, character, ...). `env.NetHackCoreEnv`: `reset()`, `step(action:int)->(CoreObservation, reward, term, trunc, info)`, `action_space`.
- `nethack_harness.tools.skills`: `registry` (a `SkillRegistry`) with `_schemas: {name: schema_dict}` and `call(name, env, obs, **kwargs) -> SkillResult{actions: list[int], feedback: str, interrupted, ...}`.
- Encoding-eval seam: `tools/encoding_eval/replay.py` `REPLAY_LOG_KEYS`; per-turn NDJSON trace has `rendered_user_content` (str | `[{type:image_url,image_url:{path}}, {type:text,text}]`), `raw_grid`, and a sibling `images/` dir.

## File structure

- Create: `nethack_interface/{pyproject.toml, __init__.py, observation.py, actions.py, env.py}`
- Create: `tools/rollout_view/{__init__.py, html.py, replay_export.py, live_server.py}`
- Modify: repo-root `pyproject.toml` (workspace member), `tools/launchpad` (open-HTML affordance — minimal)
- Tests: `tests/test_interface_observation.py`, `tests/test_interface_actions.py`, `tests/test_interface_env.py`, `tests/test_rollout_view_html.py`, `tests/test_live_stepper.py`

---

## Task 1: nethack_interface package scaffold

**Files:** Create `nethack_interface/pyproject.toml`, `nethack_interface/__init__.py`; Modify repo-root `pyproject.toml`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interface_import.py
def test_package_imports():
    import nethack_interface
    assert hasattr(nethack_interface, "__version__")
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError: nethack_interface`).

- [ ] **Step 3: Implement**

`nethack_interface/__init__.py`:
```python
"""Typed PySC2-style interface to NetHack over nethack_core (RL-ready)."""
__version__ = "0.0.1"

from nethack_interface.observation import Observation, observation_spec  # noqa: E402
from nethack_interface.actions import Action, RawAction, action_spec     # noqa: E402
from nethack_interface.env import NetHackInterface                        # noqa: E402

__all__ = ["Observation", "observation_spec", "Action", "RawAction",
           "action_spec", "NetHackInterface"]
```
`nethack_interface/pyproject.toml`:
```toml
[project]
name = "nethack-interface"
version = "0.0.1"
description = "Typed PySC2-style interface to NetHack over nethack_core."
requires-python = ">=3.10,<3.14"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["."]
```
Repo-root `pyproject.toml`: add `"nethack_interface"` to `[tool.uv.workspace] members`.

> NOTE: the `__init__` imports observation/actions/env which don't exist until Tasks 2–4. For THIS task, make `__init__.py` only `__version__ = "0.0.1"` and add the re-exports incrementally as Tasks 2–4 land (or guard with try/except). Keep Task-1 import test green.

- [ ] **Step 4: Run → PASS.** `cd environments/nethack && python -c "import nethack_interface; print(nethack_interface.__version__)"` → `0.0.1`.

- [ ] **Step 5: Commit** `nethack_interface/pyproject.toml nethack_interface/__init__.py pyproject.toml tests/test_interface_import.py` — `feat(interface): nethack_interface package scaffold`.

---

## Task 2: Typed Observation + spec

**Files:** Create `nethack_interface/observation.py`; Test `tests/test_interface_observation.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_interface_observation.py
import numpy as np, nle.nethack as N
from nethack_interface.observation import Observation, observation_spec


class _Raw:
    def __init__(self):
        g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32); g[5,10] = N.GLYPH_MON_OFF+20
        self.glyphs=g; self.tty_chars=np.full((24,80),32,np.uint8)
        b=np.zeros((27,),np.int64); b[0]=40; b[1]=10; self.blstats=b


def test_observation_from_raw_carries_map_and_status():
    obs = Observation.from_raw(_Raw(), status={"hitpoints": 12, "depth": 1},
                               inventory=[], character={"role": "Val"})
    assert obs.player == (40, 10)
    assert any(e.kind == "monster" for e in obs.entities)
    assert obs.status["hitpoints"] == 12


def test_observation_spec_declares_fields():
    spec = observation_spec()
    assert {"player", "entities", "grid", "status", "inventory", "character"} <= set(spec)
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
# nethack_interface/observation.py
"""Typed structured observation (flat feature-layer dataclass) + its schema."""
from __future__ import annotations
from dataclasses import dataclass, fields
from typing import Any, Optional


@dataclass
class Observation:
    player: Optional[tuple]   # (x, y)
    entities: list            # nethack_core.map_model.Entity
    grid: str                 # RLE topology
    status: dict
    inventory: list
    character: dict

    @classmethod
    def from_raw(cls, raw_obs, *, status, inventory, character):
        from nethack_core.map_model import build_map_model
        m = build_map_model(raw_obs)
        return cls(player=m.player, entities=m.entities, grid=m.grid,
                   status=dict(status or {}), inventory=list(inventory or []),
                   character=dict(character or {}))


def observation_spec() -> dict:
    """Declared schema: field name -> type name (dataclass introspection)."""
    return {f.name: (f.type if isinstance(f.type, str) else getattr(f.type, "__name__", str(f.type)))
            for f in fields(Observation)}
```

- [ ] **Step 4: Run → PASS** (2 passed).
- [ ] **Step 5: Commit** `nethack_interface/observation.py tests/test_interface_observation.py` — `feat(interface): typed Observation + spec`.

---

## Task 3: ActionSpec (from registry) + raw escape hatch

**Files:** Create `nethack_interface/actions.py`; Test `tests/test_interface_actions.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_interface_actions.py
from nethack_interface.actions import Action, RawAction, action_spec


def test_action_spec_derives_core_actions_from_registry():
    spec = action_spec()
    # core actions present, each with an arg schema sourced from the registry
    for name in ("move", "move_to"):
        assert name in spec
    assert isinstance(spec["move_to"], dict)  # the registry schema


def test_typed_action_and_raw_action():
    a = Action("move_to", {"x": 5, "y": 9})
    assert a.name == "move_to" and a.args == {"x": 5, "y": 9}
    r = RawAction(12)
    assert r.index == 12
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
# nethack_interface/actions.py
"""Typed action set derived from the SkillRegistry (single source of truth)
plus a raw NLE action-index escape hatch."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Action:
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class RawAction:
    index: int


def action_spec() -> dict:
    """name -> arg schema, sourced from the live skill registry (no drift)."""
    from nethack_harness.tools.skills import registry
    return dict(registry._schemas)
```

- [ ] **Step 4: Run → PASS** (2 passed). If the import path of `registry`/`_schemas` differs, read `nethack_harness/tools/skills.py` and adapt — keep the test intent (spec sourced from the registry).
- [ ] **Step 5: Commit** `nethack_interface/actions.py tests/test_interface_actions.py` — `feat(interface): ActionSpec from skill registry + raw escape hatch`.

---

## Task 4: NetHackInterface env wrapper

**Files:** Create `nethack_interface/env.py`; Test `tests/test_interface_env.py`.

- [ ] **Step 1: Failing test** — drive a tiny real env (the existing tests construct `NetHackCoreEnv`; reuse that pattern). Assert `reset()` returns an `Observation`, and `step(Action("search"))` returns `(Observation, float, bool, dict)` and that a `RawAction` also steps. (Read `tests/test_skills.py` / `test_integration.py` for the env-construction + obs-shaping helpers — reuse them; do not invent a new env fixture.)

```python
# tests/test_interface_env.py  (skeleton; fill the env fixture from existing tests)
from nethack_interface import NetHackInterface, Observation, Action, RawAction

def test_reset_and_step(make_core_env):           # fixture built from existing tests
    iface = NetHackInterface(make_core_env())
    obs = iface.reset()
    assert isinstance(obs, Observation)
    obs2, reward, done, info = iface.step(Action("search"))
    assert isinstance(obs2, Observation) and isinstance(reward, float) and isinstance(done, bool)
    obs3, *_ = iface.step(RawAction(0))            # raw escape hatch steps too
    assert isinstance(obs3, Observation)
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

```python
# nethack_interface/env.py
"""Thin typed wrapper over NetHackCoreEnv. Typed actions execute via the existing
skill dispatch (behavioral parity with the harness); RawAction via env.step(int)."""
from __future__ import annotations
from nethack_interface.observation import Observation
from nethack_interface.actions import Action, RawAction


class NetHackInterface:
    def __init__(self, core_env, character=None):
        self._env = core_env
        self._character = character or {}
        self._raw = None
        self._structured = None

    def _shape(self):
        from nethack_core.observations import shape as shape_observation
        self._structured = shape_observation(self._raw, self._character)
        return Observation.from_raw(
            self._raw, status=self._structured.status,
            inventory=self._structured.inventory, character=self._structured.character)

    def reset(self) -> Observation:
        out = self._env.reset()
        self._raw = out[0] if isinstance(out, tuple) else out
        return self._shape()

    def step(self, action):
        if isinstance(action, RawAction):
            self._raw, reward, term, trunc, info = self._env.step(action.index)
            return self._shape(), float(reward), bool(term or trunc), info
        if isinstance(action, Action):
            from nethack_harness.tools.skills import registry
            res = registry.call(action.name, self._env, self._structured, **action.args)
            total = 0.0; term = trunc = False; info = {"feedback": res.feedback}
            for idx in res.actions:
                self._raw, r, term, trunc, info2 = self._env.step(idx)
                total += float(r)
                if term or trunc:
                    break
            return self._shape(), total, bool(term or trunc), info
        raise TypeError(f"unknown action: {action!r}")
```

- [ ] **Step 4: Run → PASS.** Then `python -c "import nethack_interface; print('ok')"` (the `__init__` re-exports now resolve).
- [ ] **Step 5: Commit** `nethack_interface/env.py nethack_interface/__init__.py tests/test_interface_env.py` — `feat(interface): NetHackInterface env wrapper (typed step via skill dispatch + raw)`.

---

## Task 5: Shared HTML rollout-view core + replay export

**Files:** Create `tools/rollout_view/{__init__.py, html.py, replay_export.py}`; Test `tests/test_rollout_view_html.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_rollout_view_html.py
import json
from pathlib import Path
from tools.rollout_view.html import render_turn, render_run
from tools.rollout_view.replay_export import export_replay_html


def _turns():
    return [
        {"turn": 0, "raw_grid": ["@.."], "rendered_user_content": "MAP txt"},
        {"turn": 1, "raw_grid": ["..>"],
         "rendered_user_content": [{"type": "image_url", "image_url": {"path": "images/r_1.png"}},
                                   {"type": "text", "text": "STATUS"}]},
    ]


def test_render_turn_two_columns_text_and_image():
    html = render_turn(_turns()[1])
    assert "..>" in html               # game-state column (raw_grid)
    assert "STATUS" in html            # llm text
    assert "images/r_1.png" in html and "<img" in html  # real image embedded


def test_export_replay_html_writes_self_contained_file(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    (run / "r.ndjson").write_text("\n".join(json.dumps(t) for t in _turns()))
    out = export_replay_html(run)
    assert out.exists() and out.suffix == ".html"
    body = out.read_text()
    assert "MAP txt" in body and "<img" in body
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement**

`tools/rollout_view/html.py`:
```python
"""Shared HTML rendering for a rollout turn / run (used by replay export + live)."""
from __future__ import annotations
import html as _html


def _llm_blocks(content):
    if isinstance(content, str):
        return f"<pre>{_html.escape(content)}</pre>"
    out = []
    for e in content:
        if e.get("type") == "image_url":
            path = (e.get("image_url") or {}).get("path") or (e.get("image_url") or {}).get("url", "")
            out.append(f'<img src="{_html.escape(path)}" alt="obs image" style="max-width:100%">')
        elif e.get("type") == "text":
            out.append(f"<pre>{_html.escape(e.get('text',''))}</pre>")
    return "\n".join(out)


def render_turn(turn: dict) -> str:
    game = _html.escape("\n".join(turn.get("raw_grid") or []))
    llm = _llm_blocks(turn.get("rendered_user_content", turn.get("rendered_user_message", "")))
    return (f'<section class="turn"><h3>turn {turn.get("turn")}</h3>'
            f'<div class="cols" style="display:flex;gap:1em">'
            f'<div class="game"><h4>game state</h4><pre>{game}</pre></div>'
            f'<div class="llm"><h4>LLM input</h4>{llm}</div></div></section>')


def render_run(turns: list) -> str:
    body = "\n".join(render_turn(t) for t in turns)
    return f"<!doctype html><meta charset=utf-8><title>rollout</title><body>{body}</body>"
```
`tools/rollout_view/replay_export.py`:
```python
"""Static HTML replay export over the encoding-eval REPLAY_LOG_KEYS seam."""
from __future__ import annotations
import json
from pathlib import Path
from tools.rollout_view.html import render_run


def _load_turns(run_dir: Path) -> list:
    turns = []
    for f in sorted(Path(run_dir).glob("*.ndjson")):
        turns += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return turns


def export_replay_html(run_dir, out_name: str = "replay.html") -> Path:
    run_dir = Path(run_dir)
    out = run_dir / out_name
    out.write_text(render_run(_load_turns(run_dir)))
    return out
```

- [ ] **Step 4: Run → PASS** (2 passed).
- [ ] **Step 5: Commit** `tools/rollout_view/__init__.py tools/rollout_view/html.py tools/rollout_view/replay_export.py tests/test_rollout_view_html.py` — `feat(rollout-view): shared HTML core + static replay export`.

---

## Task 6: Live rollout stepper (localhost server)

**Files:** Create `tools/rollout_view/live_server.py`; Test `tests/test_live_stepper.py`.

Design: a `LiveStepper` that holds a `NetHackInterface` + a chosen variant's rendering, advances one turn on demand (`step_once(action_or_none)`), and exposes `current_turn() -> dict` (the same per-turn dict shape `render_turn` consumes). **Manual mode**: caller/page supplies the action. **Model mode**: a `policy(obs) -> action` callable (a real model client, or a scripted/stub policy for keyless local use). A stdlib `http.server` handler renders `current_turn()` via `render_turn` and exposes a `/step` endpoint. Bind `127.0.0.1`.

- [ ] **Step 1: Failing test** — test the `LiveStepper` core (NOT the HTTP server) for determinism/keyless-ness:

```python
# tests/test_live_stepper.py
from tools.rollout_view.live_server import LiveStepper

def test_manual_step_advances_one_turn(make_core_env):   # reuse env fixture
    from nethack_interface import NetHackInterface, RawAction
    stepper = LiveStepper(NetHackInterface(make_core_env()))
    t0 = stepper.current_turn()                 # initial obs
    assert "rendered_user_content" in t0 and "raw_grid" in t0
    stepper.step_once(RawAction(0))             # manual action, no model call
    t1 = stepper.current_turn()
    assert t1["turn"] == t0["turn"] + 1
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `LiveStepper` (the core) + a thin `serve(stepper, port=8765)` using `http.server` (GET `/` → `render_run(history)`; POST `/step` → `step_once`; manual controls in the page). `current_turn()` builds the per-turn dict: `raw_grid` from the interface's structured/raw obs, `rendered_user_content` from the chosen variant's `turn_template` (reuse `resolve_spec(variant,...).turn_template`), `turn` counter. Model mode: `LiveStepper(iface, policy=...)` where `policy(obs)->action`; manual mode: `policy=None` and the caller drives `step_once(action)`.

- [ ] **Step 4: Run → PASS.** Manually smoke the server: `python -m tools.rollout_view.live_server --help` (argparse) — confirm it starts and binds localhost.

- [ ] **Step 5: Commit** `tools/rollout_view/live_server.py tests/test_live_stepper.py` — `feat(rollout-view): live rollout stepper (localhost, manual + model modes)`.

---

## Task 7: Launchpad open-HTML affordance + verification

- [ ] 7.1 Minimal launchpad integration: in the Traces screen (or a small helper), add an action that calls `export_replay_html(run_dir)` and opens it (`webbrowser.open`). Keep it small — the TUI still shows text; HTML is the image-fidelity path. Test: the helper returns/opens the exported path for a fixture run.
- [ ] 7.2 New tests pass in isolation; full suite failures ⊆ baseline 7.
- [ ] 7.3 `nethack_interface` imports cleanly + is a resolvable workspace member (`python -c "import nethack_interface"`). Check off `openspec/changes/pysc2-interface/tasks.md`. Commit.

---

## Self-review notes

- **Spec coverage:** Tasks 2–4 → `pysc2-interface` (typed obs+spec / action spec from registry+raw / env wrapper via dispatch+raw, reuses core). Task 5 → `replay-viewer` (render both forms + image; reads the seam, no re-capture) + the shared HTML core. Task 6 → `live-rollout-stepper` (step one turn, surfaces obs+action, variant selectable, reuses rollout path; manual keyless + model modes). Task 7 → launchpad integration.
- **Type consistency:** `Observation.from_raw`, `observation_spec`, `Action(name,args)`, `RawAction(index)`, `action_spec`, `NetHackInterface.reset/step`, `render_turn/render_run`, `export_replay_html`, `LiveStepper.current_turn/step_once` — consistent across tasks.
- **Env fixture:** Tasks 4 & 6 need a real `NetHackCoreEnv`. Reuse the construction from `tests/test_skills.py` / `test_integration.py` — add a `conftest.py` `make_core_env` fixture mirroring them; do NOT invent a new env shape.
- **No new deps:** live server uses stdlib `http.server`.
