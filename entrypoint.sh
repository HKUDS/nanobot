#!/bin/sh
dir="$HOME/.nanobot"

# Render deploy path (see render.yaml + render-config.json). Gated on Render's
# automatic RENDER=true env var so local Docker/podman usage is unaffected.
if [ "$RENDER" = "true" ]; then
    echo "[entrypoint] Render deploy — starting as $(id)"
    mkdir -p "$dir" || echo "[entrypoint] warning: mkdir $dir failed"
    config="$dir/config.json"
    if [ ! -f "$config" ]; then
        echo "[entrypoint] initializing $config from render-config.json"
        cp /app/render-config.json "$config" || echo "[entrypoint] warning: cp config failed"
    else
        echo "[entrypoint] existing $config found — leaving it in place"
    fi
    set -- "$@" --config "$config"
fi

# Dokploy deploy path (see dokploy/docker-compose.yml + dokploy-config.json).
# Gated on DOKPLOY_CONFIG env var. Same pattern as Render: copy the committed
# config template on first boot, keep user edits across restarts.
if [ -n "$DOKPLOY_CONFIG" ] && [ -f "$DOKPLOY_CONFIG" ]; then
    echo "[entrypoint] Dokploy deploy — starting as $(id)"
    mkdir -p "$dir" || echo "[entrypoint] warning: mkdir $dir failed"
    config="$dir/config.json"
    if [ ! -f "$config" ]; then
        echo "[entrypoint] initializing $config from $DOKPLOY_CONFIG"
        cp "$DOKPLOY_CONFIG" "$config" || echo "[entrypoint] warning: cp config failed"
    else
        echo "[entrypoint] existing $config found — leaving it in place"
    fi
    set -- "$@" --config "$config"
fi

# Drop privileges whenever the container starts as root.
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
