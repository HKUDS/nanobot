FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

# Install runtime dependencies only (no Node.js — WhatsApp bridge is optional)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot bridge && touch nanobot/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf nanobot bridge

# Copy the full source and install
COPY nanobot/ nanobot/
RUN mkdir -p bridge && uv pip install --system --no-cache .

# Create config directory
RUN mkdir -p /root/.nanobot

# Health check for orchestrators (Docker, Compose, Kubernetes)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:18790/health || exit 1

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["nanobot"]
CMD ["status"]
