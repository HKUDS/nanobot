# ============== STAGE 1: Builder ==============
# Build tools (pip, setuptools, wheel, hatchling) live here and never
# reach the runtime image — eliminating their CVEs from Trivy scans.
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy build metadata + bridge source (~10KB).
# bridge/ is required by pyproject.toml [tool.hatch.build.targets.wheel.force-include]
# which maps "bridge" → "nanobot/bridge" inside the wheel.
COPY pyproject.toml README.md LICENSE ./
COPY bridge/ bridge/

# Dependency cache layer: stub package satisfies hatchling discovery,
# --prefix=/install isolates installed packages for clean COPY later.
RUN mkdir -p nanobot && touch nanobot/__init__.py && \
    pip install --no-cache-dir --prefix=/install .

# Application layer: only rebuilds when nanobot/ source changes.
# --no-deps skips dependency resolution (already installed above).
COPY nanobot/ nanobot/
RUN pip install --no-cache-dir --no-deps --prefix=/install .


# ============== STAGE 2: Runtime ==============
# Clean image: only curl, ca-certificates, Python stdlib, and installed packages.
# No pip, setuptools, wheel, or hatchling — no build-tool CVEs.
FROM python:3.11-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Merge the --prefix=/install tree (site-packages + bin/ scripts) into system Python.
COPY --from=builder /install /usr/local

# Remove build tools that ship with the base image — they are not needed at runtime
# and create unnecessary CVE surface for Trivy scans.
RUN pip uninstall -y pip setuptools 2>/dev/null; \
    rm -rf /usr/local/lib/python3.11/ensurepip /usr/local/lib/python3.11/distutils; \
    true

# Non-root user
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
