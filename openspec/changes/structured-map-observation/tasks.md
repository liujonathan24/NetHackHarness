## 1. Canonical map model

- [x] 1.1 Add a typed map-model module in `nethack_core` (entities with kind/glyph/(x,y)/description, player position, compact grid). NOTE: vendored in BOTH `nethack_core/` copies (repo-root workspace package + `environments/nethack/` env-bundled copy).
- [x] 1.2 Implement glyph→entity classification reusing NLE classifiers (`glyph_is_monster/object/trap`, `glyph_to_mon`, `permonst().mname`, `GLYPH_PET_OFF`) + existing `_FEATURE_GLYPHS`. Rich attrs: monster species+is_pet, item obj_class, stair direction, door state (via `detail`), trap location. Disposition omitted (not in glyphs).
- [x] 1.3 Build the model from the existing observation pipeline (reuse `StructuredObservation` status/inventory; don't re-parse).
- [x] 1.4 Unit-test classification against fixtures (monster+species+pet, item class, trap, stairs/features, player position, grid RLE).

## 2. Encoders + JSON/TOON variants

- [x] 2.1 JSON serializer for the canonical model, honoring `map_detail` (full = rich entities + RLE grid + status/inventory; minimal = kind/coord/desc + status/inventory).
- [x] 2.2 In-repo TOON encoder for the same model + `map_detail` (deterministic; documented format; more compact than JSON — verified 106 vs 199 chars on the fixture).
- [x] 2.3 Register `JSON` and `TOON` variants in `VARIANT_REGISTRY` with templates emitting the serialized model; wire the `map_detail` config flag (env kwarg, default full, threaded onto `state["map_detail"]`); keep existing variants byte-identical.
- [x] 2.4 Tests: JSON shape, TOON determinism + more-compact-than-JSON, full-vs-minimal detail, existing variants unchanged.

## 3. Code-interpretable map (nh.map)

- [x] 3.1 Add a read-only `nh.map` object (player, entities, `at(x,y)`, `monsters`, `stairs`) to the code-mode `nh` namespace backed by the canonical model. Threaded `raw_obs` through `run_user_code` so `nh.map` is populated in real rollouts.
- [x] 3.2 Tests: query by coordinate, convenience accessors, read-only semantics.

<!-- encoding-eval harness split into a follow-up change (per design decision). -->
<!-- Verification: 14 new tests pass; full suite 364 passed / 7 failed (== pre-existing baseline; zero new failures). -->
