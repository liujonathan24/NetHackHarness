---
comet_change: structured-map-observation
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-07-structured-map-observation
status: final
---

# Structured-map observation (Group A) — technical design

> Canonical requirements: the OpenSpec delta specs under
> `openspec/changes/structured-map-observation/specs/`. This is the *how*.

## Summary

Add a structured-text observation modality to the NetHack harness: a **rich
canonical map model** in `nethack_core`, two encoders (`JSON` and an in-repo
`TOON`) projecting it at a selectable `map_detail` level, and a read-only
`nh.map` object for code-mode agents. The encoding-eval benchmark is split into a
follow-up change. Builds on the same `VARIANT_REGISTRY` / `nh` namespace as the
ASCII and IMG/IMG_TTY modalities.

## Confirmed parameters (from design brainstorming)

| Decision | Choice |
| --- | --- |
| Eval scope | **Split out** — this change ships the observation substrate; the encoding benchmark is a follow-up change. |
| Entity schema | **Rich where derivable.** Per-kind attrs: monster species + pet; item object-class; stair direction; door state; trap type. Disposition (peaceful/hostile) omitted — not in the glyph stream. |
| Payload | **Entities + compact RLE grid** + status/inventory. |
| Detail control | **`map_detail` config flag (`full` \| `minimal`)** on the `JSON`/`TOON` variants — a rollout-level flag, not separate variants. |
| nh.map | **Minimal read-only** (player, entities, `at(x,y)`, `monsters`, `stairs`). |

## Components

### 1. Canonical map model — `nethack_core` (new module)

`MapModel`: `player: (x, y)`, `entities: list[Entity]`, `grid: CompactGrid`. It is
derived from the same NLE observation already shaped into `StructuredObservation`
(reuse its `status`/`inventory`; do not re-parse).

`Entity` fields: `kind` (monster/item/stair/door/trap/feature), `glyph_id`,
`x`, `y`, `description`, plus kind-specific (all where the observation exposes
them):
- **monster** → `species` (`glyph_to_mon` → permonst name), `is_pet`
  (`glyph_is_pet`). No disposition.
- **item** → `obj_class` (`glyph_to_obj` → object class).
- **stair** → `direction` (up/down, from the cmap glyph).
- **door** → `state` (open/closed/broken, from cmap variants).
- **trap** → `trap_type` (`glyph_to_trap`).
- **feature** → name (fountain/altar/etc., cmap).

Built by scanning the 21×79 glyph grid, classifying each non-empty glyph via NLE
helpers (`glyph_is_*`, `glyph_to_*`, `GLYPH_*_OFF`) + the existing `_glyph_kind`
and `_FEATURE_GLYPHS`. The model is the **rich superset**; encoders project it.

`CompactGrid`: the terrain/topology layer (walls/floor/corridors) as glyph-RLE,
reusing `_glyph_run_encode` / `_strip_blank_rows`, with a small symbol legend.

### 2. Encoders — `nethack_harness/prompt/` (new module)

- `json_encode(model, *, detail) -> str` — `MapModel` → dict → `json.dumps`.
- `toon_encode(model, *, detail) -> str` — in-repo deterministic TOON: a compact
  line-oriented form (a header, per-kind entity lines, the RLE grid). Documented
  format; one encoder, so JSON and TOON can't diverge from the model.
- `detail`:
  - `full` → rich entity attrs + the RLE grid + status/inventory.
  - `minimal` → entity `kind`, `(x,y)`, short description; **no grid, no rich
    attrs**; status/inventory still included.

### 3. Variants + flag — `prompt_spec.py`

Two registry entries `JSON` and `TOON` with image-mode-style templates that build
the text from the model + encoder. `map_detail` is a rollout-level config flag
(env kwarg, default `full`) threaded into the template, mirroring how
`compact_obs` already flows. Existing variants stay byte-identical.

### 4. `nh.map` — `code_mode.py`

A read-only object backed by the model: `nh.map.player`, `nh.map.entities`,
`nh.map.at(x, y)`, `nh.map.monsters`, `nh.map.stairs` — mirroring the existing
read-only `nh.status` / `nh.inventory` views.

## Data flow

```
NLE obs (glyphs 21×79, tty, blstats)
        │  reuse StructuredObservation status/inventory
        ▼
 MapModel (player + rich entities + RLE grid)        [nethack_core]
        │            │                     │
        ▼            ▼                     ▼
 json_encode    toon_encode           nh.map (read-only)   [consumers]
  (detail)       (detail)
        │            │
        ▼            ▼
   JSON variant   TOON variant   ── map_detail flag (full|minimal)
```

## Risks / Trade-offs

- [TOON has no reference Python lib] → define a small, documented in-repo format;
  test determinism + more-compact-than-JSON rather than chase an external spec.
- [Entity classification fidelity] → reuse NLE classifiers; fixture tests per kind
  (monster+species+pet, item+class, up/down stair, door state, trap).
- [Disposition not in glyphs] → omit; document the limitation in the model.
- [JSON token cost] → `minimal` detail + the sparse model; the (future) eval will
  quantify full-vs-minimal and JSON-vs-TOON tokens.

## Testing strategy

- Model: classify fixtures per kind; player position; grid RLE correctness.
- Encoders: JSON shape; TOON determinism; TOON < JSON size; full-vs-minimal
  projection (minimal omits grid + rich attrs, is smaller).
- Variants: `JSON`/`TOON` emit the encoded text; `map_detail` honored; existing
  variants byte-identical.
- `nh.map`: `at(x,y)`, accessors, read-only.

## Out of scope

The encoding-eval benchmark (its own follow-up change); Group B; RL training; any
change to ASCII/IMG rendered bytes.
