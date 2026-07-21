"""
nethack_core.trace_schema
==========================

Single, versioned source of truth for the per-turn rollout **trace** format —
the NDJSON stream the env writes (one JSON object per line, per LM turn) and the
rollout viewer / web console read back to replay a game exactly as the model saw
it.

Both sides import this module so the on-disk contract lives in one place:

    * writer  -> ``environments/nethack/nethack_harness/helpers._write_trace_entry``
    * readers -> ``tools/rollout_view/stats.load_trace`` and friends

This module deliberately depends on the standard library only (``json``). It
must NOT import ``verifiers``, ``flask`` or ``pufferlib`` so it stays usable
from every layer (engine, hub, console) without dragging in heavy deps.

On-disk field names are frozen (do not rename them). Bumping the format means
bumping :data:`TRACE_SCHEMA_VERSION` and documenting the change below.

Schema history
--------------
* ``1`` — first explicitly-versioned schema. Field set frozen from the
  pre-versioning writer; adds the ``schema_version`` stamp. Records written
  before versioning simply lack the key and are read as ``version 0`` (legacy).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Iterator, Union

# Current on-disk schema version. Bump when the field set changes.
TRACE_SCHEMA_VERSION = 1

# The key under which the version is stamped in each record.
SCHEMA_VERSION_KEY = "schema_version"

# ---------------------------------------------------------------------------
# Field catalogue (documentation + validation). Names are frozen — the writer
# and every reader agree on exactly these keys.
# ---------------------------------------------------------------------------

#: Fields every well-formed record carries.
REQUIRED_FIELDS: tuple[str, ...] = (
    "turn",                    # int: LM turn index within the rollout
    "raw_grid",                # list[str]: raw 24x80 tty rows (rstripped)
    "status",                  # dict: parsed status line (depth, hp, ...)
    "rendered_user_message",   # str: the literal text observation sent to the LM
    "tool_calls",              # list[{"name","arguments"}]: parsed tool calls
    "action_indices",          # list[int]: NLE action indices applied this turn
    "reward",                  # float: reward accrued this turn
)

#: Fields that may be present (writer emits them; readers must tolerate absence).
OPTIONAL_FIELDS: tuple[str, ...] = (
    SCHEMA_VERSION_KEY,        # int: schema version stamp (absent => legacy/0)
    "t_wall",                  # float: wall-clock timestamp
    "variant",                 # str: harness variant id
    "dlvl",                    # int|None: dungeon level (mirrors status depth)
    "hp",                      # int|None: hitpoints (mirrors status)
    "max_hp",                  # int|None: max hitpoints
    "max_dlvl_reached",        # int|None: deepest dlvl reached so far
    "continual_life",          # int: continual-harness life counter
    "rendered_user_content",   # str|list: multimodal user content (images->paths)
    "assistant_message",       # str: assistant message consumed this turn
    "messages",                # list[str]: in-game messages this turn
    "ch_edits",                # optional: refiner per-interval edits (variant CH)
    "checkpoint",              # str|None: level checkpoint path (web-console recorder)
)

#: Every documented field name.
ALL_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS


def record_version(record: dict) -> int:
    """Return the schema version stamped on ``record`` (0 if unstamped/legacy)."""
    try:
        return int(record.get(SCHEMA_VERSION_KEY, 0))
    except (TypeError, ValueError):
        return 0


def stamp(record: dict) -> dict:
    """Return ``record`` with the current schema version stamped in place."""
    record[SCHEMA_VERSION_KEY] = TRACE_SCHEMA_VERSION
    return record


def to_json_line(record: dict) -> str:
    """Serialize one record to a single NDJSON line (trailing newline included).

    Stamps the current :data:`TRACE_SCHEMA_VERSION`. On-disk field names are left
    untouched; only the version key is added.
    """
    return json.dumps(stamp(record)) + "\n"


def write_record(fp: IO[str], record: dict) -> None:
    """Append one stamped record as an NDJSON line to an open text file object."""
    fp.write(to_json_line(record))


def parse_line(line: str) -> Union[dict, None]:
    """Parse one NDJSON line into a record dict, or ``None`` if it is blank,
    not valid JSON, or not a JSON object. Readers skip ``None`` results."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def iter_records(path: Union[str, Path]) -> Iterator[dict]:
    """Yield each valid record from an NDJSON trace file, skipping bad lines."""
    for line in Path(path).read_text().splitlines():
        rec = parse_line(line)
        if rec is not None:
            yield rec


def read_trace(path: Union[str, Path]) -> list[dict]:
    """Read a whole NDJSON trace file into a list of record dicts."""
    return list(iter_records(path))


def validate_record(record: dict) -> list[str]:
    """Return a list of human-readable problems with ``record`` (empty == valid).

    Checks that ``record`` is a dict, carries every required field, and has no
    unknown keys. Intended for tests / defensive callers; the writer and readers
    are tolerant by design and do not call this on the hot path.
    """
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["record is not a dict"]
    for f in REQUIRED_FIELDS:
        if f not in record:
            problems.append(f"missing required field: {f!r}")
    known = set(ALL_FIELDS)
    for k in record:
        if k not in known:
            problems.append(f"unknown field: {k!r}")
    return problems


def is_valid(record: dict) -> bool:
    """True if ``record`` has all required fields and no unknown keys."""
    return not validate_record(record)
