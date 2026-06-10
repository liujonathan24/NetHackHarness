"""Finder-style filesystem browser for the rollout-view UI."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

from rollout_view import browse  # noqa: E402


def _tree(tmp):
    (tmp / "runA").mkdir()
    (tmp / "runA" / "0.ndjson").write_text('{"turn":0}\n')
    (tmp / "nested").mkdir()
    (tmp / "nested" / "deep").mkdir()
    (tmp / "nested" / "deep" / "results.jsonl").write_text("{}\n")
    return tmp


def test_lists_dirs_and_files_with_nav_links(tmp_path):
    _tree(tmp_path)
    html = browse.render_browser(tmp_path, "")
    assert "runA" in html and "nested" in html
    assert "/browse?path=" in html          # folders are navigable
    # a run dir (has .ndjson) exposes view-run + dashboard actions
    assert "/run?dir=" in html and "/dashboard?path=" in html


def test_navigates_into_nested_folder(tmp_path):
    _tree(tmp_path)
    html = browse.render_browser(tmp_path, "nested")
    assert "deep" in html
    assert "&#8617;" in html  # an ".." up link is present below root


def test_security_confines_to_root(tmp_path):
    _tree(tmp_path)
    assert browse._safe_join(Path(tmp_path).resolve(), "../../etc") is None
    html = browse.render_browser(tmp_path, "../../../etc")
    assert "not found" in html or "outside" in html


def test_collect_data_files_for_dir_and_file(tmp_path):
    _tree(tmp_path)
    got = {p.name for p in browse.collect_data_files(tmp_path, "runA")}
    assert got == {"0.ndjson"}
    got2 = {p.name for p in browse.collect_data_files(tmp_path, "nested/deep/results.jsonl")}
    assert got2 == {"results.jsonl"}
