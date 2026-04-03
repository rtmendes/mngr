#!/usr/bin/env bash
set -euo pipefail

# Idempotent setup of the nightly changelog consolidation agent.
#
# This script ensures exactly one "changelog-consolidation" schedule exists.
# Safe to run multiple times: skips creation if the schedule already exists,
# so there is never a risk of duplicate agents.
#
# The scheduled agent runs at midnight PST, reads all per-PR changelog files
# from changelog/, consolidates them into CHANGELOG.md, deletes the individual
# files, commits, and opens a PR.
#
# Usage:
#   ./scripts/setup_changelog_agent.sh
#
# Environment:
#   CHANGELOG_PROVIDER  - Provider to use (default: "local"). Set to "modal"
#                         for production use (requires Modal credentials).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

TRIGGER_NAME="changelog-consolidation"
# Midnight PST (UTC-8) = 08:00 UTC.
# During PDT (March-November), this fires at 01:00 local time.
SCHEDULE="0 8 * * *"
PROVIDER="${CHANGELOG_PROVIDER:-local}"

# Check if the trigger already exists by listing schedules as JSON.
EXISTING=$(uv run mngr schedule list --provider "$PROVIDER" --all --format json 2>/dev/null || echo '{"schedules":[]}')
if echo "$EXISTING" | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [s['trigger']['name'] for s in data.get('schedules', [])]
sys.exit(0 if '${TRIGGER_NAME}' in names else 1)
" 2>/dev/null; then
    echo "Schedule '${TRIGGER_NAME}' already exists. No action needed."
    exit 0
fi

echo "Creating schedule '${TRIGGER_NAME}'..."

# Build the args string for mngr create. Using shlex-compatible quoting:
# the outer single quotes protect the entire --args value from bash,
# and inner double quotes delimit the --message value for shlex.split().
uv run mngr schedule add "$TRIGGER_NAME" \
    --command create \
    --schedule "$SCHEDULE" \
    --provider "$PROVIDER" \
    --no-ensure-safe-commands \
    --args '--type claude --branch :mngr/changelog-consolidation-{DATE} --message "Consolidate the changelog. Read all .md files in changelog/ (ignore .gitkeep). If there are none, exit without changes. Otherwise, prepend a new section to CHANGELOG.md with today'\''s date as heading (## YYYY-MM-DD), include the content of each changelog file, then delete the individual changelog .md files (keep .gitkeep). Commit the result."'

echo "Schedule '${TRIGGER_NAME}' created successfully."
