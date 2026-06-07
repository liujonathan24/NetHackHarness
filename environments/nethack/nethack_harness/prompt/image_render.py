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
from typing import Any

# Cache the (expensive) GlyphMapper instance across calls.
_GLYPH_MAPPER = None

# NLE tty 16-colour palette (xterm-ish), indexed by tty_colors value & 0x0F.
_TTY_PALETTE = [
    (0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0),
    (0, 0, 170), (170, 0, 170), (0, 170, 170), (170, 170, 170),
    (85, 85, 85), (255, 85, 85), (85, 255, 85), (255, 255, 85),
    (85, 85, 255), (255, 85, 255), (85, 255, 255), (255, 255, 255),
]


def _reset_caches_for_test() -> None:
    """Test hook: drop the cached GlyphMapper so a forced ImportError re-triggers."""
    global _GLYPH_MAPPER
    _GLYPH_MAPPER = None


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


def glyphs_to_png_b64(raw_obs: Any) -> str:
    """Render ``raw_obs.glyphs`` as GlyphMapper tiles → base64 PNG. Strict."""
    import numpy as np  # lazy

    glyphs = np.asarray(_attr(raw_obs, "glyphs"), dtype=np.int32)
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
