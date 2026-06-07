# tests/test_encoding_eval_run.py
from __future__ import annotations

from tools.encoding_eval.run import run_matrix


def test_dispatches_each_cell_with_variant_and_detail():
    calls = []

    def stub_runner(cell):
        calls.append(cell)
        # return a couple of fake samples for this cell
        return [{"reward": 1.0, "descent_reward": 1.0, "seed": 1, "trace": []}]

    matrix = {
        "encodings": [{"variant": "B1"}, {"variant": "JSON", "map_detail": "minimal"}],
        "models": ["qwen-instruct"],
    }
    table = run_matrix(matrix, runner=stub_runner)
    # one cell per (encoding, model)
    variants = sorted(c["variant"] for c in calls)
    assert variants == ["B1", "JSON"]
    assert any(c.get("map_detail") == "minimal" for c in calls)
    assert set(table["rows"]) == {"B1", "JSON:minimal"}  # cell keys distinguish detail
