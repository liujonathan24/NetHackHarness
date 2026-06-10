#!/usr/bin/env bash
# Run a NetHack eval and auto-save it under environments/nethack/outputs/evals/<name>
# so the run shows up in the rollout viewer + file browser (no more /tmp).
#
# Usage:
#   tools/run_eval.sh <name> '<env-args-json>' [extra prime flags...]
# Env overrides: MODEL, N (num-examples), C (max-concurrent), and any env var
# the env reads (e.g. NETHACK_DISABLE_PET=1 for the no-pet ablation).
#
# Example:
#   N=24 tools/run_eval.sh n24_B1 '{"variant":"B1","skill_set":"netplay","tier":"full_dungeon_easy","max_turns":150}'
set -euo pipefail
if [ "$#" -lt 2 ]; then
  echo "usage: tools/run_eval.sh <name> '<env-args-json>' [extra prime flags...]" >&2
  exit 2
fi
NAME="$1"; ENVARGS="$2"; shift 2
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/environments/nethack/outputs/evals/$NAME"
mkdir -p "$OUT"
cd "$ROOT/environments/nethack"
prime eval run nethack -m "${MODEL:-qwen/qwen3-vl-235b-a22b-instruct}" -p prime \
  --env-dir-path . -a "$ENVARGS" \
  --num-examples "${N:-24}" --rollouts-per-example 1 --max-concurrent "${C:-8}" \
  --state-columns "max_dlvl_reached,succeeded,terminated,descent_count,died" \
  --save-results --output-dir "$OUT" --abbreviated-summary --disable-tui "$@"
echo "saved to $OUT"
