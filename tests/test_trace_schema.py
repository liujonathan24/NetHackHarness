"""The versioned NDJSON trace contract shared by the env writer and the viewers."""
import io

from nethack_core import trace_schema as ts


def _minimal_record():
    return {
        "turn": 0,
        "raw_grid": ["", ""],
        "status": {"depth": 1, "hitpoints": 14},
        "rendered_user_message": "you see here a rock",
        "tool_calls": [],
        "action_indices": [],
        "reward": 0.0,
    }


def test_to_json_line_stamps_current_version():
    line = ts.to_json_line(_minimal_record())
    assert line.endswith("\n")
    rec = ts.parse_line(line)
    assert rec[ts.SCHEMA_VERSION_KEY] == ts.TRACE_SCHEMA_VERSION
    assert ts.record_version(rec) == ts.TRACE_SCHEMA_VERSION


def test_write_record_roundtrips_through_a_file_object():
    buf = io.StringIO()
    ts.write_record(buf, _minimal_record())
    ts.write_record(buf, {**_minimal_record(), "turn": 1})
    lines = buf.getvalue().splitlines()
    assert len(lines) == 2
    recs = [ts.parse_line(x) for x in lines]
    assert [r["turn"] for r in recs] == [0, 1]


def test_legacy_records_without_stamp_read_as_version_zero():
    assert ts.record_version({"turn": 0}) == 0


def test_parse_line_skips_blank_invalid_and_non_object():
    assert ts.parse_line("") is None
    assert ts.parse_line("   ") is None
    assert ts.parse_line("{not json") is None
    assert ts.parse_line("[1, 2, 3]") is None  # valid JSON, not an object
    assert ts.parse_line('{"turn": 3}') == {"turn": 3}


def test_iter_records_tolerates_malformed_lines(tmp_path):
    p = tmp_path / "trace.ndjson"
    good = ts.to_json_line(_minimal_record())
    p.write_text(good + "\n" + "garbage\n" + "\n" + ts.to_json_line({**_minimal_record(), "turn": 1}))
    recs = ts.read_trace(p)
    assert [r["turn"] for r in recs] == [0, 1]


def test_validate_record_flags_missing_required_and_unknown_fields():
    assert ts.is_valid(_minimal_record())
    problems = ts.validate_record({"turn": 0})
    assert any("missing required field" in p for p in problems)
    problems = ts.validate_record({**_minimal_record(), "bogus": 1})
    assert any("unknown field" in p and "bogus" in p for p in problems)


def test_optional_and_web_console_fields_are_accepted():
    rec = {**_minimal_record(), "checkpoint": "/tmp/x.ckpt", "variant": "web_play",
           "messages": ["hello"], "dlvl": 1, "hp": 14}
    assert ts.is_valid(rec)
