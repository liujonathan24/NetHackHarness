## ADDED Requirements

### Requirement: Glyph-to-image rendering

The harness SHALL provide an image renderer module exposing two explicit,
strict render paths that each return a base64-encoded PNG of the NLE
observation:

- a GlyphMapper tile path that rasterizes the observation's `glyphs` grid into
  NetHack tiles, and
- a PIL tty-text path that rasterizes the observation's `tty_chars` /
  `tty_colors`.

Each path SHALL fail fast: when its required optional dependency (MiniHack/PIL
for the tile path, PIL for the tty path) is unavailable, or when rendering
raises, the path SHALL raise a clear error rather than silently substituting the
other path. The renderer module SHALL remain importable when MiniHack and PIL
are absent; optional dependencies SHALL be resolved only when a render is
actually requested.

#### Scenario: Tile render via GlyphMapper
- **WHEN** the GlyphMapper path is given an observation whose `glyphs` grid is available and MiniHack/PIL are importable
- **THEN** it returns a base64-encoded PNG string produced from the GlyphMapper tile image

#### Scenario: Tty-text render via PIL
- **WHEN** the tty-text path is given an observation and PIL is importable
- **THEN** it returns a base64-encoded PNG string produced from the observation's `tty_chars` / `tty_colors`

#### Scenario: Strict failure on missing dependency
- **WHEN** a render path is invoked but its required optional dependency is unavailable, or rendering raises
- **THEN** the path raises a clear error and does NOT silently fall back to the other render path

#### Scenario: Module imports without optional deps
- **WHEN** the image-render module is imported in an environment lacking MiniHack and PIL
- **THEN** the import succeeds and the optional dependencies are only resolved when a render is actually requested

### Requirement: IMG and IMG_TTY variants

The variant registry SHALL include an `IMG` variant and an `IMG_TTY` variant,
each using an image-mode observation spec. Their per-turn template SHALL emit an
OpenAI-multimodal content list containing an `image_url` entry (a base64 PNG
data URI) and a text entry. The text entry SHALL carry the journal, status, and
inventory blocks only; it SHALL NOT include the ASCII map, the under-player
block, the adjacent-tiles block, or next-action hints (the image is the sole
spatial channel). `IMG` SHALL use the GlyphMapper tile path; `IMG_TTY` SHALL use
the tty-text path. The rendered bytes of all pre-existing (ASCII / BALROG /
glyph-box) variants SHALL remain unchanged.

#### Scenario: IMG variant emits multimodal message
- **WHEN** a rollout runs with variant `IMG`
- **THEN** each per-turn user message content is a list containing an `image_url` (base64 PNG data URI) of the GlyphMapper tiles and a text block with the journal, status, and inventory text only

#### Scenario: IMG_TTY variant uses the tty-text path
- **WHEN** a rollout runs with variant `IMG_TTY`
- **THEN** each per-turn user message content is a list containing an `image_url` rendered from the tty-text path and a text block with the journal, status, and inventory text only

#### Scenario: IMG text omits spatial text channels
- **WHEN** the IMG or IMG_TTY text block is built
- **THEN** it contains no ASCII map, under-player, adjacent-tiles, or next-action-hint content

#### Scenario: Existing variants unchanged
- **WHEN** a rollout runs with any pre-existing variant (e.g. `B1`, `B`, `G`)
- **THEN** the per-turn user message content is a string identical to the pre-change output

### Requirement: Multimodal-capable env response

The environment's per-turn response assembly SHALL wrap either a string or a
multimodal content list into the user message. When per-turn prefix parts
(autohalt, refiner, multi-tool, and feedback notices) are present, they SHALL be
injected into a string observation by the existing join and into a list
observation as a prepended text block, so that no prefix information is lost in
either shape.

#### Scenario: String observation with prefix
- **WHEN** the per-turn template returns a string and one or more prefix parts are present
- **THEN** the user message content is the prefix parts joined ahead of the observation string, identical to the pre-change behavior

#### Scenario: List observation with prefix
- **WHEN** the per-turn template returns a multimodal content list and one or more prefix parts are present
- **THEN** the user message content is a list whose first element is a text block carrying the prefix parts, followed by the image and text entries

#### Scenario: List observation without prefix
- **WHEN** the per-turn template returns a multimodal content list and no prefix parts are present
- **THEN** the user message content is the content list wrapped unchanged into the user message
