"""Input-validation regression tests for the play-server routes.

These lock in the "malformed input is a clean 400, never an uncaught 500"
contract for the play routes (/reset /step /live /set_tune /modify). They are
engine-free: the validation paths exercised here all return before any
EngineEnv call, and the no-engine guards are tested with STATE['env'] forced
to None (it is a module global other tests may have populated).

Complements test_obs_creator.py, which covers the /obs/plot validation.
"""
from __future__ import annotations

import json

import pytest

import tools.play_server as ps


@pytest.fixture()
def client():
    ps.app.config["TESTING"] = True
    return ps.app.test_client()


@pytest.fixture()
def no_engine():
    """Force the shared env to None so the 'call /reset first' guards fire."""
    saved = ps.STATE["env"]
    ps.STATE["env"] = None
    try:
        yield
    finally:
        ps.STATE["env"] = saved


def _err(r):
    return r.status_code, (r.get_json() or {}).get("error")


# --- /trace tolerates a malformed trace file (no 500) -------------------------
def test_trace_skips_non_object_and_bad_lines(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "_TRACE_DIRS", [tmp_path])
    tp = tmp_path / "malformed.ndjson"
    tp.write_text("\n".join([
        json.dumps({"turn": 0, "status": {"dlvl": 1}}),
        "[1, 2, 3]",      # valid JSON, not an object -> must be skipped, not 500
        '"a string"',     # valid JSON scalar
        "42",
        "null",
        "{bad json",      # invalid JSON
        json.dumps({"turn": 5, "status": {"dlvl": 2}}),
    ]))
    r = client.get("/trace?path=" + str(tp.resolve()))
    assert r.status_code == 200
    turns = r.get_json()["turns"]
    assert [t["turn"] for t in turns] == [0, 5]  # only the two valid objects


# --- /set_tune validation runs before the engine, so it's testable directly ---
def test_set_tune_missing_value_is_400(client):
    code, err = _err(client.post("/set_tune", json={"name": "vision_radius"}))
    assert code == 400 and "number" in err


def test_set_tune_non_string_name_is_400(client):
    code, _ = _err(client.post("/set_tune", json={"name": 123, "value": 1}))
    assert code == 400


def test_set_tune_non_numeric_value_is_400(client):
    code, _ = _err(client.post("/set_tune", json={"name": "vision_radius", "value": "abc"}))
    assert code == 400


# --- /step validates keys shape before the engine, so it's testable directly ---
def test_step_non_string_keys_is_400(client):
    # A non-string `keys` would make `for ch in keys` / ord() raise -> 500.
    # The shape check runs before the engine guard, so no live engine is needed.
    code, err = _err(client.post("/step", json={"keys": 123}))
    assert code == 400 and "string" in (err or "").lower()


# --- no-engine guards: these must 400, never 500 -----------------------------
@pytest.mark.parametrize("path,body", [
    ("/step", {"keys": "h"}),
    ("/live", {"name": "vision_radius", "value": 1}),
    ("/modify", {"changes": {"hp": 5}}),
])
def test_play_routes_without_engine_are_400(client, no_engine, path, body):
    code, err = _err(client.post(path, json=body))
    assert code == 400 and "reset" in (err or "").lower()


# --- /reset validates seed + tune before constructing the engine -------------
def test_reset_bad_seed_is_400(client):
    code, err = _err(client.post("/reset", json={"seed": "not-an-int"}))
    assert code == 400 and "seed" in err


def test_reset_bad_tune_value_is_400(client):
    code, err = _err(client.post("/reset", json={"seed": 1, "tune": {"vision_radius": "x"}}))
    assert code == 400 and "tune" in err


# --- knob metadata invariants (engine-free; pure _META/_GROUPS config) --------
def test_every_meta_group_is_a_known_group():
    # A typo'd group would render a knob under a heading that doesn't exist.
    for name, m in ps._META.items():
        assert m["group"] in ps._GROUPS, f"{name} has unknown group {m['group']!r}"


def test_generation_knobs_grouped_under_dungeon_and_reset():
    # Regression: these floor-generation knobs once fell back to _DEFAULT_META
    # and rendered under 'Stat-based'. They reshape the floor, so they belong in
    # 'Dungeon & spawns' and must be reset knobs.
    for name in ("mob_spawn", "trap_density", "locked_door",
                 "corridor_connectivity", "room_size"):
        assert ps._META[name]["group"] == "Dungeon & spawns"
        assert ps._META[name]["reset"] is True


def test_reset_unknown_tune_knob_is_400(client):
    # An unknown knob name in the tune dict must be a clean 400 (the engine's
    # set_tune raises KeyError during reset), not an uncaught 500.
    code, err = _err(client.post("/reset", json={"seed": 1, "tune": {"bogus_knob": 1.0}}))
    assert code == 400 and "bogus_knob" in (err or "")


# --- /trace coerces field types from foreign/malformed traces -----------------
def test_trace_coerces_nonnumeric_reward_and_bad_field_types(client, tmp_path, monkeypatch):
    """The Tracer loads ANY .ndjson under the trace dirs, so a foreign trace may
    carry a string `reward` or a non-list `messages`. The client does
    reward.toFixed() / messages.join(), which throw on the wrong type. /trace
    must normalize: numeric reward, list messages/raw_grid, dict status."""
    monkeypatch.setattr(ps, "_TRACE_DIRS", [tmp_path])
    tp = tmp_path / "foreign.ndjson"
    tp.write_text("\n".join([
        json.dumps({"turn": 0, "reward": "1.5", "messages": "hello",
                    "status": "notadict", "raw_grid": "xx", "tool_calls": 7}),
        json.dumps({"turn": 1, "reward": None}),
    ]))
    r = client.get("/trace?path=" + str(tp.resolve()))
    assert r.status_code == 200
    t0, t1 = r.get_json()["turns"]
    assert isinstance(t0["reward"], float) and t0["reward"] == 1.5
    assert t0["messages"] == [] and t0["raw_grid"] == [] and t0["tool_calls"] == []
    assert t0["status"] == {}
    assert t1["reward"] == 0.0  # None -> 0.0, never a crash


# --- _trace_allowed callers must 400 (not 500) on a non-string path -----------
def test_resume_nonstring_checkpoint_is_400(client, no_engine):
    """A foreign trace could carry a non-string `checkpoint`; /resume forwards it
    to _trace_allowed -> pathlib.Path(), which would raise on a non-str. Must be
    a clean 400 (the allow-list check runs before the engine, so no env needed)."""
    code, _ = _err(client.post("/resume", json={"checkpoint": 12345}))
    assert code == 400


def test_obs_plot_nonstring_path_is_400(client):
    """Client-supplied paths flow into _trace_allowed; a non-string must 400."""
    code, err = _err(client.post("/obs/plot",
                                 json={"paths": [12345], "metrics": ["dlvl"], "custom": []}))
    assert code == 400


# --- /modify validates shape + value types before the engine -----------------
def test_modify_nondict_changes_is_400(client):
    code, err = _err(client.post("/modify", json={"changes": [1, 2, 3]}))
    assert code == 400 and "object" in (err or "")


def test_modify_noninteger_change_value_is_400(client):
    # int(None) / int([..]) raise TypeError (not ValueError) -> was an uncaught 500.
    for bad in (None, [1], {"x": 1}):
        code, _ = _err(client.post("/modify", json={"changes": {"hp": bad}}))
        assert code == 400, f"changes hp={bad!r} should be 400"


# --- /current must not 500 when an env exists but no game is started ----------
def test_current_unstarted_env_is_200_live_false(client, monkeypatch):
    """/catalog lazily builds an env (to read the knob list) before the page's
    first /reset, so on a cold load /current sees a non-None but unstarted env.
    Reading a frame then raises 'requires an active game' — /current must treat
    that as no live game (200, live:false) so the page resets, not 500."""
    class _Engine:
        def to_core_observation(self):
            raise RuntimeError("get_tune() requires an active game; call start() first")
    class _Env:
        engine = _Engine()
    monkeypatch.setitem(ps.STATE, "env", _Env())
    monkeypatch.setitem(ps.STATE, "resumed", False)
    r = client.get("/current")
    assert r.status_code == 200
    assert r.get_json().get("live") is False


# --- play routes must gate on "started", not just env!=None (unstarted = crash) -
def test_play_routes_reject_unstarted_env(client, monkeypatch):
    """An env can exist without a started game: /catalog lazily builds one to read
    the knob list. Engine ops (step/modify/live) on an unstarted game crash the C
    library, so they must 400 based on STATE['started'], not just env-None. A
    page-load race (typing before the first /reset finishes) could otherwise crash
    the server."""
    monkeypatch.setitem(ps.STATE, "env", object())   # non-None but unstarted
    monkeypatch.setitem(ps.STATE, "started", False)
    for path, body in [("/step", {"keys": "l"}),
                       ("/live", {"name": "vision_radius", "value": 1}),
                       ("/modify", {"changes": {"hp": 5}})]:
        code, err = _err(client.post(path, json=body))
        assert code == 400 and "reset" in (err or "").lower(), f"{path} must 400 when unstarted"


# --- curriculum mode + /curriculum/goto -------------------------------------
def test_curriculum_reset_reports_floor(client):
    """reset with mode=curriculum starts the tour env and reports curriculum_floor."""
    r = client.post("/reset", json={"seed": 19, "mode": "curriculum"}).get_json()
    assert r["mode"] == "curriculum"
    assert r["curriculum_floor"] == 1
    assert r["curriculum_floor_name"] == "DoD 1"


def test_curriculum_goto_places_hero_deep(client):
    client.post("/reset", json={"seed": 19, "mode": "curriculum"})
    r = client.post("/curriculum/goto", json={"floor": 4}).get_json()
    assert r["curriculum_floor"] == 4
    assert r["status"]["dlvl"] == 48  # Gehennom 48


def test_curriculum_goto_bad_floor_is_400(client):
    client.post("/reset", json={"seed": 19, "mode": "curriculum"})
    assert client.post("/curriculum/goto", json={"floor": 9}).status_code == 400
    assert client.post("/curriculum/goto", json={"floor": "x"}).status_code == 400


def test_curriculum_goto_in_standard_mode_is_400(client):
    client.post("/reset", json={"seed": 42, "mode": "standard"})
    r = client.post("/curriculum/goto", json={"floor": 3})
    assert r.status_code == 400
    assert "curriculum mode" in (r.get_json() or {}).get("error", "")


def test_reset_unknown_mode_is_400(client):
    assert client.post("/reset", json={"mode": "banana"}).status_code == 400


def test_standard_mode_has_no_curriculum_floor(client):
    r = client.post("/reset", json={"seed": 42, "mode": "standard"}).get_json()
    assert r["mode"] == "standard"
    assert "curriculum_floor" not in r
