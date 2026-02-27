#!/bin/bash
set -e

# Set permissive umask so files created by root inside the container
# are writable by the host user (who may not be root).
umask 0000

exec nanobot "$@"
