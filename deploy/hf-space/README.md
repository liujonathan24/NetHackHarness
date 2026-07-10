---
title: NetHack Curriculum Map Viewer
emoji: "🎮"
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# NetHack Curriculum Map Viewer

Live, interactive NetHack **Map Viewer** with a **Curriculum tour** mode: switch
the env to the compressed 6-floor down/up tour, jump the hero onto any floor
(Dungeons of Doom 1–3 / Gehennom 48–50) with one click, and watch it climb back
using the real `<` stairs — the environment behind the reverse-curriculum study.

Built from the public [`liujonathan24/NetHackHarness`](https://github.com/liujonathan24/NetHackHarness)
repo; the Docker image builds the fork engine from source at deploy time.

> Note: the server shares ONE game engine across all requests (the C engine is not
> reentrant), so this is a single-player demo — concurrent visitors drive the same
> board. Rebuild the Space to update from the repo.
