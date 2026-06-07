---
comet_change: image-observation-renderer
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-07-image-observation-renderer
status: final
---

# Image-observation renderer — technical design

> Canonical requirements live in the OpenSpec delta spec
> (`openspec/changes/image-observation-renderer/specs/image-observation/spec.md`).
> This document is the *how*, not the *what*. It does not redefine requirements.

## Summary

Add a rendered-image observation path to the NetHack harness: convert the NLE
`glyphs` grid (or the `tty_chars`/`tty_colors` raster) into a base64 PNG and
deliver it to the model as an OpenAI-multimodal user message. Land two variants,
`IMG` (GlyphMapper tiles) and `IMG_TTY` (tty-text raster), and generalize
`env_response` to wrap either a string or a content list. The prompt factory was
pre-wired for this (`ObsSpec.mode` documents `"img"`, `turn_template` is typed
`-> str | list`); this change is the last piece.

## Confirmed parameters (from design brainstorming)

| Decision | Choice |
| --- | --- |
| Image resolution | **Native 16px GlyphMapper tiles** → 1264×336 px PNG. No downscaling. Under Anthropic's 1568px max edge; ~3 OpenAI vision tiles. |
| IMG text content | **Journal + status + inventory only.** Drop MAP, UNDER-PLAYER, ADJACENT, next-action hints. The image is the sole spatial channel (pure-vision ablation). |
| Tile-path failure | **Strict / fail-fast.** No silent IMG→tty fallback. `IMG` always uses GlyphMapper; `IMG_TTY` always uses tty. A render path raises on missing dep or render error. |
| Prefix injection | **Separate leading text block.** prefix_parts become the first `{type:text}` element of the content list. |

## Components

### 1. `nethack_harness/prompt/image_render.py` (new)

Optional deps (`minihack`, `PIL`) are imported **lazily inside functions**, so
the module imports cleanly where they are absent and `prompt_spec` import time
stays free of the heavy tile stack.

- `glyphs_to_png_b64(raw_obs) -> str` — `GlyphMapper().to_rgb(raw_obs.glyphs)`
  → `(336, 1264, 3)` ndarray → `PIL.Image.fromarray` → PNG bytes → base64.
  Raises (ImportError / RuntimeError) if MiniHack or PIL is unavailable or the
  render fails. *Strict.*
- `tty_to_png_b64(raw_obs) -> str` — rasterize `raw_obs.tty_chars` /
  `tty_colors` to a PNG via PIL (monospace draw, NLE's 16-color palette).
  Raises if PIL is unavailable. *Strict.*
- `to_data_uri(b64) -> str` — `f"data:image/png;base64,{b64}"`.

Data source: `state["raw_obs"]` carries `.glyphs` (21×79 ints), `.tty_chars`,
`.tty_colors`. The renderer takes `raw_obs` and reads those attributes; it has
no dependency on `StructuredObservation` or `state`.

### 2. `nethack_harness/prompt/prompt_spec.py` (modified)

- `_image_template(render_fn)` — a turn_template factory. Given a `render_fn`
  (`glyphs_to_png_b64` or `tty_to_png_b64`), returns
  `turn_template(structured, journal, state, *, compact, journal_max_chars)`
  that:
  1. builds the **text block** via `format_observation_as_chat(...,
     include_map=False, include_local=False)` (journal + status + inventory),
  2. builds the **image** = `to_data_uri(render_fn(state["raw_obs"]))`,
  3. returns `[{"type": "image_url", "image_url": {"url": data_uri}},
     {"type": "text", "text": text_block}]`.
- Registry: `IMG = canonical("IMG", obs=ObsSpec(mode="img"),
  turn_template=_image_template(glyphs_to_png_b64))` and the analogous
  `IMG_TTY` with `tty_to_png_b64`. Image-render imports happen inside
  `_image_template` (lazy), not at module top.

### 3. `nethack_harness/prompt/rendering.py` (modified)

`format_observation_as_chat` gains two keyword gates, both defaulting to the
current behavior so every existing variant is byte-identical:

- `include_map: bool = True` — gates the `=== MAP ===` section (and its E2
  frontier paint).
- `include_local: bool = True` — gates the UNDER-PLAYER, ADJACENT, and
  next-action-hint sections.

The journal / status / inventory blocks and their diff-only fingerprint logic
are reused unchanged. Reusing the formatter (vs. a new status-only function)
avoids drift in the dedup logic.

### 4. `nethack.py` (modified)

`_compose_user_content(obs, prefix_parts) -> str | list`:

```
if isinstance(obs, str):
    return ("\n".join(prefix_parts) + "\n\n" + obs) if prefix_parts else obs
# list (multimodal)
if prefix_parts:
    return [{"type": "text", "text": "\n".join(prefix_parts)}, *obs]
return obs
```

Both return sites route through it:
- **~503 journal short-circuit**: today does `obs_text = f"[{feedback}]\n\n{obs_text}"`.
  Becomes `content = _compose_user_content(obs_text, [f"[{feedback}]"] if feedback else [])`.
- **~890 main**: replaces the `"\n".join(prefix_parts) + ... + obs_text` block;
  `content = _compose_user_content(obs_text, prefix_parts)`.

Then `return [vf.UserMessage(role="user", content=content)]` at both. The string
path reproduces current bytes exactly.

## Data flow

```
state["raw_obs"]
   .glyphs / .tty_chars,.tty_colors
        │
        ▼  (IMG → glyphs_to_png_b64 | IMG_TTY → tty_to_png_b64)   STRICT
   base64 PNG ── to_data_uri ──┐
                               ▼
 _image_template → [ {image_url: data:...}, {text: journal+status+inventory} ]
                               │  (turn_template returns a list)
                               ▼
 env_response → _compose_user_content(list, prefix_parts)
                               │  prefix → leading {type:text} block
                               ▼
                  vf.UserMessage(role="user", content=list)
```

## Risks / Trade-offs

- **Strict failure** surfaces a broken/missing tileset as a hard rollout error
  instead of a silent IMG→tty degrade. Accepted: cleaner eval signal; the cost
  is a hard failure if MiniHack breaks mid-run. → Mitigate by validating the
  tile path once at variant resolution / first turn so it fails early.
- **Multimodal vs text-only consumers** (trace writer, refiner window): the
  message content is now sometimes a list. → `refiner.py` already has a
  "multimodal — flatten to text where possible" branch; the trace writer records
  the text block and notes the image was elided. Verify both during build.
- **base64 PNG token cost** (~3 OpenAI tiles/turn): accepted for v1 at native
  resolution; downscaling deferred.

## Testing strategy

- **Renderer unit tests**: glyph path → base64 decodes to a 1264×336 PNG; tty
  path → valid PNG; both raise (not fall back) when their dep is monkeypatched
  absent; module imports with deps absent.
- **Formatter unit tests**: `include_map=False, include_local=False` omits
  MAP/UNDER/ADJACENT, keeps JOURNAL/STATUS/INVENTORY; defaults produce
  byte-identical output (golden compare on B1/B/G fixtures).
- **`_compose_user_content` unit tests**: str+prefix == legacy join; list+prefix
  prepends a text block; list no-prefix returns the list unchanged.
- **Integration**: IMG/IMG_TTY templates return a 2-element list (image_url +
  text); `env_response` wraps it into a UserMessage; existing variants still
  emit strings. Run the existing suite green.

## Out of scope

No reward/scoring changes; no new tools or skills; no image caching or
downscaling; no change to ASCII/BALROG/glyph-box rendered bytes.
