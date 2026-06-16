"""Hatchling build hook: bundle the fork engine into the wheel.

The Prime Hub installs only this env directory as a wheel — without the
third_party/NetHack fork source. So the wheel must carry the compiled
libnethack.so + NetHack data files (dat/). This hook runs at wheel-build time
(e.g. during `prime env push`, which builds the wheel locally where the fork
submodule IS available) and ensures both are present in nethack_core/ before
the force-include step collects them.

Fast path: if the artifacts are already in place (e.g. tools/bundle_for_hub.py
was run), it does nothing. Otherwise it copies them from the fork build dir,
building the engine first if needed. On the Hub the wheel is installed, not
built, so this hook never runs there.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data) -> None:
        pkg = Path(self.root) / "nethack_core"
        so = pkg / "libnethack.so"
        dat = pkg / "dat"
        if so.is_file() and dat.is_dir():
            return  # already bundled (tools/bundle_for_hub.py or a prior build)

        build_dir = self._find_fork_build_dir()
        if build_dir is None:
            # No fork source to bundle from — e.g. the Hub's source-build
            # integration test (`uv pip install <src>` in a clean container).
            # Don't fail the build: `artifacts` includes the engine only WHEN
            # present, so the source build succeeds without it. The wheel served
            # for real installs is the one pushed from a dev tree (fork source
            # available), which DOES carry the engine.
            print(
                "[hatch_build] no fork source + no prebuilt engine — building "
                "without the bundled engine (ok for source-only/test builds).",
                file=sys.stderr,
            )
            return

        # repo_root/third_party/NetHack/src/build -> repo_root is 4 parents up.
        repo_root = build_dir.parents[3]
        src_so = build_dir / "libnethack.so"
        if not src_so.is_file():
            script = repo_root / "nethack_core" / "build_engine.sh"
            if not script.is_file():
                raise SystemExit(f"engine not built and no build script at {script}")
            print(f"[hatch_build] building engine via {script} ...", file=sys.stderr)
            subprocess.run(["bash", str(script)], cwd=repo_root, check=True)
        if not src_so.is_file():
            raise SystemExit(f"build ran but {src_so} is still missing")

        src_dat = build_dir / "dat"
        if not src_dat.is_dir():
            raise SystemExit(f"NetHack dat dir missing at {src_dat}")

        shutil.copy2(src_so, so)
        so.chmod(0o755)
        if dat.exists():
            shutil.rmtree(dat)
        shutil.copytree(src_dat, dat)
        print(f"[hatch_build] bundled libnethack.so + dat/ into {pkg}", file=sys.stderr)

    @staticmethod
    def _find_fork_build_dir() -> "Path | None":
        for parent in Path(__file__).resolve().parents:
            cand = parent / "third_party" / "NetHack" / "src" / "build"
            if cand.exists():
                return cand
        return None
