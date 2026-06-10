#!/usr/bin/env bash
# Build libnethack.so + game data from the pinned NetHack fork submodule.
# Reproducible: configures cmake from the submodule source (deps vendored in
# src/third_party/), so it does not depend on any external checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SRC="$ROOT/third_party/NetHack/src"
BUILD="$SRC/build"

# (Re)configure from scratch if the cache is missing or was generated from a
# different source tree (e.g. a stale cache committed from another machine).
if [ ! -f "$BUILD/CMakeCache.txt" ] || \
   ! grep -q "^CMAKE_HOME_DIRECTORY:INTERNAL=$SRC\$" "$BUILD/CMakeCache.txt"; then
  rm -rf "$BUILD"
  cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=RelWithDebInfo
fi
cmake --build "$BUILD" --target nethack -j"${JOBS:-8}"

echo "Built: $BUILD/libnethack.so"
ls -l "$BUILD/libnethack.so"
file "$BUILD/libnethack.so"
