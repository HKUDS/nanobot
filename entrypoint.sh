#!/bin/sh
dir="$HOME/.nanobot"

# Render deploy path (see render.yaml + render-config.json). Gated on Render's
# automatic RENDER=true env var so local Docker/podman usage is unaffected.
# Copies the committed config template onto the mounted disk (wiring secrets via
# ${VAR} env vars and keeping runtime data on the persistent disk), chowns the
# root-owned mount, then drops to the non-root nanobot user. Logs each decision
# so a failed start is diagnosable in Render's logs.
if [ "$RENDER" = "true" ]; then
    echo "[entrypoint] Render deploy — starting as $(id)"
    mkdir -p "$dir" || echo "[entrypoint] warning: mkdir $dir failed"
    config="$dir/config.json"
    cp /app/render-config.json "$config" || echo "[entrypoint] warning: cp config failed"
    if [ "$(id -u)" = "0" ]; then
        chown -R nanobot:nanobot "$dir" || echo "[entrypoint] warning: chown $dir failed"
        if setpriv --reuid=nanobot --regid=nanobot --init-groups true 2>/dev/null; then
            echo "[entrypoint] dropping privileges to nanobot via setpriv"
            exec setpriv --reuid=nanobot --regid=nanobot --init-groups nanobot "$@" --config "$config"
        fi
        echo "[entrypoint] setpriv privilege-drop not permitted — running as root"
    fi
    exec nanobot "$@" --config "$config"
fi

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
