"""Configurable IMG tileset: swap the GlyphMapper art for any sprite sheet laid
out in the canonical NetHack tile order (https://nethackwiki.com/wiki/Tileset)."""
import base64
import io

import numpy as np
import nle.nethack as N
from PIL import Image

from nethack_harness.prompt import image_render as IR


class _Raw:
    def __init__(self):
        g = np.full((21, 79), N.GLYPH_CMAP_OFF, np.int32)
        g[5, 10] = N.GLYPH_MON_OFF + 20  # a monster glyph
        self.glyphs = g


def _png_to_arr(b64: str):
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB"))


def _make_sheet(tmp_path, tile_size=16, per_row=40, rows=37):
    """A synthetic sheet whose tile i encodes its own index in its pixels."""
    sheet = np.zeros((rows * tile_size, per_row * tile_size, 3), np.uint8)
    for i in range(rows * per_row):
        r, c = divmod(i, per_row)
        sheet[r * tile_size:(r + 1) * tile_size, c * tile_size:(c + 1) * tile_size] = (
            i % 256, (i // 256) % 256, 123)
    p = tmp_path / "sheet.png"
    Image.fromarray(sheet).save(p)
    return str(p)


def _expected_color(tid):
    return (tid % 256, (tid // 256) % 256, 123)


def test_default_renders_builtin_tiles_at_16px():
    IR._reset_caches_for_test(); IR.set_tileset(None)
    arr = _png_to_arr(IR.glyphs_to_png_b64(_Raw()))
    assert arr.shape == (21 * 16, 79 * 16, 3)  # MiniHack 16px tiles


def test_custom_tileset_arg_is_used():
    from minihack.tiles import glyph2tile
    IR._reset_caches_for_test()
    import tempfile, pathlib
    sheet = _make_sheet(pathlib.Path(tempfile.mkdtemp()))
    raw = _Raw()
    arr = _png_to_arr(IR.glyphs_to_png_b64(raw, tileset=sheet, tile_size=16))
    tid = int(glyph2tile[int(raw.glyphs[5, 10])])  # the monster cell's tile
    px = tuple(int(v) for v in arr[5 * 16 + 8, 10 * 16 + 8][:3])  # cell center
    assert px == _expected_color(tid)


def test_set_tileset_and_revert():
    from minihack.tiles import glyph2tile
    import tempfile, pathlib
    sheet = _make_sheet(pathlib.Path(tempfile.mkdtemp()))
    IR._reset_caches_for_test()
    IR.set_tileset(sheet, tile_size=16)
    try:
        raw = _Raw()
        arr = _png_to_arr(IR.glyphs_to_png_b64(raw))
        tid = int(glyph2tile[int(raw.glyphs[5, 10])])
        assert tuple(int(v) for v in arr[5 * 16 + 8, 10 * 16 + 8][:3]) == _expected_color(tid)
    finally:
        IR.set_tileset(None)
    # reverted → built-in tiles again
    IR._reset_caches_for_test()
    assert _png_to_arr(IR.glyphs_to_png_b64(_Raw())).shape == (21 * 16, 79 * 16, 3)


def test_env_var_selects_tileset(monkeypatch):
    from minihack.tiles import glyph2tile
    import tempfile, pathlib
    sheet = _make_sheet(pathlib.Path(tempfile.mkdtemp()))
    monkeypatch.setenv("NETHACK_TILESET", sheet)
    monkeypatch.setenv("NETHACK_TILESET_SIZE", "16")
    IR._reset_caches_for_test()
    raw = _Raw()
    arr = _png_to_arr(IR.glyphs_to_png_b64(raw))
    tid = int(glyph2tile[int(raw.glyphs[5, 10])])
    assert tuple(int(v) for v in arr[5 * 16 + 8, 10 * 16 + 8][:3]) == _expected_color(tid)
