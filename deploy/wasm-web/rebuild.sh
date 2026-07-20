#!/usr/bin/env bash
# Rebuild the optimized WASM release bundle in this directory from the fork's
# compiled objects. Assumes src/build_wasm_dat.sh + src/build_wasm.sh have already
# produced build-wasm/obj/*.o and build-wasm/dat (see deploy/wasm-web/README.md).
#
#   PATH must have Python >=3.10 BEFORE emsdk (see the wasm-browser-port notes);
#   then: source <emsdk>/emsdk_env.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SRC="$REPO/third_party/NetHack/src"
BW="$SRC/build-wasm"

EXP='["_nleweb_new_obs","_nleweb_tty_chars","_nleweb_tty_colors","_nleweb_chars","_nleweb_colors","_nleweb_glyphs","_nleweb_blstats","_nleweb_message","_nleweb_misc","_nleweb_done","_nleweb_in_game","_nleweb_rows","_nleweb_cols","_nleweb_tty_rows","_nleweb_tty_cols","_nleweb_blstats_size","_nleweb_start","_nleweb_step","_nleweb_ctx","_nleweb_goto_abs","_nleweb_hero_on_stair","_nleweb_num_dungeons","_nleweb_dungeon_info","_nleweb_tune_count","_nleweb_tune_name","_nleweb_set_tune","_nleweb_clear_tune","_nleweb_get_tune","_nleweb_live_tune","_nleweb_set_state","_nleweb_goto_depth","_nleweb_seat_on_stair","_nleweb_level_up","_nle_end","_malloc","_free"]'

cd "$BW"
# Fixed 256 MB (NO ALLOW_MEMORY_GROWTH): a growable wasm memory is backed by a
# resizable ArrayBuffer, which TextDecoder rejects in current browsers ("must not
# be resizable"). A fixed memory is a plain ArrayBuffer, so string decoding works.
emcc -O2 -sASYNCIFY -sASYNCIFY_STACK_SIZE=8388608 \
  -sINITIAL_MEMORY=268435456 -sTOTAL_STACK=16777216 \
  -sUSE_BZIP2=1 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 -sEXPORT_NAME=NetHackModule \
  -sEXPORTED_RUNTIME_METHODS='["ccall","cwrap","UTF8ToString","stringToUTF8","HEAPU8","HEAP8","HEAP16","HEAP32","HEAPF64"]' \
  -sEXPORTED_FUNCTIONS="$EXP" \
  --preload-file dat@/nethackdir obj/*.o -o "$HERE/nethack.js"

# Map Viewer page + client-side backend shim (from the fork) ...
cp "$SRC/web/play.html" "$SRC/web/console_backend.js" "$HERE/"
# ... and the UNCHANGED local-app UI assets (from the harness webconsole). The
# three static pages add only NEW selectors, kept in console.extra.css, so these
# two files stay byte-identical to the Flask console's and this cp is safe.
cp "$REPO/tools/webconsole/static/console.js" "$REPO/tools/webconsole/static/console.css" "$HERE/"

# Recorded agent trials -> static JSON for the Replays page. TRIALS_ROOT holds one
# directory per trial (<agent>_seed<N>_<OK|FAIL>_dlvl<D>/*.ndjson).
if [ -n "${TRIALS_ROOT:-}" ]; then
  (cd "$REPO" && python3 tools/export_trials.py --root "$TRIALS_ROOT" --out "$HERE/trials")
else
  echo "note: TRIALS_ROOT unset — keeping the committed $HERE/trials as-is"
fi

echo "release bundle refreshed in $HERE"
ls -la "$HERE"/*.wasm "$HERE"/*.data "$HERE"/*.js "$HERE"/*.css "$HERE"/*.html
