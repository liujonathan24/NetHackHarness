# Deploy the live Map Viewer to Hugging Face Spaces (free)

GitHub Pages can't run this (it's static-only; the dashboard needs a Flask server
+ the compiled C engine). A **Hugging Face Docker Space** hosts it free, with a
persistent public URL and no credit card.

## Steps

1. Get a **write** token: https://huggingface.co/settings/tokens
2. Authenticate (sets up the git credential helper too):
   ```
   hf auth login
   ```
3. Deploy:
   ```
   bash deploy/hf-space/deploy.sh          # or: deploy.sh my-space-name
   ```
4. Open the printed URL after the build finishes (~3–5 min for the first build).

## How it works

- `Dockerfile` clones the public repo + engine submodule, builds `libnethack.so`,
  installs Flask, and runs `tools/play_server.py` on port 7860 (HF's `app_port`).
- `ARG REF` selects the branch to build. It defaults to `curriculum-dashboard`
  (the branch with curriculum mode); change to `main` once that PR is merged.

## Notes / limits

- **Single shared game**: the server holds one global `EngineEnv`, so it's a
  single-player demo — concurrent visitors share the same board.
- Free CPU Spaces sleep after ~48h idle and rebuild on wake.
- To update, push a trivial change or hit "Factory rebuild" in the Space settings.
