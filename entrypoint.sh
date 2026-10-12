#!/bin/sh
dir="$HOME/.nanobot"

# Container config bootstrap. Two deploy paths share the init-once logic:
# - Render (RENDER=true): template wires secrets via ${VAR} env vars, resolved
#   at startup by the config loader.
# - Local Docker (NANOBOT_DOCKER_BOOTSTRAP=1, set by docker-compose.yml): a
#   template with binds that work across the container boundary, and secrets
#   baked in at first boot (env value if provided, otherwise generated) so a
#   missing env var can never crash-loop the containers.
# Initializes the on-disk config only when it does not already exist, so
# WebUI/provider settings edited at runtime survive restarts.
# Logs each decision so a failed start is diagnosable in the container logs.
# Privilege dropping is handled below, for every root start (not just here).
if [ "$RENDER" = "true" ] || [ "$NANOBOT_DOCKER_BOOTSTRAP" = "1" ]; then
    echo "[entrypoint] container deploy — starting as $(id)"
    mkdir -p "$dir" || echo "[entrypoint] warning: mkdir $dir failed"
    config="$dir/config.json"
    if [ ! -f "$config" ]; then
        if [ "$RENDER" = "true" ]; then
            echo "[entrypoint] initializing $config from render-config.json"
            cp /app/render-config.json "$config" || echo "[entrypoint] warning: cp config failed"
        else
            web_token="${NANOBOT_WEB_TOKEN:-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')}"
            api_key="${NANOBOT_API_KEY:-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')}"
            echo "[entrypoint] initializing $config from docker-config.json"
            sed -e "s|\${NANOBOT_WEB_TOKEN}|$web_token|" \
                -e "s|\${NANOBOT_API_KEY}|$api_key|" \
                /app/docker-config.json > "$config" \
                || echo "[entrypoint] warning: config bootstrap failed"
            echo "[entrypoint] WebUI: http://localhost:8765 — password: $web_token"
            echo "[entrypoint] OpenAI-compatible API: http://127.0.0.1:8900/v1 — api key: $api_key"
        fi
    else
        echo "[entrypoint] existing $config found — leaving it in place"
        if [ "$NANOBOT_DOCKER_BOOTSTRAP" = "1" ]; then
            echo "[entrypoint] WebUI password lives in $config (channels.websocket.tokenIssueSecret)"
        fi
    fi
    set -- "$@" --config "$config"
fi

# Drop privileges whenever the container starts as root. Render mounts the
# persistent disk root-owned, and a plain `docker run` also defaults to root now,
# so this covers both. Chown the data dir so the non-root user can write it, then
# re-exec as nanobot. Fail closed: if the privilege drop cannot be performed,
# exit rather than run the agent as root.
if [ "$(id -u)" = "0" ]; then
    chown -R nanobot:nanobot "$dir" 2>/dev/null || echo "[entrypoint] warning: chown $dir failed"
    if setpriv --reuid=nanobot --regid=nanobot --init-groups true 2>/dev/null; then
        echo "[entrypoint] dropping privileges to nanobot via setpriv"
        exec setpriv --reuid=nanobot --regid=nanobot --init-groups nanobot "$@"
    fi
    echo "[entrypoint] error: started as root but setpriv privilege drop failed — refusing to run as root" >&2
    exit 1
fi

# Already non-root: make sure the data dir is writable before starting.
if [ -d "$dir" ] && [ ! -w "$dir" ]; then
    owner_uid=$(stat -c %u "$dir" 2>/dev/null || stat -f %u "$dir" 2>/dev/null)
    cat >&2 <<EOF
Error: $dir is not writable (owned by UID $owner_uid, running as UID $(id -u)).

Fix (pick one):
  Host:   sudo chown -R 1000:1000 ~/.nanobot
  Docker: docker run --user \$(id -u):\$(id -g) ...
  Podman: podman run --userns=keep-id ...
EOF
    exit 1
fi

exec nanobot "$@"
