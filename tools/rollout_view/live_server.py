"""Live rollout stepper: drive a NetHackInterface one turn at a time and view
the result as HTML on localhost.

`LiveStepper` is the testable core (no HTTP): it holds a `NetHackInterface`,
renders the chosen variant's per-turn observation (the dict shape that
`tools.rollout_view.html.render_turn` consumes), and advances exactly one turn
on demand.

  - MANUAL mode (``policy=None``): the caller supplies the action to
    ``step_once(action)`` (an ``Action``/``RawAction``).
  - MODEL mode (``policy=callable``): ``step_once()`` calls ``policy(obs)`` to
    pick the action.

`serve()` is a thin stdlib ``http.server`` wrapper bound to localhost: GET ``/``
renders the run history, POST ``/step`` advances one turn (manual mode steps a
single primitive ``RawAction``; model mode invokes the policy).
"""
from __future__ import annotations

import argparse
from typing import Any, Callable, Optional

from tools.rollout_view.html import render_run, render_turn


class LiveStepper:
    """Step a `NetHackInterface` one turn at a time and surface each turn as a
    `render_turn`-ready dict.

    Parameters
    ----------
    interface:
        A constructed ``nethack_interface.NetHackInterface``. It is reset on
        construction so ``current_turn()`` reflects the initial observation.
    policy:
        Optional ``policy(obs) -> Action | RawAction`` callable. When set,
        ``step_once()`` (with no explicit action) consults it (MODEL mode).
        When ``None`` (MANUAL mode) the caller passes the action.
    variant:
        Which prompt variant's renderer to use for ``rendered_user_content``.
    """

    def __init__(self, interface, *, policy: Optional[Callable] = None,
                 variant: str = "B1"):
        self.interface = interface
        self.policy = policy
        self.variant = variant
        self._turn = 0
        self._last_obs = interface.reset()
        self.history: list[dict] = []
        self._current = self._build_turn()
        self.history.append(self._current)

    # ---- rendering ----

    def _raw_grid(self) -> list:
        """The 24x80 tty grid as a list of rstrip'd strings, built from the
        interface's current raw obs (mirrors helpers._write_trace_entry)."""
        raw = getattr(self.interface, "_raw", None)
        if raw is None:
            return []
        try:
            return [
                "".join(chr(int(c)) for c in row).rstrip()
                for row in raw.tty_chars
            ]
        except Exception:
            return []

    def _rendered_user_content(self):
        """Render the chosen variant's per-turn observation text (str) or
        multimodal list, reusing the harness prompt spec."""
        try:
            from nethack_harness.prompt.prompt_spec import resolve_spec, SYSTEM_PROMPT

            spec = resolve_spec(self.variant, SYSTEM_PROMPT)
            structured = getattr(self.interface, "_structured", None)
            state = {"raw_obs": getattr(self.interface, "_raw", None),
                     "map_detail": "full"}
            return spec.turn_template(
                structured, None, state,
                compact=True, journal_max_chars=2000,
            )
        except Exception as e:  # never let rendering break the stepper
            return f"[render error: {e}]"

    def _build_turn(self) -> dict:
        return {
            "turn": self._turn,
            "raw_grid": self._raw_grid(),
            "rendered_user_content": self._rendered_user_content(),
        }

    # ---- stepping ----

    def current_turn(self) -> dict:
        """The most-recent per-turn dict (the shape `render_turn` consumes)."""
        return self._current

    def step_once(self, action: Any = None) -> dict:
        """Advance exactly one turn.

        MANUAL mode: ``action`` must be supplied. MODEL mode: if ``action`` is
        ``None`` and a ``policy`` is set, ``policy(last_obs)`` chooses it.
        """
        if action is None:
            if self.policy is None:
                raise ValueError(
                    "step_once() needs an action in manual mode "
                    "(no policy configured)."
                )
            action = self.policy(self._last_obs)
        obs, *_ = self.interface.step(action)
        self._last_obs = obs
        self._turn += 1
        self._current = self._build_turn()
        self.history.append(self._current)
        return self._current


# ---------------------------------------------------------------------------
# Thin HTTP layer (not the test target).
#
# One entry page (`/`) lists recorded runs and offers a live-session launcher.
# `/run?dir=X` opens the single-window slider viewer over a recorded run;
# `/live?variant=V` starts a live session (same viewer, with a Step control);
# POST `/step` advances the live session one turn and returns the new turn as an
# HTML fragment the page appends in place (no full reload).
# ---------------------------------------------------------------------------


def _load_turns(run_dir) -> list:
    from pathlib import Path

    from nethack_core import trace_schema

    turns: list = []
    for f in sorted(Path(run_dir).glob("*.ndjson")):
        turns += trace_schema.read_trace(f)
    return turns


class RolloutViewServer:
    """Server state: where recorded runs live, how to build a fresh interface for
    a live session, and the currently-active live stepper (if any)."""

    def __init__(self, *, runs_root, make_interface, variants=None):
        from pathlib import Path

        self.runs_root = Path(runs_root)
        self.make_interface = make_interface  # () -> NetHackInterface (fresh)
        from tools.rollout_view.index import DEFAULT_VARIANTS
        self.variants = tuple(variants or DEFAULT_VARIANTS)
        self.live: Optional[LiveStepper] = None


def _make_handler(server: RolloutViewServer):
    from http.server import BaseHTTPRequestHandler
    from pathlib import Path
    from urllib.parse import urlparse, parse_qs

    from urllib.parse import quote

    class _Handler(BaseHTTPRequestHandler):
        def _send(self, body: str, status: int = 200):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, data: bytes, ctype: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            path = u.path.rstrip("/") or "/"
            q = parse_qs(u.query)
            if path == "/":
                from tools.rollout_view.index import discover_runs, render_index
                runs = discover_runs(server.runs_root)
                self._send(render_index(runs, variants=server.variants, root=server.runs_root))
            elif path == "/run":
                d = (q.get("dir") or [None])[0]
                if not d:
                    return self._send("<h1>400 — missing ?dir</h1>", 400)
                run_dir = Path(d).resolve()
                # Map a turn's relative image ref (`images/x.png`) to the /file
                # route so recorded-run images actually load over HTTP.
                img_src = (lambda ref, _rd=run_dir:
                           "/file?path=" + quote(str((_rd / ref).resolve())))
                self._send(render_run(_load_turns(d), live=False,
                                      title=Path(d).name, img_src=img_src))
            elif path == "/file":
                p = (q.get("path") or [None])[0]
                if not p:
                    return self._send("<h1>400</h1>", 400)
                fp = Path(p).resolve()
                # Security: only serve files under the runs root.
                root = server.runs_root.resolve()
                if root not in fp.parents or not fp.is_file():
                    return self._send("<h1>403</h1>", 403)
                import mimetypes
                ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
                self._send_bytes(fp.read_bytes(), ctype)
            elif path == "/browse":
                from tools.rollout_view.browse import render_browser
                rel = (q.get("path") or [""])[0]
                self._send(render_browser(server.runs_root, rel))
            elif path == "/dashboard":
                from tools.rollout_view.browse import collect_data_files
                from tools.rollout_view.dashboard import dashboard_from_paths
                rel = (q.get("path") or [""])[0]
                files = collect_data_files(server.runs_root, rel)
                if not files:
                    return self._send("<h1>404 — no .ndjson/.jsonl under that path</h1>", 404)
                metrics = tuple((q.get("metrics") or ["dlvl,hp,xp,kills_cum"])[0].split(","))
                self._send(dashboard_from_paths([str(f) for f in files], metrics=metrics,
                                                title=f"STATS · {rel or server.runs_root.name}"))
            elif path == "/live":
                variant = (q.get("variant") or ["B1"])[0]
                server.live = LiveStepper(server.make_interface(), variant=variant)
                self._send(render_run(server.live.history, live=True, title=f"live · {variant}"))
            else:
                self._send("<h1>404</h1>", 404)

        def do_POST(self):
            if self.path.rstrip("/") == "/step":
                if server.live is None:
                    return self._send("<pre>no live session — start one from /</pre>", 409)
                from nethack_interface import RawAction
                try:
                    turn = (server.live.step_once(RawAction(0)) if server.live.policy is None
                            else server.live.step_once())
                except Exception as e:
                    return self._send(f"<pre>step error: {e}</pre>", 500)
                self._send(render_turn(turn))  # fragment; the page appends it
            else:
                self._send("<h1>404</h1>", 404)

        def log_message(self, *args):  # quiet by default
            pass

    return _Handler


def _build_default_interface():
    from nethack_core import NetHackCoreEnv
    from nethack_interface import NetHackInterface

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=42, disp=42)
    return NetHackInterface(env)


def serve(*, runs_root, make_interface=None, port: int = 8765,
          host: str = "127.0.0.1", variants=None):
    """Serve the rollout-view UI (index + run viewer + live stepper) on localhost.

    Blocks until interrupted. `runs_root` is scanned for recorded runs;
    `make_interface()` builds a fresh `NetHackInterface` per live session.
    """
    from http.server import HTTPServer

    if make_interface is None:
        make_interface = _build_default_interface
    server = RolloutViewServer(runs_root=runs_root, make_interface=make_interface, variants=variants)
    httpd = HTTPServer((host, port), _make_handler(server))
    print(f"rollout views on http://{host}:{port}/  (runs: {server.runs_root})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Rollout views: browse recorded runs + step a live rollout (localhost)."
    )
    parser.add_argument("--runs-root", default="environments/nethack/outputs/evals",
                        help="directory scanned for recorded runs (default: %(default)s)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    serve(runs_root=args.runs_root, port=args.port, host=args.host)


if __name__ == "__main__":  # pragma: no cover
    main()
