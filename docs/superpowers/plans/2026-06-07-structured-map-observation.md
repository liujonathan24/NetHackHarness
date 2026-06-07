---
change: structured-map-observation
design-doc: docs/superpowers/specs/2026-06-07-structured-map-observation-design.md
base-ref: c1eb386282296164a32c219f5ae7e079df729d08
---

# Structured-map observation (Group A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encode the NetHack map as structured text (JSON + an in-repo TOON), built from one rich canonical map model, with a `map_detail` flag, plus a read-only `nh.map` code object.

**Architecture:** A new `nethack_core/map_model.py` builds a rich `MapModel` (player + typed entities w/ coords + RLE grid) from the NLE glyph grid, reusing NLE classifiers and the existing feature/monster extractors. `nethack_harness/prompt/map_encoders.py` serializes that model as JSON or TOON at a `full`/`minimal` detail. Two variants (`JSON`, `TOON`) register in `VARIANT_REGISTRY`; `map_detail` rides on `state["map_detail"]`. `nh.map` exposes the model read-only in code-mode.

**Tech Stack:** Python, NLE 1.3.0 (`nle.nethack` glyph classifiers), numpy, pytest.

---

## Environment & test invocation (read first)

- On branch `main` (or the build-isolation branch). Package at `environments/nethack/`.
- **Test command** (cwd `environments/nethack`):
  ```bash
  cd environments/nethack
  python -m pytest ../../tests/<file> -p no:cacheprovider -q --no-header
  ```
  New test files go in repo-root `tests/`.
- **Known baseline:** 7 pre-existing failures (`test_integration`→`test_rewards` ordering pollution; pass in isolation). Do NOT fix; do NOT count as regressions. Rule: new tests pass in isolation; full-suite failure set stays ⊆ those 7.
- **Commit path-scoped** (`git add -- <paths>`); never `git add -A`.

## Grounded API facts

- NLE: `nle.nethack as N`. `N.GLYPH_MON_OFF`, `N.GLYPH_PET_OFF` (=381), `N.GLYPH_OBJ_OFF`. `N.glyph_is_monster(g)`, `N.glyph_is_pet(g)`, `N.glyph_is_object(g)`, `N.glyph_is_trap(g)`.
- Monster species: `N.permonst(N.glyph_to_mon(g)).mname` → e.g. `"wolf"`.
- `is_pet`: `N.GLYPH_PET_OFF <= g < N.GLYPH_PET_OFF + 381` (mirrors existing `_glyph_kind`).
- Item/feature labels + coords already exist in `nethack_core/observations.py`: `_FEATURE_GLYPHS` (tty-char → label incl. "stairs DOWN"/"stairs UP"/"door (closed)"/"weapon"/"armor"/…) and `extract_visible_features(tty_chars)` (returns `["stairs DOWN at (47,6)", ...]`).
- `StructuredObservation` (`nethack_core/observations.py:60`) has `status`, `inventory`, `map_view`, `adjacent`, `under_player`. `shape(obs, character)` builds it.
- `raw_obs` exposes `.glyphs` (21×79 int), `.tty_chars`, `.blstats` (player x = `blstats[0]`, y = `blstats[1]`).
- Variants: `nethack_harness/prompt/prompt_spec.py` — `_build_registry` returns a dict; `canonical(name, **kw)` helper; `ObsSpec(mode=..., setup_flags=...)`; templates are `(structured, journal, state, *, compact, journal_max_chars) -> str|list`.
- `nh` namespace: `nethack_harness/tools/code_mode.py` — a class with `@property` `map_view`/`status`/`inventory` returning read-only views off `self._obs`.
- Detail flag: the env stores config on `state`; `JSON`/`TOON` templates read `state.get("map_detail", "full")`. Implementer wires the env kwarg in Task 3.

## File structure

- Create: `environments/nethack/nethack_core/map_model.py` (MapModel, Entity, `build_map_model`)
- Create: `environments/nethack/nethack_harness/prompt/map_encoders.py` (`json_encode`, `toon_encode`)
- Modify: `environments/nethack/nethack_harness/prompt/prompt_spec.py` (JSON/TOON variants)
- Modify: `environments/nethack/nethack.py` (thread `map_detail` onto state)
- Modify: `environments/nethack/nethack_harness/tools/code_mode.py` (`nh.map`)
- Tests: `tests/test_map_model.py`, `tests/test_map_encoders.py`, `tests/test_map_variants.py`, `tests/test_nh_map.py`

---

## Task 1: Canonical map model

**Files:**
- Create: `environments/nethack/nethack_core/map_model.py`
- Test: `tests/test_map_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_map_model.py
from __future__ import annotations

import numpy as np
import nle.nethack as N

from nethack_core.map_model import build_map_model, MapModel, Entity


def _obs_with(glyphs, tty_chars=None, x=40, y=10):
    class O: pass
    o = O()
    o.glyphs = glyphs
    o.tty_chars = tty_chars if tty_chars is not None else np.full((24, 80), ord(" "), np.uint8)
    blstats = np.zeros((27,), np.int64); blstats[0] = x; blstats[1] = y
    o.blstats = blstats
    return o


def test_player_position():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)  # all floor-ish
    m = build_map_model(_obs_with(g, x=12, y=5))
    assert isinstance(m, MapModel)
    assert m.player == (12, 5)


def test_monster_entity_has_species_and_pet_flag():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
    # place a wild monster glyph and a pet glyph
    wild = N.GLYPH_MON_OFF + 20            # some monster
    pet = N.GLYPH_PET_OFF + 20             # same species, tame
    g[5, 10] = wild
    g[6, 11] = pet
    m = build_map_model(_obs_with(g))
    mons = [e for e in m.entities if e.kind == "monster"]
    by_xy = {(e.x, e.y): e for e in mons}
    assert (10, 5) in by_xy and (11, 6) in by_xy
    assert by_xy[(10, 5)].species == N.permonst(N.glyph_to_mon(wild)).mname
    assert by_xy[(10, 5)].is_pet is False
    assert by_xy[(11, 6)].is_pet is True


def test_item_entity_has_class():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
    g[3, 4] = N.GLYPH_OBJ_OFF + 20
    m = build_map_model(_obs_with(g))
    items = [e for e in m.entities if e.kind == "item"]
    assert items and items[0].obj_class is not None


def test_grid_is_rle_string():
    g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
    m = build_map_model(_obs_with(g))
    assert isinstance(m.grid, str) and len(m.grid) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_map_model.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ModuleNotFoundError: No module named 'nethack_core.map_model'`.

- [ ] **Step 3: Write minimal implementation**

```python
# environments/nethack/nethack_core/map_model.py
"""The canonical map model: a rich, typed view of the NetHack map.

Built from the NLE glyph grid (21x79). Entities carry coordinates and per-kind
attributes derived from NLE's glyph classifiers; the grid is a compact RLE of the
terrain layer. This is the one model the JSON/TOON encoders and nh.map consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# NLE pet glyph range (mirrors nethack_core.observations._glyph_kind).
_PET_OFF = 381
_NUMMONS = 381


@dataclass
class Entity:
    kind: str            # monster | item | stair | door | trap | feature
    glyph_id: int
    x: int
    y: int
    description: str
    species: Optional[str] = None     # monster
    is_pet: Optional[bool] = None     # monster
    obj_class: Optional[str] = None   # item
    detail: Optional[str] = None      # stair direction / door state / trap type / feature name


@dataclass
class MapModel:
    player: Optional[tuple]           # (x, y)
    entities: list                    # list[Entity]
    grid: str                         # RLE topology string
    legend: dict = field(default_factory=dict)


def _rle_grid(glyphs) -> str:
    """Compact run-length encoding of the terrain glyph rows."""
    import numpy as np

    rows = []
    for row in np.asarray(glyphs):
        out = []
        prev = None
        count = 0
        for v in row:
            v = int(v)
            if v == prev:
                count += 1
            else:
                if prev is not None:
                    out.append(f"{prev}x{count}" if count > 1 else f"{prev}")
                prev, count = v, 1
        if prev is not None:
            out.append(f"{prev}x{count}" if count > 1 else f"{prev}")
        rows.append(",".join(out))
    return "\n".join(rows)


def build_map_model(raw_obs: Any) -> MapModel:
    import numpy as np
    import nle.nethack as N
    from nethack_core.observations import _FEATURE_GLYPHS

    glyphs = np.asarray(raw_obs.glyphs)
    tty = np.asarray(getattr(raw_obs, "tty_chars"))
    blstats = np.asarray(raw_obs.blstats)
    player = (int(blstats[0]), int(blstats[1]))

    entities: list = []
    h, w = glyphs.shape
    for gy in range(h):
        for gx in range(w):
            g = int(glyphs[gy, gx])
            if N.glyph_is_monster(g) or N.glyph_is_pet(g):
                is_pet = bool(N.GLYPH_PET_OFF <= g < N.GLYPH_PET_OFF + _NUMMONS)
                try:
                    species = N.permonst(N.glyph_to_mon(g)).mname
                except Exception:
                    species = None
                entities.append(Entity("monster", g, gx, gy,
                                       description=species or "monster",
                                       species=species, is_pet=is_pet))
            elif N.glyph_is_object(g):
                # Item class label via the tty char on this tile (reuses the
                # proven _FEATURE_GLYPHS map); tty row = glyph row + 1.
                ty = gy + 1
                ch = int(tty[ty, gx]) if 0 <= ty < tty.shape[0] else ord("?")
                label = _FEATURE_GLYPHS.get(ch)
                entities.append(Entity("item", g, gx, gy,
                                       description=label or "object", obj_class=label))

    # Features (stairs/doors/altars/...) from the tty layer with coordinates.
    for ty in range(1, min(22, tty.shape[0])):
        for tx in range(tty.shape[1]):
            label = _FEATURE_GLYPHS.get(int(tty[ty, tx]))
            if not label:
                continue
            if "stairs" in label:
                kind, detail = "stair", label
            elif "door" in label:
                kind, detail = "door", label
            elif label in ("weapon", "armor", "tool", "scroll", "potion", "wand",
                           "ring", "amulet", "gem/rock", "food/corpse", "gold"):
                continue  # those are items, handled via glyphs above
            else:
                kind, detail = "feature", label
            entities.append(Entity(kind, 0, tx, ty - 1, description=label, detail=detail))

    return MapModel(player=player, entities=entities, grid=_rle_grid(glyphs))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_map_model.py -p no:cacheprovider -q --no-header
```
Expected: PASS (4 passed). If `test_item_entity_has_class` fails because the tty char is blank in the synthetic obs, set the corresponding `tty_chars` cell in the test to `ord("(")` at `(ty=4, tx=4)` so the item-class label resolves — update the fixture, not the implementation.

- [ ] **Step 5: Commit**

```bash
git add -- environments/nethack/nethack_core/map_model.py tests/test_map_model.py
git commit -m "feat(structured-map): rich canonical MapModel from NLE glyphs"
```

---

## Task 2: JSON + TOON encoders

**Files:**
- Create: `environments/nethack/nethack_harness/prompt/map_encoders.py`
- Test: `tests/test_map_encoders.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_map_encoders.py
from __future__ import annotations

import json

from nethack_core.map_model import MapModel, Entity
from nethack_harness.prompt.map_encoders import json_encode, toon_encode


def _model():
    return MapModel(
        player=(10, 5),
        entities=[
            Entity("monster", 20, 12, 5, "wolf", species="wolf", is_pet=False),
            Entity("stair", 0, 47, 6, "stairs DOWN", detail="stairs DOWN"),
        ],
        grid="2353x79",
    )


def test_json_full_has_entities_and_grid():
    s = json_encode(_model(), detail="full")
    d = json.loads(s)
    assert d["player"] == [10, 5]
    kinds = {e["kind"] for e in d["entities"]}
    assert {"monster", "stair"} <= kinds
    assert "grid" in d
    # rich attrs present at full detail
    mon = next(e for e in d["entities"] if e["kind"] == "monster")
    assert mon["species"] == "wolf"


def test_json_minimal_trims_attrs_and_grid():
    full = json_encode(_model(), detail="full")
    mini = json_encode(_model(), detail="minimal")
    assert "grid" not in json.loads(mini)
    mon = next(e for e in json.loads(mini)["entities"] if e["kind"] == "monster")
    assert "species" not in mon  # rich attrs dropped
    assert len(mini) < len(full)


def test_toon_deterministic_and_smaller_than_json():
    m = _model()
    a = toon_encode(m, detail="full")
    b = toon_encode(m, detail="full")
    assert a == b  # deterministic
    assert len(a) < len(json_encode(m, detail="full"))  # more compact
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_map_encoders.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ModuleNotFoundError: ...map_encoders`.

- [ ] **Step 3: Write minimal implementation**

```python
# environments/nethack/nethack_harness/prompt/map_encoders.py
"""Serialize the canonical MapModel as JSON or TOON, at a selectable detail.

`full`  -> rich entity attributes + the RLE grid.
`minimal` -> entity kind/coord/description only; no grid, no rich attrs.
Both project the SAME model, so JSON and TOON cannot diverge.
"""
from __future__ import annotations

import json
from typing import Any

_RICH_FIELDS = ("species", "is_pet", "obj_class", "detail")


def _entity_dict(e: Any, detail: str) -> dict:
    d = {"kind": e.kind, "x": e.x, "y": e.y, "desc": e.description}
    if detail == "full":
        for f in _RICH_FIELDS:
            v = getattr(e, f, None)
            if v is not None:
                d[f] = v
    return d


def _model_dict(model: Any, detail: str) -> dict:
    d = {
        "player": list(model.player) if model.player else None,
        "entities": [_entity_dict(e, detail) for e in model.entities],
    }
    if detail == "full":
        d["grid"] = model.grid
    return d


def json_encode(model: Any, *, detail: str = "full") -> str:
    return json.dumps(_model_dict(model, detail), separators=(",", ":"))


def toon_encode(model: Any, *, detail: str = "full") -> str:
    """Token-frugal line-oriented encoding of the same model.

    Format (deterministic):
        @ x,y
        <kind> x,y desc[ k=v ...]
        ...
        grid: <rle>            # full detail only
    """
    lines = []
    if model.player:
        lines.append(f"@ {model.player[0]},{model.player[1]}")
    for e in model.entities:
        parts = [e.kind, f"{e.x},{e.y}", e.description]
        if detail == "full":
            for f in _RICH_FIELDS:
                v = getattr(e, f, None)
                if v is not None:
                    parts.append(f"{f}={v}")
        lines.append(" ".join(str(p) for p in parts))
    if detail == "full":
        lines.append(f"grid: {model.grid}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_map_encoders.py -p no:cacheprovider -q --no-header
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add -- environments/nethack/nethack_harness/prompt/map_encoders.py tests/test_map_encoders.py
git commit -m "feat(structured-map): JSON + in-repo TOON encoders with detail flag"
```

---

## Task 3: JSON / TOON variants + map_detail flag

**Files:**
- Modify: `environments/nethack/nethack_harness/prompt/prompt_spec.py`
- Modify: `environments/nethack/nethack.py` (store `map_detail` on state)
- Test: `tests/test_map_variants.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_map_variants.py
from __future__ import annotations

import json
import numpy as np
import nle.nethack as N

from nethack_harness.prompt.prompt_spec import VARIANT_REGISTRY


class _Obs:
    def __init__(self):
        g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
        g[5, 10] = N.GLYPH_MON_OFF + 20
        self.glyphs = g
        self.tty_chars = np.full((24, 80), ord(" "), np.uint8)
        b = np.zeros((27,), np.int64); b[0] = 40; b[1] = 10
        self.blstats = b


def _structured():
    # Minimal StructuredObservation-like object the template's status/inventory
    # rendering tolerates; reuse the tests/conftest make_structured_obs if present.
    from nethack_core.observations import StructuredObservation
    return StructuredObservation(map_view="", messages=[], inventory=[],
                                 status={"hitpoints": 10, "depth": 1}, character={})


def test_json_and_toon_registered():
    assert "JSON" in VARIANT_REGISTRY
    assert "TOON" in VARIANT_REGISTRY


def test_json_variant_emits_json_text():
    spec = VARIANT_REGISTRY["JSON"]
    state = {"raw_obs": _Obs(), "map_detail": "full"}
    out = spec.turn_template(_structured(), None, state, compact=True, journal_max_chars=2000)
    assert isinstance(out, str)
    assert '"entities"' in out  # JSON payload present


def test_map_detail_minimal_smaller_than_full():
    spec = VARIANT_REGISTRY["JSON"]
    obs = _Obs(); s = _structured()
    full = spec.turn_template(s, None, {"raw_obs": obs, "map_detail": "full"},
                              compact=True, journal_max_chars=2000)
    mini = spec.turn_template(s, None, {"raw_obs": obs, "map_detail": "minimal"},
                              compact=True, journal_max_chars=2000)
    assert len(mini) < len(full)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_map_variants.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `KeyError: 'JSON'`.

- [ ] **Step 3: Write minimal implementation**

In `prompt_spec.py`, add a structured-map template factory near `_image_template`:

```python
def _structured_map_template(fmt):
    """Per-turn template emitting a structured-text map (JSON or TOON).

    ``fmt`` is "json" or "toon". The map_detail level is read from
    ``state["map_detail"]`` (default "full"). The status/inventory block is
    appended via the canonical formatter with the ASCII map gated off.
    """

    def _render(structured, journal, state, *, compact, journal_max_chars):
        from nethack_core.map_model import build_map_model
        from nethack_harness.prompt.map_encoders import json_encode, toon_encode
        from nethack_harness.prompt.rendering import format_observation_as_chat

        detail = state.get("map_detail", "full")
        model = build_map_model(state["raw_obs"])
        enc = json_encode if fmt == "json" else toon_encode
        map_text = enc(model, detail=detail)
        status = format_observation_as_chat(
            structured, journal, state, compact=compact,
            journal_max_chars=journal_max_chars,
            include_map=False, include_local=False,
        )
        return f"=== MAP ({fmt.upper()}) ===\n{map_text}\n\n{status}"

    return _render
```

Register in `_build_registry`'s dict:

```python
        "JSON": canonical("JSON", turn_template=_structured_map_template("json")),
        "TOON": canonical("TOON", turn_template=_structured_map_template("toon")),
```

In `nethack.py`, thread the flag: add a `map_detail: str = "full"` kwarg on the verifiers env `__init__` (store `self.map_detail = map_detail`), and where the env initializes per-rollout `state` (the same place it sets other state like `structured_obs`/`raw_obs`, near `state["env"] = ...` in setup), add:

```python
        state["map_detail"] = self.map_detail
```

Read the actual env `__init__` and the state-setup site first to place these precisely; match the surrounding kwarg + state-assignment style.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_map_variants.py -p no:cacheprovider -q --no-header
# existing variants unchanged
python -m pytest ../../tests/test_obs_compaction.py ../../tests/test_balrog.py ../../tests/test_image_variants.py -p no:cacheprovider -q --no-header
```
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add -- environments/nethack/nethack_harness/prompt/prompt_spec.py environments/nethack/nethack.py tests/test_map_variants.py
git commit -m "feat(structured-map): JSON/TOON variants + map_detail flag"
```

---

## Task 4: nh.map code-interpretable object

**Files:**
- Modify: `environments/nethack/nethack_harness/tools/code_mode.py`
- Test: `tests/test_nh_map.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nh_map.py
from __future__ import annotations

import numpy as np
import nle.nethack as N

from nethack_core.map_model import MapModel, Entity
from nethack_harness.tools.code_mode import MapView


def _model():
    return MapModel(
        player=(10, 5),
        entities=[
            Entity("monster", 20, 12, 5, "wolf", species="wolf", is_pet=False),
            Entity("stair", 0, 47, 6, "stairs DOWN", detail="stairs DOWN"),
        ],
        grid="g",
    )


def test_player_and_entities():
    mv = MapView(_model())
    assert mv.player == (10, 5)
    assert len(mv.entities) == 2


def test_at_returns_entity():
    mv = MapView(_model())
    e = mv.at(12, 5)
    assert e is not None and e.kind == "monster"
    assert mv.at(0, 0) is None


def test_kind_accessors():
    mv = MapView(_model())
    assert [e.kind for e in mv.monsters] == ["monster"]
    assert [e.kind for e in mv.stairs] == ["stair"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_nh_map.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ImportError: cannot import name 'MapView'`.

- [ ] **Step 3: Write minimal implementation**

In `code_mode.py`, add a `MapView` class and expose it as `nh.map`. First read how the `nh` namespace object is defined (the class with `@property map_view`/`status`/`inventory` off `self._obs`), then add:

```python
class MapView:
    """Read-only structural view of the map for code-mode agents."""
    def __init__(self, model):
        self._m = model

    @property
    def player(self):
        return self._m.player

    @property
    def entities(self):
        return list(self._m.entities)

    def at(self, x, y):
        for e in self._m.entities:
            if e.x == x and e.y == y:
                return e
        return None

    def _of(self, kind):
        return [e for e in self._m.entities if e.kind == kind]

    @property
    def monsters(self):
        return self._of("monster")

    @property
    def stairs(self):
        return self._of("stair")
```

Add a `map` property on the `nh` namespace class, building the model lazily from the same raw obs the namespace already holds (mirror how `map_view` reads `self._obs`):

```python
    @property
    def map(self):
        from nethack_core.map_model import build_map_model
        return MapView(build_map_model(self._raw_obs))
```

Read the namespace class to confirm the attribute holding the raw NLE obs (it may be `self._raw_obs`, `self._obs`, or passed in); wire `map` to whatever the class already stores. If only the StructuredObservation is held, thread the raw obs into the namespace constructor at its single construction site in `run_user_code` (pass the raw obs through) — make that threading the minimal change.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_nh_map.py -p no:cacheprovider -q --no-header
python -m pytest ../../tests/test_code_mode.py -p no:cacheprovider -q --no-header
```
Expected: PASS for both (test_code_mode unchanged).

- [ ] **Step 5: Commit**

```bash
git add -- environments/nethack/nethack_harness/tools/code_mode.py tests/test_nh_map.py
git commit -m "feat(structured-map): nh.map read-only code object"
```

---

## Task 5: Verification + tasks.md sync

- [ ] **Step 1: New tests in isolation**

```bash
cd environments/nethack
python -m pytest ../../tests/test_map_model.py ../../tests/test_map_encoders.py ../../tests/test_map_variants.py ../../tests/test_nh_map.py -p no:cacheprovider -q --no-header
```
Expected: all PASS.

- [ ] **Step 2: Regression + full suite (failure set ⊆ baseline 7)**

```bash
cd environments/nethack
python -m pytest ../../tests -p no:cacheprovider -q --no-header 2>&1 | tail -12
```
Expected: only the 7 known baseline failures (test_integration/test_rewards). Passed count up by the new tests. Any NEW failure → fix before proceeding.

- [ ] **Step 3: Check off `openspec/changes/structured-map-observation/tasks.md`** (`- [ ]` → `- [x]`).

- [ ] **Step 4: Commit**

```bash
git add -- openspec/changes/structured-map-observation/tasks.md
git commit -m "chore(structured-map): mark tasks complete; verified ⊆ baseline"
```

---

## Self-review notes

- **Spec coverage:** Task 1 → `canonical-map-model` (entities w/ coords + rich attrs + grid, NLE classifiers). Task 2+3 → `structured-map-observation` (JSON/TOON, `map_detail` full/minimal, existing unchanged). Task 4 → `code-interpretable-map` (`nh.map` at/accessors/read-only). encoding-eval correctly absent (split out).
- **Type consistency:** `build_map_model(raw_obs) -> MapModel`; `Entity` fields (`kind/glyph_id/x/y/description/species/is_pet/obj_class/detail`) consistent across Tasks 1,2,4; `json_encode/toon_encode(model, *, detail)` consistent across Tasks 2,3; `MapView` API (`player/entities/at/monsters/stairs`) consistent across Tasks 4.
- **Grid RLE** is glyph-id based (lossless topology); tests assert it's a non-empty string, not an exact format.
