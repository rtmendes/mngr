#!/bin/bash
# Sourced via BASH_ENV before every bash -c command in the sandbox.
# Starts the Docker daemon if it's not already running and we're in a
# runtime sandbox (not during image build). Errors are silently ignored
# so this is safe to source during builds or non-Docker sandboxes.
if [ -x /start-dockerd.sh ] && ! docker info >/dev/null 2>&1; then
    /start-dockerd.sh >/dev/null 2>&1 || true
fi
