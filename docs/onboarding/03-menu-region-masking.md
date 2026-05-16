# Menu region masking: the `_strip_right_menu` fix

**Status:** Wired up in `nethack_core/observations.py` as of Day 2. Tested in
`tests/test_observations.py`.

## The problem the ICLR 2026 blog called out

NetHack's `tty_chars` is a 24x80 array that contains both the dungeon view
*and* any open menu, side-by-side. When you press `i` to view inventory, or
the game pops up a "Pick which item to throw?" menu, the menu sits in the
right ~30 columns of the screen. Naïvely rendering `tty_chars` as the agent's
observation gives it a mash-up of dungeon plus menu text, which makes both
harder to read.

Sample (real NetHack screen, ~):

```
@......                    a - blessed +1 long sword
.#####                     b - uncursed leather armor
...........                c - 3 uncursed daggers
                          (end)
```

If you hand the agent this as the map, "first option" / "second option" /
"daggers" pollutes the tile vocabulary. The ICLR 2026 "Revisiting the NLE"
blogpost validated that splitting these views — clean map + structured menu —
improves both PPO and LM-agent performance on MiniHack subtasks.

The v0 implementation in `observations.py` had a no-op:

```python
def _strip_right_menu(row: str) -> str:
    # NetHack menus right-align. Naive heuristic for v0: drop the trailing
    # contiguous menu-looking suffix. TODO(jonathan): make this robust...
    return row
```

So no masking happened. `render_map_view` returned the full tty with menu
text in it.

## The fix

Two changes:

1. **Extract the menu's left column when we extract the menu options.** New
   function `extract_menu_region(tty_chars)` returns both `list[MenuOption]`
   and the leftmost column at which any menu line starts. The regex pattern
   is now `_MENU_INLINE_RE = re.compile(r"(?<![a-zA-Z])([a-zA-Z])\s+[-+]\s+\S")`
   — searched anywhere in the row, not anchored at the start, so it correctly
   finds menus that sit to the right of dungeon content.

2. **Use that column to truncate every row.** `_strip_right_menu(row, left_col)`
   cuts each row at `left_col`. Rows shorter than `left_col` are returned
   unchanged.

```python
def render_map_view(tty_chars, menu=None, menu_left_col=None) -> str:
    rows = ["".join(chr(c) for c in row) for row in tty_chars]
    if menu is not None:
        if menu_left_col is None:
            menu_left_col = _infer_menu_left_col(rows)  # fallback heuristic
        if menu_left_col is not None and menu_left_col > 0:
            rows = [_strip_right_menu(r, menu_left_col) for r in rows]
    return "\n".join(r.rstrip() for r in rows)
```

The `_infer_menu_left_col` fallback exists for cases where the caller hands
us only `menu` (not the column). It scans the rows for the same inline
pattern.

## What the agent actually sees now

Before:

```
=== MAP ===
@......                    a - blessed +1 long sword
.#####                     b - uncursed leather armor
...........                c - 3 uncursed daggers

=== MENU (select with menu_option) ===
  [0] blessed +1 long sword
  [1] uncursed leather armor
  [2] 3 uncursed daggers
```

After:

```
=== MAP ===
@......
.#####
...........

=== MENU (select with menu_option) ===
  [0] blessed +1 long sword
  [1] uncursed leather armor
  [2] 3 uncursed daggers
```

The dungeon view is clean. The menu is structured and selectable by index
(via the `menu_option` skill), so the model picks semantically, not by letter.

## Edge cases handled

- **Menus that fill the screen** (no dungeon visible). `extract_menu_region`
  returns left_col=0 (or close to it). The conditional `if menu_left_col > 0`
  skips masking — there's no dungeon to preserve, the whole screen is menu.
- **`(N of M)` pagination.** The end-row detector matches both `(end)` and
  `(\d+ of \d+)`.
- **Rows shorter than left_col.** Returned untouched. NetHack rows can be
  short on near-empty levels.
- **Inventory prompts that aren't menus.** "What do you want to throw? [abh]"
  is handled separately via `extract_inventory_prompt` — that's a one-line
  message, not a multi-row menu.

## How to verify

```bash
uv run pytest tests/test_observations.py -v
```

Six new tests cover the menu extraction, region detection, and map masking
end-to-end with synthetic tty fixtures.

## References

- ICLR 2026 blogpost: "Revisiting the NLE" — the menu masking validation on
  MiniHack gem-pickup and ring-selection subtasks
- NetHack source: `src/options.c` for the menu rendering paths
