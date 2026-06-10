from nethack_core import _engine


def test_library_loads():
    lib = _engine.load_library()
    assert lib is not None
    # Public symbols that actually exist in the fork's libnethack.so.
    # (There is intentionally NO nle_reset — reset is via nle_end+nle_start
    # or the fast-reset/snapshot path. Verified vs nm -D + nle.h.)
    for sym in ("nle_start", "nle_step", "nle_end", "nle_set_seed", "nle_get_obs"):
        assert hasattr(lib, sym)


def test_missing_library_raises_clear_error(tmp_path, monkeypatch):
    # Pointing NLE_LIB_PATH at a non-existent file should raise EngineNotBuilt
    # with a helpful message (mention build_engine.sh).
    monkeypatch.setenv("NLE_LIB_PATH", str(tmp_path / "does_not_exist.so"))
    # Reset any cached handle so the locator re-evaluates.
    _engine._LIB = None
    import pytest
    with pytest.raises(_engine.EngineNotBuilt) as exc:
        _engine.library_path()
    assert "build_engine.sh" in str(exc.value)
