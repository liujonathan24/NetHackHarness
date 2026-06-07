from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from PIL import Image

from nethack_harness.prompt import image_render


class _Obs:
    """Minimal raw_obs stand-in with the attributes the renderer reads."""
    def __init__(self, glyphs, tty_chars, tty_colors):
        self.glyphs = glyphs
        self.tty_chars = tty_chars
        self.tty_colors = tty_colors


def _blank_obs():
    glyphs = np.zeros((21, 79), dtype=np.int32)
    tty_chars = np.full((24, 80), ord(" "), dtype=np.uint8)
    tty_colors = np.zeros((24, 80), dtype=np.uint8)
    return _Obs(glyphs, tty_chars, tty_colors)


def _decode_png(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64)))


def test_glyphs_to_png_b64_is_1264x336():
    b64 = image_render.glyphs_to_png_b64(_blank_obs())
    img = _decode_png(b64)
    assert img.format == "PNG"
    assert img.size == (1264, 336)  # (width, height)


def test_tty_to_png_b64_returns_valid_png():
    b64 = image_render.tty_to_png_b64(_blank_obs())
    img = _decode_png(b64)
    assert img.format == "PNG"
    assert img.size[0] > 0 and img.size[1] > 0


def test_to_data_uri_prefix():
    uri = image_render.to_data_uri("QUJD")
    assert uri == "data:image/png;base64,QUJD"


def test_dict_obs_supported():
    o = _blank_obs()
    d = {"glyphs": o.glyphs, "tty_chars": o.tty_chars, "tty_colors": o.tty_colors}
    assert image_render.glyphs_to_png_b64(d).startswith  # callable, no raise
    image_render.tty_to_png_b64(d)


def test_glyph_path_strict_raises_without_minihack(monkeypatch):
    # Force the GlyphMapper import to fail; strict path must raise, not fall back.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("minihack"):
            raise ImportError("forced: no minihack")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    image_render._reset_caches_for_test()
    with pytest.raises((ImportError, RuntimeError)):
        image_render.glyphs_to_png_b64(_blank_obs())
