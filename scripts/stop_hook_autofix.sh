#!/bin/bash
# Stop hook that requires /autofix to be run before the agent can stop.
# Reads configuration from .autofix/config/stop-hook.json.
set -euo pipefail

CONFIG_FILE=".autofix/config/stop-hook.json"

# Read config values from JSON using jq
_read_config() {
    local key="$1"
    local default="$2"
    if [ -f "$CONFIG_FILE" ]; then
        local val
        val=$(jq -r --arg k "$key" '.[$k] // empty' "$CONFIG_FILE" 2>/dev/null)
        if [ -n "$val" ]; then
            echo "$val"
            return
        fi
    fi
    echo "$default"
}

ENABLED=$(_read_config "enabled" "true")
if [ "$ENABLED" != "true" ]; then
    exit 0
fi

HASH=$(git rev-parse HEAD 2>/dev/null) || exit 0

if [ -f ".autofix/plans/${HASH}_verified.md" ]; then
    # Verified -- clear any stuck tracking and allow stop.
    rm -f .autofix/blocked_commits
    exit 0
fi

# Track how many times we've blocked at the same commit. If the agent is stuck
# (e.g. /autofix crashes before writing the marker), allow it through after 3
# attempts rather than looping forever.
STUCK_FILE=".autofix/blocked_commits"
echo "$HASH" >> "$STUCK_FILE"
if [ -f "$STUCK_FILE" ]; then
    LAST_THREE=$(tail -n 3 "$STUCK_FILE")
    ENTRY_COUNT=$(echo "$LAST_THREE" | wc -l | tr -d ' ')
    if [ "$ENTRY_COUNT" -ge 3 ]; then
        UNIQUE_COUNT=$(echo "$LAST_THREE" | sort -u | wc -l | tr -d ' ')
        if [ "$UNIQUE_COUNT" -eq 1 ]; then
            echo "WARNING: Autofix has been unable to verify this commit after 3 attempts." >&2
            echo "WARNING: Allowing stop to proceed. Please investigate manually." >&2
            rm -f "$STUCK_FILE"
            exit 0
        fi
    fi
fi

EXTRA_ARGS=$(_read_config "extra_args" "")

if [ -n "$EXTRA_ARGS" ]; then
    echo "To verify your changes, run: \"/autofix ${EXTRA_ARGS}\"" >&2
else
    echo "To verify your changes, run: \"/autofix\"" >&2
fi
exit 2
