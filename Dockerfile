FROM python:3.11-slim-bookworm

# Runtime system dependencies (no Node.js — WhatsApp bridge is optional)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade build tooling to patch known CVEs in the base image's bundled
# pip/wheel/setuptools (CVE-2026-24049, CVE-2026-23949, CVE-2026-1703).
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# --- Dependency cache layer ---
# Copy only build metadata and the bridge source (~10KB).
# bridge/ is required because pyproject.toml [tool.hatch.build.targets.wheel.force-include]
# maps "bridge" → "nanobot/bridge" — hatchling fails if the directory is missing.
# A stub nanobot/__init__.py satisfies package discovery so pip can resolve deps
# without the real source tree.  This layer only rebuilds when deps change.
COPY pyproject.toml README.md LICENSE ./
COPY bridge/ bridge/
RUN mkdir -p nanobot && touch nanobot/__init__.py && \
    pip install --no-cache-dir . && \
    rm -rf nanobot __pycache__

# --- Application layer ---
# Only rebuilds when Python source changes.
# --no-deps: all dependencies are already installed above; skip the resolver.
COPY nanobot/ nanobot/
RUN pip install --no-cache-dir --no-deps .

# Non-root user and config directory
RUN groupadd --gid 1001 nanobot && \
    useradd --uid 1001 --gid nanobot --shell /bin/bash --create-home nanobot && \
    mkdir -p /home/nanobot/.nanobot && \
    chown -R nanobot:nanobot /home/nanobot /app

USER nanobot

# Health check for orchestrators (Docker, Compose, Kubernetes).
# Reads NANOBOT_GATEWAY__PORT if set (e.g. staging uses 18791), falls back to 18790.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf "http://localhost:${NANOBOT_GATEWAY__PORT:-18790}/health" || exit 1

EXPOSE 18790

ENTRYPOINT ["nanobot"]
CMD ["status"]
