"""Harness TOML loader/writer/validator/preview.

Harness TOMLs live at `tools/launchpad/harnesses/*.toml`. The runtime overlay
loader is in `environments/nethack/nethack.py` (gated by the `NETHACK_HARNESS`
env var); this module owns the CLI/TUI side of CRUD + preview.
"""

from __future__ import annotations

from pathlib import Path

from tools.launchpad.types import HarnessConfig


def harnesses_dir() -> Path:
    """Return the on-disk dir containing harness TOMLs (creates if missing)."""
    raise NotImplementedError("core.harness.harnesses_dir")


def list_harnesses() -> list[HarnessConfig]:
    """List every harness in `harnesses_dir()`, sorted by name."""
    raise NotImplementedError("core.harness.list_harnesses")


def load_harness(name: str) -> HarnessConfig:
    """Load one harness by name (with `extends` resolution applied).

    Raises:
        FileNotFoundError: if `<name>.toml` is missing.
        ValueError: if the TOML is malformed or fails pydantic validation.
    """
    raise NotImplementedError("core.harness.load_harness")


def save_harness(cfg: HarnessConfig) -> Path:
    """Write `cfg` to `harnesses_dir()/<cfg.name>.toml` via `tomli_w`.

    Returns the written path. Overwrites any existing file with the same name.

    Raises:
        ValueError: if `cfg.name` contains path separators.
    """
    raise NotImplementedError("core.harness.save_harness")


def create_harness(name: str, extends: str = "default") -> HarnessConfig:
    """Create a new harness that `extends` another.

    Raises:
        FileExistsError: if `<name>.toml` already exists.
        FileNotFoundError: if `<extends>.toml` doesn't exist.
    """
    raise NotImplementedError("core.harness.create_harness")


def edit_harness(name: str) -> int:
    """Open `<name>.toml` in $EDITOR (fallback: nano). Returns editor's exit code.

    Raises:
        FileNotFoundError: if `<name>.toml` doesn't exist.
    """
    raise NotImplementedError("core.harness.edit_harness")


def diff_harness(name: str, against: str = "default") -> str:
    """Return a unified-diff string of `<name>.toml` vs `<against>.toml`."""
    raise NotImplementedError("core.harness.diff_harness")


def validate_harness(name: str) -> list[str]:
    """Validate `<name>.toml`. Returns a list of human-readable warnings.

    Empty list means valid. Hard errors raise.

    Raises:
        ValueError: on parse / schema failure.
    """
    raise NotImplementedError("core.harness.validate_harness")


def preview_harness(name: str, state: dict | None = None) -> str:
    """Render the turn-0 user message that the LLM would see under this harness.

    Args:
        name: harness name.
        state: optional sample state dict (uses a synthetic default if None).

    Returns:
        The rendered user-facing string (same content as a TraceTurn's
        `rendered_user_message`).
    """
    raise NotImplementedError("core.harness.preview_harness")
