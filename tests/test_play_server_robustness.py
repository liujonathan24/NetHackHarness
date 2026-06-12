"""Input-validation regression tests for the play-server routes.

These lock in the "malformed input is a clean 400, never an uncaught 500"
contract for the play routes (/reset /step /live /set_tune /modify). They are
engine-free: the validation paths exercised here all return before any
EngineEnv call, and the no-engine guards are tested with STATE['env'] forced
to None (it is a module global other tests may have populated).

Complements test_obs_creator.py, which covers the /obs/plot validation.
"""
from __future__ import annotations

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
