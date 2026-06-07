## ADDED Requirements

### Requirement: nh.map queryable object

The code-mode `nh` namespace SHALL expose a read-only `nh.map` object backed by
the canonical map model, letting agent code query the map structurally instead of
parsing the `nh.map_view` string. `nh.map` SHALL provide at least: the player
position, the full entity list, lookup of what occupies a coordinate
(`nh.map.at(x, y)`), and convenience accessors for common entity kinds (e.g.
`nh.map.monsters`, `nh.map.stairs`). It SHALL be read-only, consistent with the
existing `nh.status` / `nh.inventory` views.

#### Scenario: Query an entity by coordinate
- **WHEN** agent code calls `nh.map.at(x, y)` for a tile occupied by a monster
- **THEN** it returns that entity (kind "monster", with its description)

#### Scenario: Convenience accessors
- **WHEN** agent code reads `nh.map.monsters` and `nh.map.stairs`
- **THEN** each returns the entities of that kind from the current observation

#### Scenario: Read-only
- **WHEN** agent code attempts to mutate `nh.map`
- **THEN** the map state is unaffected (the object is a read-only view), consistent with `nh.status` / `nh.inventory`
