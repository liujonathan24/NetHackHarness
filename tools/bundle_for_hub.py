"""Vendor nethack_core/*.py into environments/nethack/nethack_core/ for Hub push.

The Prime Environments Hub installs the env directory as a standalone tarball,
so the workspace dep `nethack-core` is unresolvable there. This script copies
the substrate into the env directory so the wheel built by `prime env push`
is self-contained.

Run before `prime env push`:

    python tools/bundle_for_hub.py
    cd environments/nethack && prime env push --visibility=PRIVATE --auto-bump
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "nethack_core"
DST = ROOT / "environments" / "nethack" / "nethack_core"
# Prebuilt engine binary. The fork source (third_party/NetHack) is NOT shipped to
# the Hub, so the wheel must carry the compiled libnethack.so. _engine.py's
# locator looks for it next to the package (nethack_core/libnethack.so) when no
# third_party/ build dir is present.
ENGINE_BUILD = ROOT / "third_party" / "NetHack" / "src" / "build"
ENGINE_SO = ENGINE_BUILD / "libnethack.so"
ENGINE_DAT = ENGINE_BUILD / "dat"
BUILD_SCRIPT = SRC / "build_engine.sh"


def _ensure_engine_built() -> Path:
    """Return the path to a freshly-available libnethack.so, building if needed.

    The Hub wheel is self-contained (no fork source on the Hub), so a prebuilt
    .so must be bundled. Build it on demand if it's missing. x86-64 Linux only.
    """
    if ENGINE_SO.is_file():
        return ENGINE_SO
    if not BUILD_SCRIPT.is_file():
        raise SystemExit(
            f"engine not built and no build script at {BUILD_SCRIPT}. "
            "Run `git submodule update --init --recursive` first."
        )
    print(f"libnethack.so not found — building via {BUILD_SCRIPT.relative_to(ROOT)} ...")
    subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=ROOT, check=True)
    if not ENGINE_SO.is_file():
        raise SystemExit(f"build_engine.sh ran but {ENGINE_SO} is still missing.")
    return ENGINE_SO


def main() -> None:
    if not SRC.is_dir():
        raise SystemExit(f"source not found: {SRC}")

    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    copied = 0
    for py in SRC.glob("*.py"):
        shutil.copy2(py, DST / py.name)
        copied += 1

    # The ctypes engine binding (_engine.py / engine_env.py, copied above) needs
    # its build script too; it is not a *.py file.
    build_sh = SRC / "build_engine.sh"
    if build_sh.is_file():
        shutil.copy2(build_sh, DST / build_sh.name)
        (DST / build_sh.name).chmod(0o755)
        copied += 1

    init = DST / "__init__.py"
    if not init.exists():
        init.write_text('"""Vendored nethack_core for Hub deployment. Edit nethack_core/ in the workspace root, not here."""\n')

    print(f"bundled {copied} modules into {DST.relative_to(ROOT)}")

    # Bundle the prebuilt engine binary + NetHack data files — without these the
    # Hub wheel imports but crashes at first use with EngineNotBuilt (no fork
    # source to build from). The engine loads the .so and copies the dat/ tree
    # into a temp hackdir on every start().
    engine = _ensure_engine_built()
    so_dst = DST / "libnethack.so"
    shutil.copy2(engine, so_dst)
    so_dst.chmod(0o755)
    print(f"bundled engine libnethack.so ({engine.stat().st_size:,} bytes) into {so_dst.relative_to(ROOT)}")

    if not ENGINE_DAT.is_dir():
        raise SystemExit(f"engine dat dir missing at {ENGINE_DAT}; rerun build_engine.sh")
    dat_dst = DST / "dat"
    if dat_dst.exists():
        shutil.rmtree(dat_dst)
    shutil.copytree(ENGINE_DAT, dat_dst)
    n_dat = sum(1 for _ in dat_dst.rglob("*") if _.is_file())
    print(f"bundled engine dat/ ({n_dat} files) into {dat_dst.relative_to(ROOT)}")

    # Also copy the wiki snapshot into the env dir so the wheel's
    # `force-include` for wiki/snapshot.json finds it. Without this,
    # `prime env push` fails with `Forced include not found`.
    wiki_src = ROOT / "wiki" / "snapshot.json"
    wiki_dst = ROOT / "environments" / "nethack" / "wiki" / "snapshot.json"
    if wiki_src.is_file():
        wiki_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wiki_src, wiki_dst)
        print(f"bundled wiki snapshot ({wiki_src.stat().st_size} bytes) into {wiki_dst.relative_to(ROOT)}")
    else:
        print(f"(no wiki/snapshot.json at workspace root — skipping bundle; run tools/build_wiki_index.py first)")


if __name__ == "__main__":
    main()
