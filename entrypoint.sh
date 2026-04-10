#!/bin/sh
dir="$HOME/.hiperone"
if [ -d "$dir" ] && [ ! -w "$dir" ]; then
    owner_uid=$(stat -c %u "$dir" 2>/dev/null || stat -f %u "$dir" 2>/dev/null)
    cat >&2 <<EOF
Error: $dir is not writable (owned by UID $owner_uid, running as UID $(id -u)).

Fix (pick one):
  Host:   sudo chown -R root:root ~/.hiperone
  Docker: docker run -v ~/.hiperone:/root/.hiperone ...
EOF
    exit 1
fi
exec nanobot "$@"
