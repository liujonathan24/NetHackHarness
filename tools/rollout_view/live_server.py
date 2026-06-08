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
# ---------------------------------------------------------------------------


def _make_handler(stepper: LiveStepper):
    from http.server import BaseHTTPRequestHandler

    class _Handler(BaseHTTPRequestHandler):
        def _send_html(self, body: str, status: int = 200):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/") in ("", "/") or self.path.startswith("/?"):
                controls = (
                    '<form method="post" action="/step">'
                    '<button type="submit">step one turn</button></form>'
                )
                self._send_html(render_run(stepper.history).replace(
                    "<body>", f"<body>{controls}", 1))
            else:
                self._send_html("<h1>404</h1>", status=404)

        def do_POST(self):
            if self.path.rstrip("/") == "/step":
                try:
                    from nethack_interface import RawAction

                    if stepper.policy is None:
                        stepper.step_once(RawAction(0))
                    else:
                        stepper.step_once()
                except Exception as e:
                    self._send_html(f"<pre>step error: {e}</pre>", status=500)
                    return
                # Redirect back to the run view.
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self._send_html("<h1>404</h1>", status=404)

        def log_message(self, *args):  # quiet by default
            pass

    return _Handler


def serve(stepper: LiveStepper, port: int = 8765, host: str = "127.0.0.1"):
    """Serve the live stepper over HTTP, bound to localhost by default.

    Blocks until interrupted. GET ``/`` renders the run history; POST ``/step``
    advances one turn.
    """
    from http.server import HTTPServer

    httpd = HTTPServer((host, port), _make_handler(stepper))
    print(f"live rollout stepper on http://{host}:{port}/ "
          f"(variant={stepper.variant}, "
          f"mode={'model' if stepper.policy else 'manual'})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _build_default_interface():
    from nethack_core.env import NetHackCoreEnv
    from nethack_interface import NetHackInterface

    env = NetHackCoreEnv(task_name="NetHackScore-v0")
    env.seed(core=42, disp=42)
    return NetHackInterface(env)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Live NetHack rollout stepper (localhost; manual by default)."
    )
    parser.add_argument("--variant", default="B1",
                        help="prompt variant to render (default: B1)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    stepper = LiveStepper(_build_default_interface(), variant=args.variant)
    serve(stepper, port=args.port, host=args.host)


if __name__ == "__main__":  # pragma: no cover
    main()
