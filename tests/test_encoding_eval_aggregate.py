from __future__ import annotations

from tools.encoding_eval.aggregate import aggregate_cells, table_to_markdown


def _sample(*, reward, descended, max_dlvl, xp, tokens_per_turn=None):
    trace = [{"rendered_user_message": "MAP", "status": {"depth": max_dlvl, "experience_level": xp}}]
    s = {"reward": reward, "scout_reward": 0.0, "descent_reward": 1.0 if descended else 0.0,
         "seed": 1, "trace": trace, "max_dlvl": max_dlvl, "xp_level": xp}
    if tokens_per_turn is not None:
        s["tokens_per_turn"] = tokens_per_turn
    return s


def test_table_has_one_row_per_encoding():
    cells = {
        "B1": [_sample(reward=1, descended=True, max_dlvl=2, xp=3, tokens_per_turn=500)],
        "JSON": [_sample(reward=0, descended=False, max_dlvl=1, xp=1, tokens_per_turn=1200)],
    }
    table = aggregate_cells(cells)
    assert set(table["rows"]) == {"B1", "JSON"}
    b1 = table["rows"]["B1"]
    # reuses summarize_eval + progression
    assert b1["descent_rate"] == 1.0
    assert "ci_lo" in b1 and "ci_hi" in b1
    assert b1["max_dlvl"] == 2
    assert b1["progression_tier"]  # non-empty
    assert b1["tokens_per_turn"] == 500


def test_missing_usage_marks_cost_unavailable():
    cells = {"IMG": [_sample(reward=0, descended=False, max_dlvl=1, xp=1)]}  # no tokens
    table = aggregate_cells(cells)
    assert table["rows"]["IMG"]["dollars_per_run"] is None


def test_table_to_markdown_renders_rows_and_na():
    cells = {
        "B1": [_sample(reward=1, descended=True, max_dlvl=2, xp=3, tokens_per_turn=500)],
        "IMG": [_sample(reward=0, descended=False, max_dlvl=1, xp=1)],  # no tokens/cost
    }
    md = table_to_markdown(aggregate_cells(cells))
    assert "| encoding |" in md and "B1" in md and "IMG" in md
    assert "n/a" in md  # missing cost rendered as n/a, not fabricated
