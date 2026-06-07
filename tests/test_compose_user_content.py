from __future__ import annotations

from nethack_harness.prompt.content import compose_user_content, content_to_text


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


def test_content_to_text_string_passthrough():
    assert content_to_text("OBS") == "OBS"


def test_content_to_text_joins_all_text_blocks():
    # A composed list with a leading prefix block + the status block: the trace
    # text must keep BOTH (image entry elided).
    obs = [{"type": "text", "text": "[a]\n[b]"},
           {"type": "image_url", "image_url": {"url": "data:..."}},
           {"type": "text", "text": "STATUS"}]
    assert content_to_text(obs) == "[a]\n[b]\nSTATUS"
