"""Status-line parser for the NLD human-data ingest."""
import pathlib
import sys

sys.path.insert(
    0,
    str(pathlib.Path(__file__).resolve().parents[2] / "environments" / "nethack"),
)

import pytest

from nethack_core import (
    detect_role,
    is_valkyrie,
    strength_to_internal,
)
from nethack_core import nld_parse

# A realistic NetHack 3.6 two-line bottom status (a deep Valkyrie).
DEEP_VALK = (
    "Agnes the Warrior        St:18/** Dx:16 Co:18 In:9 Wi:14 Ch:8  Neutral\n"
    "Dlvl:48 $:0 HP:175(175) Pw:0(0) AC:-3 Xp:18/720000 T:42000 Hungry"
)

SHALLOW = (
    "Agent the Stripling      St:18/03 Dx:14 Co:16 In:8 Wi:13 Ch:10  Lawful\n"
    "Dlvl:3 $:42 HP:34(34) Pw:5(5) AC:6 Xp:5/160 T:900"
)


@pytest.mark.parametrize("disp,internal", [
    ("3", 3), ("14", 14), ("18", 18),
    ("18/01", 19), ("18/03", 21), ("18/99", 117),
    ("18/00", 118), ("18/**", 118),
    ("19", 119), ("25", 125),
])
def test_strength_to_internal(disp, internal):
    assert strength_to_internal(disp) == internal


def test_parse_deep_valkyrie_status():
    st = nld_parse.parse_status(DEEP_VALK)
    assert st["depth"] == 48
    assert st["hp"] == 175 and st["max_hp"] == 175
    assert st["xp_level"] == 18
    assert st["str"] == 118  # 18/**
    assert st["dex"] == 16 and st["con"] == 18
    assert st["int"] == 9 and st["wis"] == 14 and st["cha"] == 8


def test_parse_shallow_status():
    st = nld_parse.parse_status(SHALLOW)
    assert st["depth"] == 3
    assert st["xp_level"] == 5
    assert st["str"] == 21  # 18/03


def test_parse_non_status_returns_none():
    assert nld_parse.parse_status("--More--") is None
    assert nld_parse.parse_status("Really attack the dog? [yn]") is None


def test_role_detection():
    assert is_valkyrie("You are a neutral female human Valkyrie.")
    assert not is_valkyrie("You are a lawful male human Knight.")
    assert detect_role("Hello Agent, welcome ... human Valkyrie.") == "Valkyrie"
    assert detect_role("a chaotic gnomish Wizard") == "Wizard"
