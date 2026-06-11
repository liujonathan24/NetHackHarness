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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "nethack_core"
DST = ROOT / "environments" / "nethack" / "nethack_core"


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
