## 1. Canonical map model

- [ ] 1.1 Add a typed map-model module in `nethack_core` (entities with kind/glyph/(x,y)/description, player position, compact grid).
- [ ] 1.2 Implement glyph→entity classification reusing NLE classifiers (`glyph_is_*`, `glyph_to_*`, `GLYPH_*_OFF`) + existing `_glyph_kind`/`_FEATURE_GLYPHS`.
- [ ] 1.3 Build the model from the existing observation pipeline (reuse `StructuredObservation` status/inventory; don't re-parse).
- [ ] 1.4 Unit-test classification against fixtures (monster, item, stairs, door, player position).

## 2. Encoders + JSON/TOON variants

- [ ] 2.1 JSON serializer for the canonical model, honoring `map_detail` (full = rich entities + RLE grid + status/inventory; minimal = kind/coord/desc + status/inventory).
- [ ] 2.2 In-repo TOON encoder for the same model + `map_detail` (deterministic; documented format; more compact than JSON).
- [ ] 2.3 Register `JSON` and `TOON` variants in `VARIANT_REGISTRY` with templates emitting the serialized model; wire the `map_detail` config flag; keep existing variants byte-identical.
- [ ] 2.4 Tests: JSON shape, TOON determinism + more-compact-than-JSON, full-vs-minimal detail, existing variants unchanged.

## 3. Code-interpretable map (nh.map)

- [ ] 3.1 Add a read-only `nh.map` object (player, entities, `at(x,y)`, `monsters`, `stairs`) to the code-mode `nh` namespace backed by the canonical model.
- [ ] 3.2 Tests: query by coordinate, convenience accessors, read-only semantics.

<!-- encoding-eval harness split into a follow-up change (per design decision). -->
