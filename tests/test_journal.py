"""
Tests for the Journal: keyed note store, recall by substring, objective pinning.

Run with: uv run pytest tests/test_journal.py -v
"""

from __future__ import annotations

from nethack_harness.memory.journal import Journal


def test_journal_starts_empty():
    j = Journal()
    assert j.is_empty()
    assert j.render() == ""


def test_add_note_returns_added_then_updated():
    j = Journal()
    assert "added" in j.add_note("altar", "found a holy altar on dlvl 4")
    assert "updated" in j.add_note("altar", "altar was on dlvl 4, used it")


def test_add_note_strips_whitespace_and_lowercases_key():
    j = Journal()
    j.add_note("  Altar  ", "  holy on dlvl 4  ")
    assert "altar" in j.notes
    assert j.notes["altar"] == "holy on dlvl 4"


def test_add_note_refuses_empty_key():
    j = Journal()
    out = j.add_note("   ", "some text")
    assert "Refused" in out
    assert j.is_empty()


def test_recall_returns_all_when_query_empty():
    j = Journal()
    j.add_note("altar", "holy on dlvl 4")
    j.add_note("dragon", "killed on dlvl 7")
    out = j.recall("")
    assert sorted(out) == sorted([("altar", "holy on dlvl 4"), ("dragon", "killed on dlvl 7")])


def test_recall_matches_by_key_or_text_substring_case_insensitive():
    j = Journal()
    j.add_note("altar", "holy on dlvl 4")
    j.add_note("dragon", "killed on dlvl 7")
    j.add_note("shopkeeper", "angry, avoid dlvl 5")

    by_key = j.recall("DRAGON")
    assert by_key == [("dragon", "killed on dlvl 7")]

    by_text = j.recall("dlvl 4")
    assert by_text == [("altar", "holy on dlvl 4")]

    # No matches → empty list, not None.
    assert j.recall("kraken") == []


def test_pin_objective_replaces_previous():
    j = Journal()
    out = j.pin_objective("find stairs")
    assert "set" in out
    out = j.pin_objective("kill the kobold first")
    assert "updated" in out
    assert j.objective == "kill the kobold first"


def test_render_combines_objective_and_notes():
    j = Journal()
    j.pin_objective("reach dlvl 5")
    j.add_note("altar", "holy on dlvl 4")
    rendered = j.render()
    assert "Objective: reach dlvl 5" in rendered
    assert "altar: holy on dlvl 4" in rendered


def test_render_objective_only_no_notes():
    j = Journal()
    j.pin_objective("survive")
    assert "Objective: survive" in j.render()
    assert "Your notes:" not in j.render()


def test_render_notes_only_no_objective():
    j = Journal()
    j.add_note("k", "v")
    rendered = j.render()
    assert "Your notes:" in rendered
    assert "Objective:" not in rendered


def test_render_caps_at_max_chars():
    """Adding 200 notes of 100 chars each is ~20KB; render must cap that."""
    j = Journal()
    j.pin_objective("survive")
    for i in range(200):
        j.add_note(f"note_{i:03d}", "x" * 100)
    rendered = j.render(max_chars=2000)
    # The cap is soft (we may include the elision marker line) — give some slack.
    assert len(rendered) <= 2500, f"render ignored max_chars: {len(rendered)} chars"
    assert "Objective: survive" in rendered  # objective always kept
    assert "elided" in rendered


def test_render_pins_belief_state_notes_through_cap():
    """belief_state:tN notes are the agent's long-term memory; cap must keep them."""
    j = Journal()
    for i in range(50):
        j.add_note(f"junk_{i}", "x" * 100)
    j.add_note("belief_state:t25", "the agent is in a corridor near a fountain")
    for i in range(50):
        j.add_note(f"more_{i}", "x" * 100)
    rendered = j.render(max_chars=1500)
    assert "belief_state:t25" in rendered, "belief_state note was dropped by the cap"


def test_render_uncapped_for_small_journals():
    """Cap should be a no-op when the journal is already small."""
    j = Journal()
    j.add_note("a", "short")
    j.add_note("b", "also short")
    rendered = j.render(max_chars=2000)
    assert "a: short" in rendered
    assert "b: also short" in rendered
    assert "elided" not in rendered


def test_recall_finds_pinned_objective():
    """v0.0.55: recall includes the pinned objective under key 'objective'."""
    from nethack_harness.memory.journal import Journal
    j = Journal()
    j.pin_objective("Reach dungeon level 2 by finding stairs DOWN")
    hits = j.recall("objective")
    assert ("objective", "Reach dungeon level 2 by finding stairs DOWN") in hits
    # Substring match in objective text:
    hits = j.recall("descend")
    # The objective doesn't contain 'descend', so this matches the more
    # directive corridor_explore description, not this fixture. Let's
    # use a substring that IS in the fixture:
    hits = j.recall("stairs")
    assert any(k == "objective" for k, _ in hits)


def test_recall_empty_query_returns_objective_plus_notes():
    from nethack_harness.memory.journal import Journal
    j = Journal()
    j.pin_objective("Find the amulet")
    j.add_note("loc1", "Mines entrance at dlvl 3")
    hits = j.recall("")
    keys = [k for k, _ in hits]
    assert "objective" in keys
    assert "loc1" in keys
