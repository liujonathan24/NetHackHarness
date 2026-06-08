"""Render an NLE observation as a base64 PNG.

Two explicit, strict render paths:

- :func:`glyphs_to_png_b64` — MiniHack ``GlyphMapper`` tiles over ``raw_obs.glyphs``.
- :func:`tty_to_png_b64` — a PIL raster of ``raw_obs.tty_chars`` / ``tty_colors``.

Optional deps (``minihack``, ``PIL``) are imported lazily so this module imports
cleanly where they are absent. Each path FAILS FAST: if its dependency is missing
or rendering raises, it raises — it never silently substitutes the other path.
"""
from __future__ import annotations

import base64
import io
import os
from typing import Any

# Cache the (expensive) GlyphMapper instance across calls.
_GLYPH_MAPPER = None

# Optional custom tileset. A sprite sheet (any tile size) laid out row-major in
# the canonical NetHack tile order — the same order MiniHack's built-in tiles
# use, so the existing glyph->tile mapping (`glyph2tile`) applies unchanged.
# Select one via set_tileset(...) or the NETHACK_TILESET env var (with optional
# NETHACK_TILESET_SIZE, default 16). When none is set, the built-in tiles render.
# See https://nethackwiki.com/wiki/Tileset for the format.
_TILESET_OVERRIDE = None    # (path, tile_size) from set_tileset(); beats env
_CUSTOM_TILES = None        # cached tiles ndarray (n, ts, ts, 3)
_CUSTOM_TILES_KEY = None    # (path, tile_size) the cache was built for


def set_tileset(path, tile_size: int = 16) -> None:
    """Globally select a custom tileset sprite sheet (canonical NetHack tile
    order, row-major). ``path=None`` reverts to the built-in MiniHack tiles."""
    global _TILESET_OVERRIDE
    _TILESET_OVERRIDE = (str(path), int(tile_size)) if path else None


def _resolve_tileset(tileset, tile_size):
    """Resolve the active tileset: explicit arg > set_tileset() > env > built-in."""
    if tileset:
        return str(tileset), int(tile_size or 16)
    if _TILESET_OVERRIDE:
        return _TILESET_OVERRIDE
    env = os.environ.get("NETHACK_TILESET")
    if env:
        return env, int(os.environ.get("NETHACK_TILESET_SIZE", "16"))
    return None, 16


def _custom_tiles(path: str, tile_size: int):
    """Crop a sprite sheet into a tile_id-indexed array (row-major). Cached."""
    global _CUSTOM_TILES, _CUSTOM_TILES_KEY
    if _CUSTOM_TILES_KEY != (path, tile_size):
        import numpy as np  # lazy
        from PIL import Image  # lazy

        sheet = np.asarray(Image.open(path).convert("RGB"))
        per_row = sheet.shape[1] // tile_size
        rows = sheet.shape[0] // tile_size
        tiles = np.empty((rows * per_row, tile_size, tile_size, 3), np.uint8)
        for i in range(rows * per_row):
            r, c = divmod(i, per_row)
            tiles[i] = sheet[r * tile_size:(r + 1) * tile_size,
                             c * tile_size:(c + 1) * tile_size]
        _CUSTOM_TILES, _CUSTOM_TILES_KEY = tiles, (path, tile_size)
    return _CUSTOM_TILES


def _render_with_tiles(glyphs, tiles, tile_size: int):
    """Compose the glyph grid from a custom tile array via the glyph->tile map."""
    import numpy as np  # lazy
    from minihack.tiles import glyph2tile  # lazy

    h, w = glyphs.shape
    img = np.zeros((h * tile_size, w * tile_size, 3), np.uint8)
    n = len(tiles)
    for j in range(h):
        for i in range(w):
            tid = int(glyph2tile[int(glyphs[j, i])])
            if tid < n:  # guard sheets that lack high tile_ids
                img[j * tile_size:(j + 1) * tile_size,
                    i * tile_size:(i + 1) * tile_size] = tiles[tid]
    return img

# NLE tty 16-colour palette (xterm-ish), indexed by tty_colors value & 0x0F.
_TTY_PALETTE = [
    (0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0),
    (0, 0, 170), (170, 0, 170), (0, 170, 170), (170, 170, 170),
    (85, 85, 85), (255, 85, 85), (85, 255, 85), (255, 255, 85),
    (85, 85, 255), (255, 85, 255), (85, 255, 255), (255, 255, 255),
]


def _reset_caches_for_test() -> None:
    """Test hook: drop cached tiles so a forced ImportError / tileset swap re-triggers."""
    global _GLYPH_MAPPER, _CUSTOM_TILES, _CUSTOM_TILES_KEY
    _GLYPH_MAPPER = None
    _CUSTOM_TILES = None
    _CUSTOM_TILES_KEY = None


def _attr(obs: Any, name: str):
    """Read ``name`` from an obs that may be an object or a dict."""
    if isinstance(obs, dict):
        return obs[name]
    return getattr(obs, name)


def _png_b64(arr) -> str:
    """Encode an (H, W, 3) uint8 ndarray as a base64 PNG string."""
    from PIL import Image  # lazy

    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _glyph_mapper():
    global _GLYPH_MAPPER
    if _GLYPH_MAPPER is None:
        from minihack.tiles.glyph_mapper import GlyphMapper  # lazy, may raise

        _GLYPH_MAPPER = GlyphMapper()
    return _GLYPH_MAPPER


def glyphs_to_png_b64(raw_obs: Any, *, tileset=None, tile_size=None) -> str:
    """Render ``raw_obs.glyphs`` as tiles → base64 PNG. Strict.

    Uses the active custom tileset (``tileset`` arg > ``set_tileset()`` >
    ``NETHACK_TILESET`` env) when one is set; otherwise the built-in MiniHack
    ``GlyphMapper`` tiles."""
    import numpy as np  # lazy

    glyphs = np.asarray(_attr(raw_obs, "glyphs"), dtype=np.int32)
    path, ts = _resolve_tileset(tileset, tile_size)
    if path:
        rgb = _render_with_tiles(glyphs, _custom_tiles(path, ts), ts)
    else:
        rgb = _glyph_mapper().to_rgb(glyphs)  # (H, W, 3) uint8
    return _png_b64(np.asarray(rgb, dtype="uint8"))


def tty_to_png_b64(raw_obs: Any, *, cell_w: int = 9, cell_h: int = 16) -> str:
    """Render ``raw_obs.tty_chars`` / ``tty_colors`` as a PIL raster → base64 PNG. Strict."""
    import numpy as np  # lazy
    from PIL import Image, ImageDraw, ImageFont  # lazy

    chars = np.asarray(_attr(raw_obs, "tty_chars"), dtype=np.uint8)
    colors = np.asarray(_attr(raw_obs, "tty_colors"), dtype=np.uint8)
    rows, cols = chars.shape
    img = Image.new("RGB", (cols * cell_w, rows * cell_h), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    for r in range(rows):
        for c in range(cols):
            ch = chr(int(chars[r, c]))
            if ch == " ":
                continue
            color = _TTY_PALETTE[int(colors[r, c]) & 0x0F]
            draw.text((c * cell_w, r * cell_h), ch, fill=color, font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def to_data_uri(b64: str) -> str:
    """Wrap a base64 PNG string in an ``image/png`` data URI."""
    return f"data:image/png;base64,{b64}"
