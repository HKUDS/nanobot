FROM node:24-bookworm-slim AS webui-builder

WORKDIR /app
COPY webui/package.json webui/package-lock.json ./webui/
WORKDIR /app/webui
RUN npm ci
COPY webui/ ./
COPY packages/client-events/ /app/packages/client-events/
COPY nanobot/command/locales/ /app/nanobot/command/locales/
COPY nanobot/channels/ /app/nanobot/channels/
RUN mkdir -p /app/nanobot/web && npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl git bubblewrap openssh-client libmagic1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Keep the runtime environment writable by the non-root nanobot user. Enabled
# channels may install their manifest-declared dependencies at startup.
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN uv venv --seed "$VIRTUAL_ENV"

ARG NANOBOT_EXTRAS=
COPY pyproject.toml ./
RUN set -- && \
    for extra in $(printf '%s' "$NANOBOT_EXTRAS" | tr ',' ' '); do \
        set -- "$@" --extra "$extra"; \
    done && \
    uv pip install --python "$VIRTUAL_ENV/bin/python" --no-cache -r pyproject.toml "$@"

COPY README.md LICENSE THIRD_PARTY_NOTICES.md hatch_build.py ./
COPY docs/ docs/
COPY nanobot/ nanobot/
COPY scripts/install_channel_dependencies.py scripts/
COPY --from=webui-builder /app/nanobot/web/dist/ nanobot/web/dist/
RUN NANOBOT_SKIP_WEBUI_BUILD=1 uv pip install --python "$VIRTUAL_ENV/bin/python" --no-cache --no-deps .

ARG NANOBOT_CHANNELS=whatsapp
RUN for channel in $(printf '%s' "$NANOBOT_CHANNELS" | tr ',' ' '); do \
        python -m scripts.install_channel_dependencies "$channel"; \
    done

# Keep the Render template outside the data directory so a mounted disk won't hide it.
COPY render-config.json ./

RUN useradd -m -u 1000 -s /bin/bash nanobot && \
    mkdir -p /home/nanobot/.nanobot && \
    chown -R nanobot:nanobot /home/nanobot /app/.venv

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

# Render mounts its persistent disk as root. entrypoint.sh fixes ownership before dropping privileges.
USER root
ENV HOME=/home/nanobot
# Ensure crash output reaches Render logs (app output is otherwise swallowed on
# non-graceful exit).
ENV PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1

EXPOSE 18790 8765

ENTRYPOINT ["entrypoint.sh"]
CMD ["status"]
