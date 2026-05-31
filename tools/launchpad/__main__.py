"""Entry point. Bare `launchpad` boots the TUI; subcommands run via Typer."""

from __future__ import annotations

import sys

from tools.launchpad.cli import app


def main() -> None:
    """Console-script entry. With no args, boot the TUI; else dispatch Typer."""
    if len(sys.argv) == 1:
        # No subcommand: boot the Textual TUI.
        from tools.launchpad.tui.app import LaunchpadApp

        LaunchpadApp().run()
        return
    app()


if __name__ == "__main__":
    main()
