#!/usr/bin/env bash
# One-command deploy of the Map Viewer dashboard to a Hugging Face Docker Space.
#
# Prereq (once):  hf auth login    # paste a WRITE token from
#                                  # https://huggingface.co/settings/tokens
# Usage:          bash deploy/hf-space/deploy.sh [space-name]
set -euo pipefail
SPACE_NAME="${1:-nethack-curriculum-console}"
HERE="$(cd "$(dirname "$0")" && pwd)"

USER="$(hf auth whoami 2>/dev/null | head -1)"
if [ -z "${USER:-}" ] || [ "$USER" = "Not logged in" ]; then
  echo "Not logged in. Run:  hf auth login   (a WRITE token), then re-run." >&2
  exit 1
fi
REPO_ID="$USER/$SPACE_NAME"
echo "Deploying to Hugging Face Space: $REPO_ID"

# Create the Docker Space (idempotent).
hf repo create "$REPO_ID" --repo-type space --space_sdk docker --exist-ok

# Push the Dockerfile + README (the image clones the app repo itself at build).
WORK="$(mktemp -d)"
git clone "https://huggingface.co/spaces/$REPO_ID" "$WORK" 2>/dev/null || {
  echo "clone failed — is 'hf auth login' set up as the git credential helper?" >&2; exit 1; }
cp "$HERE/Dockerfile" "$HERE/README.md" "$WORK/"
( cd "$WORK" && git add Dockerfile README.md \
    && git commit -qm "deploy NetHack curriculum Map Viewer" \
    && git push )
echo
echo "Done. Live (after the build finishes, ~3-5 min):"
echo "  https://huggingface.co/spaces/$REPO_ID"
