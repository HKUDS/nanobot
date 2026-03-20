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

# Strip build-only packages from the install tree.  pip/setuptools/wheel/hatchling
# are needed to build wheels but must not reach the runtime image (CVE surface).
RUN pip install --prefix=/install pip && \
    PYTHONPATH=/install/lib/python3.11/site-packages /install/bin/pip \
        uninstall -y --root=/install pip setuptools wheel hatchling \
        hatchling pathspec pluggy trove-classifiers editables 2>/dev/null; \
    rm -rf /install/bin/pip* /install/bin/wheel 2>/dev/null; true
# Fallback: brute-force remove any remaining dist-info for build tools.
# Uses full paths instead of cd to avoid Trivy DS-0013 linting warning.
RUN rm -rf /install/lib/python3.11/site-packages/pip* \
           /install/lib/python3.11/site-packages/setuptools* \
           /install/lib/python3.11/site-packages/wheel* \
           /install/lib/python3.11/site-packages/hatchling* \
           /install/lib/python3.11/site-packages/_distutils_hack* \
           /install/lib/python3.11/site-packages/pkg_resources* \
           /install/lib/python3.11/site-packages/distutils* \
           /install/lib/python3.11/site-packages/pathspec* \
           /install/lib/python3.11/site-packages/pluggy* \
           /install/lib/python3.11/site-packages/trove_classifiers* \
           /install/lib/python3.11/site-packages/editables* \
           2>/dev/null; true


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

# Remove build tools that ship with the base image (separate from builder overlay).
RUN rm -rf /usr/local/lib/python3.11/ensurepip \
           /usr/local/lib/python3.11/distutils \
           /usr/local/lib/python3.11/site-packages/pip* \
           /usr/local/lib/python3.11/site-packages/setuptools* \
           /usr/local/lib/python3.11/site-packages/wheel* \
           /usr/local/lib/python3.11/site-packages/pkg_resources* \
           /usr/local/lib/python3.11/site-packages/_distutils_hack* \
           /usr/local/lib/python3.11/site-packages/distutils-precedence.pth \
           /usr/local/bin/pip* 2>/dev/null; true

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
