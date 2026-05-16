"""
Tests for the wiki module: lookup, substring search, ranking, index swap.

Run with: uv run pytest tests/test_wiki.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nethack_core.wiki import WikiIndex, WikiPage, get_index, reload_default_index, set_index


def test_default_index_has_seed_pages():
    """The dev-time default index must contain the high-value pages."""
    idx = WikiIndex.default()
    for title in ("cockatrice", "mine town", "sokoban", "oracle", "elbereth", "altar"):
        assert idx.lookup(title) is not None


def test_lookup_is_case_insensitive():
    idx = WikiIndex.default()
    assert idx.lookup("Cockatrice") is not None
    assert idx.lookup("MINE TOWN") is not None


def test_lookup_returns_none_on_unknown():
    idx = WikiIndex.default()
    assert idx.lookup("not-a-real-page") is None


def test_search_ranks_title_match_above_body_match():
    """Searches that hit the title should outrank body-only hits."""
    idx = WikiIndex(pages=[
        WikiPage(title="dragon", body="A large mythical creature."),
        WikiPage(title="kobold", body="Easily killed by a dragon."),
        WikiPage(title="newt", body="Smallest monster."),
    ])
    hits = idx.search("dragon", k=3)
    assert hits[0].title == "dragon"
    # 'kobold' contains 'dragon' in its body so should also rank.
    titles = [h.title for h in hits]
    assert "kobold" in titles


def test_search_empty_query_returns_empty_list():
    assert WikiIndex.default().search("", k=5) == []


def test_search_respects_k():
    idx = WikiIndex.default()
    # 'a' is a very common substring; should still cap at k=2.
    assert len(idx.search("a", k=2)) <= 2


def test_from_json_roundtrip(tmp_path):
    raw = [{"title": "foo", "body": "bar baz"}]
    p = tmp_path / "wiki.json"
    p.write_text(json.dumps(raw))
    idx = WikiIndex.from_json(p)
    assert idx.lookup("foo").body == "bar baz"


def test_set_index_swaps_global_singleton():
    """Hot-swapping the global index lets the wiki skills point at a new corpus."""
    original = get_index()
    try:
        new_idx = WikiIndex(pages=[WikiPage(title="custom", body="custom body")])
        set_index(new_idx)
        assert get_index().lookup("custom") is not None
        # The original default's pages are no longer in the new singleton.
        assert get_index().lookup("cockatrice") is None
    finally:
        set_index(original)


def test_page_short_truncates_with_ellipsis():
    p = WikiPage(title="x", body="a" * 500)
    out = p.short(max_chars=100)
    assert len(out) <= 101  # 100 chars + ellipsis
    assert out.endswith("…")


def test_bundled_snapshot_auto_loads():
    """If wiki/snapshot.json exists in the workspace, the default index
    auto-loads from it (102+ pages) instead of the 6-page stub."""
    from pathlib import Path
    workspace_snap = Path(__file__).resolve().parents[1] / "wiki" / "snapshot.json"
    if not workspace_snap.exists():
        import pytest as _pt
        _pt.skip("wiki/snapshot.json not present — run tools/build_wiki_index.py first")
    idx = reload_default_index()
    assert len(idx._pages) >= 50, f"snapshot found but only {len(idx._pages)} pages loaded"
    # A few entries from the expanded list should be present.
    for title in ("cockatrice", "elbereth", "valkyrie"):
        assert idx.lookup(title) is not None, f"missing {title}"


def test_reload_default_index_returns_index():
    idx = reload_default_index()
    assert isinstance(idx, WikiIndex)
