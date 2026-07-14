#!/usr/bin/env bash
# Rebuild the optimized WASM release bundle in this directory from the fork's
# compiled objects. Assumes src/build_wasm_dat.sh + src/build_wasm.sh have already
# produced build-wasm/obj/*.o and build-wasm/dat (see deploy/wasm-web/README.md).
#
#   PATH must have Python >=3.10 BEFORE emsdk (see the wasm-browser-port notes);
#   then: source <emsdk>/emsdk_env.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../../third_party/NetHack/src"
BW="$SRC/build-wasm"

EXP='["_nleweb_new_obs","_nleweb_tty_chars","_nleweb_tty_colors","_nleweb_chars","_nleweb_colors","_nleweb_glyphs","_nleweb_blstats","_nleweb_message","_nleweb_done","_nleweb_in_game","_nleweb_rows","_nleweb_cols","_nleweb_tty_rows","_nleweb_tty_cols","_nleweb_blstats_size","_nleweb_start","_nleweb_step","_nleweb_ctx","_nleweb_goto_abs","_nleweb_hero_on_stair","_nleweb_num_dungeons","_nleweb_dungeon_info","_nle_end","_malloc","_free"]'

cd "$BW"
emcc -O2 -sASYNCIFY -sASYNCIFY_STACK_SIZE=8388608 \
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=201326592 -sTOTAL_STACK=16777216 \
  -sUSE_BZIP2=1 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 -sEXPORT_NAME=NetHackModule \
  -sEXPORTED_RUNTIME_METHODS='["ccall","cwrap","UTF8ToString","stringToUTF8","HEAPU8","HEAP8","HEAP16","HEAP32"]' \
  -sEXPORTED_FUNCTIONS="$EXP" \
  --preload-file dat@/nethackdir obj/*.o -o "$HERE/nethack.js"

cp "$SRC/web/index.html" "$SRC/web/nethack_web.js" "$HERE/"
echo "release bundle refreshed in $HERE"
ls -la "$HERE"/*.wasm "$HERE"/*.data "$HERE"/*.js
