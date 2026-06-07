---
change: image-observation-renderer
design-doc: docs/superpowers/specs/2026-06-07-image-observation-renderer-design.md
base-ref: c218d6223651415a875b8158dabacb5612309d87
---

# Image-observation renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the harness deliver the NetHack observation as a rendered image (GlyphMapper tiles or tty-text raster) via two new variants, `IMG` and `IMG_TTY`.

**Architecture:** A new `image_render.py` converts `state["raw_obs"]` into a base64 PNG (lazy optional imports; strict fail-fast). Two new `VARIANT_REGISTRY` entries use an `_image_template` factory that emits an OpenAI-multimodal content list (`[image_url, text]`). `format_observation_as_chat` gains `include_map`/`include_local` gates so the IMG text block is journal+status+inventory only, with all existing variants byte-identical. `env_response` routes both return sites through a `_compose_user_content` helper that wraps `str | list`.

**Tech Stack:** Python, NLE 1.3.0, MiniHack `GlyphMapper`, PIL 10.0.1, numpy, pytest.

---

## Environment & test invocation (read first)

- Package lives at `environments/nethack/`. The importable top-level packages
  (`nethack_harness`, `nethack_core`) resolve when **cwd is
  `environments/nethack`** using the system `python` (which has numpy / nle /
  minihack / PIL). The repo-root `.venv` is just a symlink to that interpreter.
- **Canonical test command** (run from `environments/nethack`):
  ```bash
  cd environments/nethack
  python -m pytest ../../tests/<file> -p no:cacheprovider -q --no-header
  ```
  New test files go in the repo-root `tests/` directory.
- **Known-failing baseline (pre-existing, NOT caused by this change):** the full
  suite is 330 passed / 8 failed. 7 are test-isolation pollution from
  `test_integration.py` leaking global state into `test_rewards.py` +
  `test_integration::test_success_reward_zero_then_one` (each passes in
  isolation). The 8th is `test_hub_install::test_hub_install_e2e` (a packaging
  bug: `nethack.py:26` `from environments.nethack import harness_overlay`). None
  touch prompt/image rendering. **Verification rule for this plan:** every new
  test passes in isolation, every prompt/rendering test below passes, and the
  full-suite failure set remains a subset of those known 8.

## Key facts grounded in the codebase

- `state["raw_obs"]` may be an object (attrs `.glyphs`, `.tty_chars`,
  `.tty_colors`, `.chars`) or a dict; access defensively.
- `GlyphMapper().to_rgb(glyphs)` returns a `uint8` ndarray `(336, 1264, 3)` for
  a `(21, 79)` glyph grid.
- `turn_template` signature: `(structured, journal, state, *, compact,
  journal_max_chars) -> str | list`. It already receives `state`, so the image
  templates read `state["raw_obs"]` with no signature change.
- `env_response` return sites in `nethack.py`: the journal short-circuit
  (~line 503) and the main path (~line 890). Both currently do
  `vf.UserMessage(role="user", content=obs_text)`.

## File structure

- Create: `environments/nethack/nethack_harness/prompt/image_render.py`
- Modify: `environments/nethack/nethack_harness/prompt/rendering.py` (add
  `include_map` / `include_local` gates to `format_observation_as_chat`)
- Modify: `environments/nethack/nethack_harness/prompt/prompt_spec.py`
  (`_image_template` factory + `IMG` / `IMG_TTY` registry entries)
- Modify: `environments/nethack/nethack.py` (`_compose_user_content` + both
  return sites)
- Test (create): `tests/test_image_render.py`, `tests/test_image_variants.py`,
  `tests/test_compose_user_content.py`
- Test (touch/verify): `tests/test_obs_compaction.py`, `tests/test_balrog.py`

---

## Task 1: Image renderer module

**Files:**
- Create: `environments/nethack/nethack_harness/prompt/image_render.py`
- Test: `tests/test_image_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_image_render.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_image_render.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ModuleNotFoundError: No module named 'nethack_harness.prompt.image_render'`.

- [ ] **Step 3: Write minimal implementation**

```python
# environments/nethack/nethack_harness/prompt/image_render.py
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_image_render.py -p no:cacheprovider -q --no-header
```
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add environments/nethack/nethack_harness/prompt/image_render.py tests/test_image_render.py
git commit -m "feat(image-obs): add strict glyph/tty PNG renderer (image_render.py)"
```

---

## Task 2: include_map / include_local gates on the text formatter

**Files:**
- Modify: `environments/nethack/nethack_harness/prompt/rendering.py`
  (`format_observation_as_chat`, around lines 601–770)
- Test: `tests/test_image_variants.py` (formatter portion)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_image_variants.py  (formatter gates)
from __future__ import annotations

from nethack_harness.prompt.rendering import format_observation_as_chat
from nethack_harness.prompt.prompt_spec import VARIANT_REGISTRY  # used in Task 3


def _structured(make_structured_obs):
    # `make_structured_obs` is a helper fixture you build from an existing test's
    # construction of a StructuredObservation. If no fixture exists, construct the
    # smallest StructuredObservation the other rendering tests already use.
    return make_structured_obs()


def test_include_map_false_drops_map_block(make_structured_obs):
    s = make_structured_obs()
    full = format_observation_as_chat(s, None, None, compact=False)
    no_map = format_observation_as_chat(s, None, None, compact=False, include_map=False)
    assert "=== MAP ===" in full
    assert "=== MAP ===" not in no_map
    # status / inventory still present
    assert "=== STATUS ===" in no_map


def test_include_local_false_drops_local_blocks(make_structured_obs):
    s = make_structured_obs()
    no_local = format_observation_as_chat(
        s, None, None, compact=False, include_map=False, include_local=False
    )
    assert "=== ADJACENT ===" not in no_local
    assert "=== UNDER PLAYER ===" not in no_local


def test_defaults_unchanged(make_structured_obs):
    s = make_structured_obs()
    a = format_observation_as_chat(s, None, None, compact=False)
    b = format_observation_as_chat(
        s, None, None, compact=False, include_map=True, include_local=True
    )
    assert a == b  # defaults must be byte-identical
```

> **Note for the implementer:** if `make_structured_obs` does not already exist as
> a fixture, add a `conftest.py` in `tests/` that builds the same minimal
> `StructuredObservation` used by `tests/test_obs_compaction.py`. Reuse that
> construction verbatim — do not invent a new observation shape.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_image_variants.py -k formatter -p no:cacheprovider -q --no-header
```
Expected: FAIL — `format_observation_as_chat() got an unexpected keyword argument 'include_map'`.

- [ ] **Step 3: Write minimal implementation**

In `rendering.py`, change the signature and gate the relevant blocks:

```python
def format_observation_as_chat(
    structured,
    journal: Optional[Journal] = None,
    state: Optional[dict] = None,
    compact: bool = True,
    journal_max_chars: int = 2000,
    include_map: bool = True,
    include_local: bool = True,
) -> str:
```

Wrap the MAP section (the block starting `lines.append("=== MAP ===")` through
its trailing `lines.append("")`, including the E2 frontier-paint branch) in:

```python
    if include_map:
        lines.append("=== MAP ===")
        ...existing map code...
        lines.append("")
```

Wrap the UNDER-PLAYER, ADJACENT, and next-action-hint sections in
`if include_local:`. Leave JOURNAL, descent/E1 blocks, STATUS, and INVENTORY
unchanged. (The descent/E1 blocks are map-derived but gated by their own
`setup_flags`, which the IMG variants do not set, so they are already inert for
IMG — no extra gating needed.)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_image_variants.py -k formatter -p no:cacheprovider -q --no-header
# regression: existing rendering/compaction tests stay green
python -m pytest ../../tests/test_obs_compaction.py ../../tests/test_balrog.py -p no:cacheprovider -q --no-header
```
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add environments/nethack/nethack_harness/prompt/rendering.py tests/test_image_variants.py tests/conftest.py
git commit -m "feat(image-obs): add include_map/include_local gates to format_observation_as_chat"
```

---

## Task 3: IMG / IMG_TTY variants

**Files:**
- Modify: `environments/nethack/nethack_harness/prompt/prompt_spec.py`
- Test: `tests/test_image_variants.py` (variant portion)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_image_variants.py  (append)
import numpy as np

from nethack_harness.prompt.prompt_spec import VARIANT_REGISTRY


class _Obs:
    def __init__(self):
        self.glyphs = np.zeros((21, 79), dtype=np.int32)
        self.tty_chars = np.full((24, 80), ord(" "), dtype=np.uint8)
        self.tty_colors = np.zeros((24, 80), dtype=np.uint8)


def test_img_and_img_tty_registered():
    assert "IMG" in VARIANT_REGISTRY
    assert "IMG_TTY" in VARIANT_REGISTRY
    assert VARIANT_REGISTRY["IMG"].obs.mode == "img"
    assert VARIANT_REGISTRY["IMG_TTY"].obs.mode == "img"


def test_img_template_emits_multimodal_list(make_structured_obs):
    spec = VARIANT_REGISTRY["IMG"]
    state = {"raw_obs": _Obs()}
    content = spec.turn_template(
        make_structured_obs(), None, state, compact=True, journal_max_chars=2000
    )
    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["type"] == "text"
    # IMG text is journal+status+inventory only — no map/adjacent/under-player
    assert "=== MAP ===" not in content[1]["text"]
    assert "=== ADJACENT ===" not in content[1]["text"]
    assert "=== STATUS ===" in content[1]["text"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_image_variants.py -k "img" -p no:cacheprovider -q --no-header
```
Expected: FAIL — `KeyError: 'IMG'`.

- [ ] **Step 3: Write minimal implementation**

In `prompt_spec.py`, add an image-template factory near the other templates:

```python
def _image_template(render_name):
    """Per-turn template that returns a multimodal [image_url, text] content list.

    ``render_name`` selects the strict render path: "glyph" → GlyphMapper tiles,
    "tty" → tty-text raster. The text block is journal + status + inventory only
    (the image is the sole spatial channel).
    """

    def _render(structured, journal, state, *, compact, journal_max_chars):
        from nethack_harness.prompt.image_render import (
            glyphs_to_png_b64, tty_to_png_b64, to_data_uri,
        )
        from nethack_harness.prompt.rendering import format_observation_as_chat

        raw = state["raw_obs"]
        b64 = glyphs_to_png_b64(raw) if render_name == "glyph" else tty_to_png_b64(raw)
        text = format_observation_as_chat(
            structured, journal, state,
            compact=compact, journal_max_chars=journal_max_chars,
            include_map=False, include_local=False,
        )
        return [
            {"type": "image_url", "image_url": {"url": to_data_uri(b64)}},
            {"type": "text", "text": text},
        ]

    return _render
```

Add the registry entries inside `_build_registry`'s returned dict:

```python
        # Image observation: rendered tiles (IMG) or tty raster (IMG_TTY).
        "IMG": canonical("IMG", obs=ObsSpec(mode="img"),
                         turn_template=_image_template("glyph")),
        "IMG_TTY": canonical("IMG_TTY", obs=ObsSpec(mode="img"),
                             turn_template=_image_template("tty")),
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_image_variants.py -p no:cacheprovider -q --no-header
```
Expected: PASS (all formatter + variant tests).

- [ ] **Step 5: Commit**

```bash
git add environments/nethack/nethack_harness/prompt/prompt_spec.py tests/test_image_variants.py
git commit -m "feat(image-obs): register IMG and IMG_TTY multimodal variants"
```

---

## Task 4: env_response multimodal generalization

> **Revised approach (controller note, 2026-06-07):** the helper lives in a NEW
> leaf module `nethack_harness/prompt/content.py`, NOT inside `nethack.py`. Reason:
> `nethack.py:26` has an unguarded `from environments.nethack import
> harness_overlay`, so `import nethack` FAILS from the `environments/nethack` test
> cwd (the same packaging bug behind `test_hub_install`). Putting the pure helper
> in a leaf module makes it unit-testable in isolation with no heavy import, and
> is cleaner. `nethack.py` imports `compose_user_content` from there.

**Files:**
- Create: `environments/nethack/nethack_harness/prompt/content.py`
- Modify: `environments/nethack/nethack.py` (import + both env_response return
  sites ~503 and ~890)
- Test: `tests/test_compose_user_content.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compose_user_content.py
from __future__ import annotations

from nethack_harness.prompt.content import compose_user_content


def test_str_with_prefix_matches_legacy_join():
    out = compose_user_content("OBS", ["[a]", "[b]"])
    assert out == "[a]\n[b]\n\nOBS"


def test_str_without_prefix_unchanged():
    assert compose_user_content("OBS", []) == "OBS"


def test_list_with_prefix_prepends_text_block():
    obs = [{"type": "image_url", "image_url": {"url": "data:..."}},
           {"type": "text", "text": "STATUS"}]
    out = compose_user_content(obs, ["[a]", "[b]"])
    assert out[0] == {"type": "text", "text": "[a]\n[b]"}
    assert out[1:] == obs


def test_list_without_prefix_unchanged():
    obs = [{"type": "image_url", "image_url": {"url": "data:..."}},
           {"type": "text", "text": "STATUS"}]
    assert compose_user_content(obs, []) == obs
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd environments/nethack
python -m pytest ../../tests/test_compose_user_content.py -p no:cacheprovider -q --no-header
```
Expected: FAIL — `ModuleNotFoundError: No module named 'nethack_harness.prompt.content'`.

- [ ] **Step 3: Write minimal implementation**

Create `environments/nethack/nethack_harness/prompt/content.py`:

```python
"""Compose the per-turn user-message content.

The per-turn template returns either a string (text observation) or a multimodal
content list (image variants). ``compose_user_content`` injects the per-turn
prefix parts (autohalt / refiner / multi-tool / feedback notices) into either
shape so no prefix information is lost.
"""
from __future__ import annotations

from typing import Union

Content = Union[str, list]


def compose_user_content(obs: Content, prefix_parts: list) -> Content:
    """Wrap a string or multimodal-list observation, injecting prefix parts.

    String obs reproduce the legacy ``"\n".join(prefix) + "\n\n" + obs`` join.
    List obs get the prefix as a single leading ``{"type": "text"}`` block.
    """
    if isinstance(obs, str):
        if prefix_parts:
            return "\n".join(prefix_parts) + "\n\n" + obs
        return obs
    # multimodal content list
    if prefix_parts:
        return [{"type": "text", "text": "\n".join(prefix_parts)}, *obs]
    return obs


def content_to_text(obs: Content) -> str:
    """Extract the text form of a content value (for the trace writer)."""
    if isinstance(obs, str):
        return obs
    return next((p["text"] for p in obs if p.get("type") == "text"), "")
```

In `nethack.py`, add to the prompt imports near the top:
```python
from nethack_harness.prompt.content import compose_user_content, content_to_text
```

Rewire the **main return site** (~line 882–890). Replace:

```python
        if prefix_parts:
            obs_text = "\n".join(prefix_parts) + "\n\n" + obs_text
        # Per-turn trace ...
        _write_trace_entry(self, state, assistant_msg, tool_calls,
                           action_indices, total_reward, obs_text)
        return [vf.UserMessage(role="user", content=obs_text)]
```
with:
```python
        content = compose_user_content(obs_text, prefix_parts)
        # Per-turn trace ...
        _write_trace_entry(self, state, assistant_msg, tool_calls,
                           action_indices, total_reward, content_to_text(content))
        return [vf.UserMessage(role="user", content=content)]
```

Rewire the **journal short-circuit site** (~line 501–503). Replace:

```python
            if feedback:
                obs_text = f"[{feedback}]\n\n{obs_text}"
            return [vf.UserMessage(role="user", content=obs_text)]
```
with:
```python
            content = compose_user_content(obs_text, [f"[{feedback}]"] if feedback else [])
            return [vf.UserMessage(role="user", content=content)]
```

> **Note:** `content_to_text` replaces the inline trace-text extraction so the
> trace writer keeps receiving a string. Do not change the trace writer signature.
> Do NOT touch `nethack.py:26` / the `environments.nethack` import — that
> packaging bug is a separate roadmap "Base" item, not part of this task.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd environments/nethack
python -m pytest ../../tests/test_compose_user_content.py -p no:cacheprovider -q --no-header
```
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add environments/nethack/nethack.py tests/test_compose_user_content.py
git commit -m "feat(image-obs): generalize env_response to wrap str|list content"
```

---

## Task 5: Full verification + tasks.md sync

**Files:**
- Modify: `openspec/changes/image-observation-renderer/tasks.md` (check boxes)

- [ ] **Step 1: Run the new tests in isolation**

```bash
cd environments/nethack
python -m pytest ../../tests/test_image_render.py ../../tests/test_image_variants.py ../../tests/test_compose_user_content.py -p no:cacheprovider -q --no-header
```
Expected: PASS (all green).

- [ ] **Step 2: Run the prompt/rendering regression set**

```bash
cd environments/nethack
python -m pytest ../../tests/test_obs_compaction.py ../../tests/test_obs_e1_frontiers.py ../../tests/test_obs_e2_paint.py ../../tests/test_balrog.py ../../tests/test_history_compaction.py ../../tests/test_observations.py -p no:cacheprovider -q --no-header
```
Expected: PASS (these are the tests this change could affect; all must be green).

- [ ] **Step 3: Run the full suite and confirm no NEW failures**

```bash
cd environments/nethack
python -m pytest ../../tests -p no:cacheprovider -q --no-header 2>&1 | tail -15
```
Expected: failures are a **subset of the documented baseline 8**
(`test_hub_install_e2e`, `test_integration::test_success_reward_zero_then_one`,
6 × `test_rewards`). Passed count increases by the new tests. If any NEW test
fails, fix it before proceeding — do not absorb it into the baseline.

- [ ] **Step 4: Check off tasks.md**

Mark all boxes in `openspec/changes/image-observation-renderer/tasks.md` as
`- [x]` to match completed work.

- [ ] **Step 5: Commit**

```bash
git add openspec/changes/image-observation-renderer/tasks.md
git commit -m "chore(image-obs): mark tasks complete; verify feature green against baseline"
```

---

## Self-review notes

- **Spec coverage:** Task 1 → *Glyph-to-image rendering* (tile/tty/strict/import-without-deps). Task 3 → *IMG and IMG_TTY variants* (multimodal message, text omits spatial channels, existing variants unchanged via Task 2 defaults). Task 4 → *Multimodal-capable env response* (str+prefix / list+prefix / list no-prefix). All delta-spec requirements have a task.
- **Type consistency:** `glyphs_to_png_b64` / `tty_to_png_b64` / `to_data_uri` names match across Tasks 1, 3. `_image_template("glyph"|"tty")` matches its registry callers. `format_observation_as_chat(..., include_map, include_local)` matches Tasks 2, 3. `_compose_user_content(obs, prefix_parts)` matches Task 4 call sites.
- **Strict semantics:** no cross-fallback anywhere; the glyph path raises on missing minihack (Task 1 test asserts this).
