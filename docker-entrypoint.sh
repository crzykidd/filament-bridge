#!/bin/sh
set -e
# Ensure the data dir is writable by the runtime user, then drop privileges.
# Allow override via PUID/PGID (default 1000:1000).
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
mkdir -p "${DATA_DIR:-/data}"
chown -R "${PUID}:${PGID}" "${DATA_DIR:-/data}" 2>/dev/null || true
# If already running as non-root (e.g. compose set `user:`), just exec.
if [ "$(id -u)" = "0" ]; then
  exec gosu "${PUID}:${PGID}" "$@"
else
  exec "$@"
fi
