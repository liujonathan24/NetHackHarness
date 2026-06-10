"""rollout_view — retro HTML viewer + post-hoc stats dashboard for NetHack rollouts."""
from . import stats
from .dashboard import render_dashboard, dashboard_from_paths

__all__ = ["stats", "render_dashboard", "dashboard_from_paths"]
