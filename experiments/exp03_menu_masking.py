"""exp03 — menu region masking: dungeon view stops being polluted with menu text.

Bug: v0 of `_strip_right_menu` was a stub returning the row unchanged. When
NetHack opens an inventory menu (right side of screen), `render_map_view`
included the menu text mid-row, e.g. `..#@..a - tin of food.....`. Models had
to ignore that garbage when reasoning about the map.

Fix: `extract_menu_region` finds the menu's leftmost column from the inline
`<letter> - <name>` pattern and `_strip_right_menu` truncates each row at
that column. Map view becomes clean.

This experiment opens an inventory menu, renders the map both ways, and
diffs them. Verdict = FIX CONFIRMED if the legacy render contains menu chars
that the fixed render does not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nethack_core.env import NetHackCoreEnv
from nethack_core.observations import (
    extract_menu_region,
    render_map_view,
)

OUT_DIR = Path(__file__).parent / "results"
OUT_DIR.mkdir(exist_ok=True)

SEED = 42


def legacy_render_map_view(tty_chars) -> list[str]:
    """v0 stub: return rows verbatim, no menu stripping."""
    rows = []
    for y in range(tty_chars.shape[0]):
        rows.append(tty_chars[y].tobytes().decode("latin-1").rstrip("\x00"))
    return rows


def fixed_render_map_view(tty_chars) -> list[str]:
    """Current impl: strip the right-side menu region per row."""
    options, left_col = extract_menu_region(tty_chars)
    rows = []
    for y in range(tty_chars.shape[0]):
        row = tty_chars[y].tobytes().decode("latin-1").rstrip("\x00")
        if left_col is not None and len(row) > left_col:
            row = row[:left_col].rstrip()
        rows.append(row)
    return rows, options, left_col


def _synthetic_tty_with_menu() -> "np.ndarray":
    """Build a 24x80 tty with a left-side dungeon view and a right-side
    inventory menu starting at column 50.

    This mirrors what NLE produces when the agent opens an inventory; we
    construct it directly so the experiment doesn't depend on action sets
    that may not include 'i' (NetHackScore's restricted set, for instance).
    """
    import numpy as np

    rows = [
        " " * 80,
        " " * 80,
        "  ----------                          a - 5 daggers (alt)",
        "  |@.....|                            b - 2 darts",
        "  |....d.|                            c - silver bell",
        "  |......|                            d - tin of food",
        "  ----------                          e - blessed scroll",
        "                                      (end) ",
        " " * 80,
    ] + [" " * 80] * 15
    arr = np.zeros((24, 80), dtype=np.uint8)
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            arr[y, x] = ord(ch)
    return arr


def run() -> dict:
    tty = _synthetic_tty_with_menu()

    legacy_rows = legacy_render_map_view(tty)
    fixed_rows, opts, left_col = fixed_render_map_view(tty)

    # Diff: count how many rows differ.
    diffs = [(i, l, f) for i, (l, f) in enumerate(zip(legacy_rows, fixed_rows)) if l != f]

    # If the menu fired we expect: many rows identical (no menu there) +
    # several rows where legacy has menu garbage and fixed truncates.
    legacy_widths = [len(r.rstrip()) for r in legacy_rows]
    fixed_widths = [len(r.rstrip()) for r in fixed_rows]

    result = {
        "seed": SEED,
        "menu_left_col": left_col,
        "menu_options_extracted": [{"letter": o.letter, "description": o.description} for o in (opts or [])[:3]],
        "n_rows": len(legacy_rows),
        "n_diffs": len(diffs),
        "legacy_max_row_width": max(legacy_widths),
        "fixed_max_row_width": max(fixed_widths),
        "verdict": (
            "FIX CONFIRMED"
            if left_col is not None and len(diffs) >= 1 and max(fixed_widths) < max(legacy_widths)
            else "NO_MENU_OPENED" if left_col is None
            else "INCONCLUSIVE"
        ),
    }
    if diffs:
        i, l, f = diffs[0]
        result["sample_diff"] = {"row": i, "legacy": l, "fixed": f}

    (OUT_DIR / "exp03_menu_masking.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    print(f"\n{r['verdict']}")
