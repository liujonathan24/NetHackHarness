# Hugging Face Docker Space — live NetHack Map Viewer with Curriculum tour mode.
#
# Thin image: clones the PUBLIC GitHub repo + engine submodule at build time,
# builds libnethack.so from source, installs Flask, and serves play_server on the
# HF Spaces port (7860). No secrets needed — everything cloned is public.
#
# Build ARGs let you point at a branch/commit; REF defaults to the branch that
# carries the curriculum-mode dashboard until it merges to main.
FROM python:3.11-slim

RUN apt-get update -qq && apt-get install --no-install-recommends -y \
      cmake bison flex libbz2-dev build-essential git ca-certificates curl file \
    && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /opt/app
ARG REPO=https://github.com/liujonathan24/NetHackHarness
ARG REF=curriculum-dashboard
RUN git clone --branch "${REF}" "${REPO}" . \
    && git submodule update --init third_party/NetHack

# Build the fork engine (native arch), then install the packages + Flask.
RUN bash nethack_core/build_engine.sh
RUN uv pip install --system -e nethack_core \
    && uv pip install --system -e environments/nethack \
    && uv pip install --system "flask>=3.1.3"

# HF Spaces route external traffic to app_port (README metadata) = 7860.
EXPOSE 7860
CMD ["python", "tools/play_server.py", "--host", "0.0.0.0", "--port", "7860"]
