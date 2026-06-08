"""Shared retro UI theme for the rollout views (index + trace viewer).

A dungeon-stone palette (grays) with soft candy-pastel accent tiles — calmer than
neon, evoking a dim stone dungeon dotted with colored gems. Both the index page
and the single-window trace viewer pull `THEME_CSS` so they stay in lockstep.
"""
from __future__ import annotations

# Pixel fonts (graceful monospace fallback when offline).
_FONTS = ("@import url('https://fonts.googleapis.com/css2?"
          "family=Press+Start+2P&family=VT323&display=swap');")

# Dungeon grays + candy accents. The candy ramp is reused as rotating run "tiles".
_VARS = """
:root {
  --bg:      #14141a;   /* dungeon void */
  --panel:   #1d1d24;   /* stone panel */
  --surface: #262630;   /* lighter stone (inputs) */
  --line:    #3b3b46;   /* stone border */
  --line-lt: #555562;   /* hover border */
  --text:    #cdcdd6;   /* bone gray text */
  --dim:     #7c7c8a;   /* muted gray */
  /* candy-pastel accent tiles */
  --pink:    #ff9ecb;
  --cyan:    #86e5ff;
  --gold:    #ffd98a;
  --violet:  #bda6ff;
  --mint:    #9af0b4;
}
"""

# Shared base look: stone background, faint scanlines, pixel headings, stone panels,
# candy-gold buttons. Component layout (index list / viewer columns) lives per-page.
_BASE = """
* { box-sizing: border-box; }
html, body { margin: 0; }
body { min-height: 100vh; color: var(--text); font-size: 20px; letter-spacing: .3px;
  font-family: 'VT323', ui-monospace, monospace;
  background: radial-gradient(ellipse at 50% -12%, #22222c 0%, var(--bg) 62%); }
body::after { content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 50;
  background: repeating-linear-gradient(0deg, rgba(0,0,0,.14) 0 1px, transparent 1px 3px);
  mix-blend-mode: multiply; }
h1 { font-family: 'Press Start 2P', monospace; font-size: 18px; line-height: 1.55;
  margin: 0 0 1.2em; color: var(--gold); text-shadow: 0 0 10px rgba(255,217,138,.30); }
.cursor { animation: blink 1.1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.panel { border: 2px solid var(--line); background: var(--panel); padding: .9em 1.1em;
  margin: 0 0 1.3em; box-shadow: inset 0 0 0 1px #0d0d12, 0 2px 0 #0d0d12; }
.bar { font-family: 'Press Start 2P', monospace; font-size: 10px; color: var(--cyan);
  margin: 0 0 .85em; }
button, select { font-family: 'VT323', monospace; font-size: 19px; background: var(--surface);
  color: var(--text); border: 2px solid var(--line); padding: .12em .6em; }
button { cursor: pointer; text-transform: uppercase; letter-spacing: 1px; color: var(--gold); }
button:hover { background: var(--gold); color: #1a1206; border-color: var(--gold);
  box-shadow: 0 0 10px rgba(255,217,138,.4); }
input[type=range] { accent-color: var(--violet); }
:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
a { color: var(--cyan); text-decoration: none; }
.hint, .dim { color: var(--dim); font-size: 16px; }
@media (prefers-reduced-motion: reduce) { .cursor { animation: none; } }
"""

# The candy ramp, in order — pages rotate run/turn tiles through it.
CANDY = ("var(--pink)", "var(--cyan)", "var(--gold)", "var(--violet)", "var(--mint)")

THEME_CSS = _FONTS + _VARS + _BASE
