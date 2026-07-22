"""
nethack_core
============

Interface-agnostic NetHack **engine** substrate: wrap the NetHack engine (the
``nle`` gym path via :class:`NetHackCoreEnv`, or the custom fork engine via
:class:`EngineEnv`) and surface a clean, typed observation plus the map model,
glyph classifiers and reward primitives downstream layers build on. Everything
else (skills, prompt, curriculum navigation, memory, verifiers env) lives in the
``nethack`` / ``nethack_harness`` packages.

Public API
----------
This ``__init__`` is the **one documented import boundary** for the engine
layer. Consumers (``environments/nethack/**``, ``approaches/**``, ``tools/**``)
must import from the package root only — either a re-exported symbol::

    from nethack_core import NetHackCoreEnv, EngineEnv, shape, build_map_model

or a re-exported submodule namespace (handy where a caller uses many symbols,
e.g. glyph/action tables, or to disambiguate the two ``parse_status``)::

    from nethack_core import actions, glyphs, observations, nld_parse

Do NOT reach into deep submodule paths (``from nethack_core.env import ...``);
those are internal and a future standalone ``nethack-engine`` package will not
promise them.

Quick start
-----------
    from nethack_core import NetHackCoreEnv, observations

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=42, disp=42)
    obs, meta = env.reset()
    structured = observations.shape(obs, character={"role": "unknown"})

Snapshot / restore / branch / tune / modify / save_level / load_level are
methods on :class:`EngineEnv` (the fork-engine path).
"""
from __future__ import annotations

# --- re-exported submodule namespaces (public) ---
# Importing a submodule via the package root (``from nethack_core import
# glyphs``) is part of the public surface. These also disambiguate the two
# distinct ``parse_status`` (observations vs nld_parse).
from . import actions
from . import glyphs
from . import map_model
from . import nld_parse
from . import observations
from . import rewards
from . import trace_schema

# --- environments / engine ---
from .env import CoreObservation, EpisodeMetadata, NetHackCoreEnv
from .engine_env import EngineEnv
from .curriculum_env import CurriculumEnv
from .curriculum_engine_env import CurriculumEngineEnv, curriculum_floor_of
from .curriculum_upgrade import STAT_FIELDS, ValkyrieUpgradeModel

# --- observations / structured obs ---
from .observations import (
    BLSTATS_IDX,
    InventoryItem,
    MenuOption,
    StructuredObservation,
    extract_adjacent,
    extract_hostiles_in_sight,
    extract_inventory_prompt,
    extract_menu,
    extract_menu_region,
    extract_under_player,
    extract_visible_features,
    extract_yn_prompt,
    parse_character_from_attributes_menu,
    parse_inventory,
    render_map_view,
    shape,
)

# --- map model ---
from .map_model import Entity, MapModel, build_map_model

# --- reward primitives ---
from .rewards import DeltaReward, RewardModel, ScoreDepthXPReward

# --- action tables ---
from .actions import (
    Command,
    CompassDirection,
    CompassDirectionLonger,
    MiscAction,
    MiscDirection,
    TextCharacters,
)

# --- glyph classifiers / tables ---
from .glyphs import (
    CMAP_CLOSED_DOOR_INDICES,
    GLYPH_CMAP_OFF,
    GLYPH_MON_OFF,
    GLYPH_OBJ_OFF,
    GLYPH_PET_OFF,
    cmap_clean_char_lut,
    glyph_is_body,
    glyph_is_cmap,
    glyph_is_detected_monster,
    glyph_is_invisible,
    glyph_is_monster,
    glyph_is_normal_monster,
    glyph_is_normal_object,
    glyph_is_object,
    glyph_is_pet,
    glyph_is_ridden_monster,
    glyph_is_statue,
    glyph_is_trap,
    glyph_to_mon,
    monster_name,
)

# --- NetHack Learning Dataset (ttyrec) status parsing ---
# NOTE: ``nld_parse.parse_status`` (parses a status *text* line) and
# ``observations.parse_status`` (parses a blstats *array*) are distinct. Neither
# is re-exported flat to avoid a name clash — reach them via the namespace:
# ``nld_parse.parse_status`` / ``observations.parse_status``.
from .nld_parse import detect_role, is_valkyrie, strength_to_internal

# --- trace schema (versioned NDJSON contract) ---
from .trace_schema import TRACE_SCHEMA_VERSION

__all__ = [
    # submodule namespaces
    "actions",
    "glyphs",
    "map_model",
    "nld_parse",
    "observations",
    "rewards",
    "trace_schema",
    # environments / engine
    "CoreObservation",
    "EpisodeMetadata",
    "NetHackCoreEnv",
    "EngineEnv",
    "CurriculumEnv",
    "CurriculumEngineEnv",
    "curriculum_floor_of",
    "STAT_FIELDS",
    "ValkyrieUpgradeModel",
    # observations
    "BLSTATS_IDX",
    "InventoryItem",
    "MenuOption",
    "StructuredObservation",
    "extract_adjacent",
    "extract_hostiles_in_sight",
    "extract_inventory_prompt",
    "extract_menu",
    "extract_menu_region",
    "extract_under_player",
    "extract_visible_features",
    "extract_yn_prompt",
    "parse_character_from_attributes_menu",
    "parse_inventory",
    "render_map_view",
    "shape",
    # map model
    "Entity",
    "MapModel",
    "build_map_model",
    # rewards
    "DeltaReward",
    "RewardModel",
    "ScoreDepthXPReward",
    # actions
    "Command",
    "CompassDirection",
    "CompassDirectionLonger",
    "MiscAction",
    "MiscDirection",
    "TextCharacters",
    # glyphs
    "CMAP_CLOSED_DOOR_INDICES",
    "GLYPH_CMAP_OFF",
    "GLYPH_MON_OFF",
    "GLYPH_OBJ_OFF",
    "GLYPH_PET_OFF",
    "cmap_clean_char_lut",
    "glyph_is_body",
    "glyph_is_cmap",
    "glyph_is_detected_monster",
    "glyph_is_invisible",
    "glyph_is_monster",
    "glyph_is_normal_monster",
    "glyph_is_normal_object",
    "glyph_is_object",
    "glyph_is_pet",
    "glyph_is_ridden_monster",
    "glyph_is_statue",
    "glyph_is_trap",
    "glyph_to_mon",
    "monster_name",
    # nld_parse
    "detect_role",
    "is_valkyrie",
    "strength_to_internal",
    # trace schema
    "TRACE_SCHEMA_VERSION",
]
