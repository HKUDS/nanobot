FROM python:3.11-slim-bookworm

# Install runtime dependencies only (no Node.js — WhatsApp bridge is optional)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
# bridge/ is in .dockerignore but pyproject.toml force-includes it in the wheel;
# create an empty stub so hatchling doesn't fail during dependency resolution.
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot bridge && touch nanobot/__init__.py && \
    pip install --no-cache-dir . && \
    rm -rf nanobot bridge

# Copy the full source and install
COPY nanobot/ nanobot/
RUN mkdir -p bridge && pip install --no-cache-dir .

# Create a non-root user and config directory
RUN groupadd --gid 1001 nanobot && \
    useradd --uid 1001 --gid nanobot --shell /bin/bash --create-home nanobot && \
    mkdir -p /home/nanobot/.nanobot && \
    chown -R nanobot:nanobot /home/nanobot /app

USER nanobot

# Health check for orchestrators (Docker, Compose, Kubernetes)
# Uses NANOBOT_GATEWAY__PORT if set (e.g. staging uses 18791), falls back to 18790.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf "http://localhost:${NANOBOT_GATEWAY__PORT:-18790}/health" || exit 1

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["nanobot"]
CMD ["status"]
