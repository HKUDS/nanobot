FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG INSTALL_NODE=false
ARG INSTALL_BRIDGE=false
ARG EXTRAS=""

# ── Base system deps ──
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# ── Optional: Node.js 20 (needed for WhatsApp bridge) ──
RUN if [ "$INSTALL_NODE" = "true" ]; then \
      apt-get update && \
      apt-get install -y --no-install-recommends curl gnupg git openssh-client && \
      mkdir -p /etc/apt/keyrings && \
      curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | \
        gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
      echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list && \
      apt-get update && \
      apt-get install -y --no-install-recommends nodejs && \
      apt-get purge -y gnupg && apt-get autoremove -y && \
      rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app

# ── Python deps (cached layer) ──
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot bridge && touch nanobot/__init__.py && \
    if [ -n "$EXTRAS" ]; then \
      uv pip install --system --no-cache ".[$EXTRAS]"; \
    else \
      uv pip install --system --no-cache .; \
    fi && \
    rm -rf nanobot bridge

# ── App source ──
COPY nanobot/ nanobot/
COPY bridge/ bridge/

# ── Optional: WhatsApp bridge ──
RUN if [ "$INSTALL_BRIDGE" = "true" ]; then \
      git config --global url."https://github.com/".insteadOf "ssh://git@github.com/" && \
      cd bridge && npm install && npm run build && cd ..; \
    fi

# ── Final install with source ──
RUN if [ -n "$EXTRAS" ]; then \
      uv pip install --system --no-cache ".[$EXTRAS]"; \
    else \
      uv pip install --system --no-cache .; \
    fi

RUN mkdir -p /root/.nanobot
EXPOSE 18790
ENTRYPOINT ["nanobot"]
CMD ["gateway"]
