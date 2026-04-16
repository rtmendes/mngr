#!/bin/bash
# Wrapper script that starts the Docker daemon (if not already running)
# and then exec's the given command with all arguments.
# Available in release images as a command prefix for scripts that need Docker.
set -euo pipefail

if ! docker info >/dev/null 2>&1 && [ -x /start-dockerd.sh ]; then
    # Capture combined output so we can surface it on failure. start-dockerd.sh
    # runs with `set -x`, which is noisy on success, so we only print the log
    # when the script fails (to aid debugging of opaque dockerd startup issues).
    dockerd_log=$(mktemp)
    if ! /start-dockerd.sh >"$dockerd_log" 2>&1; then
        rc=$?
        echo "start-dockerd.sh failed (exit $rc); output follows:" >&2
        cat "$dockerd_log" >&2
        exit "$rc"
    fi
fi

exec "$@"
