"""Open a recorded rollout as a rich HTML replay.

The launchpad-facing affordance: export the self-contained HTML replay (text +
real images, both forms) for a recorded run and open it in the browser. The
Textual TUI shows the text forms; this is the full-image-fidelity path.
"""
from __future__ import annotations

from pathlib import Path

from tools.rollout_view.replay_export import export_replay_html


def open_replay_html(run_dir, *, open_browser: bool = True) -> Path:
    """Export the HTML replay for ``run_dir`` and (optionally) open it.

    Returns the path to the written ``replay.html``. ``open_browser=False``
    exports without opening (used by tests / headless callers).
    """
    out = export_replay_html(run_dir)
    if open_browser:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())
    return out
