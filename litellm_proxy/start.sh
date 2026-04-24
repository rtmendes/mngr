#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load env vars from .env
source "$REPO_ROOT/.env"

PORT="${1:-4000}"

echo "Starting LiteLLM proxy on port $PORT..."
echo ""
echo "To use with claude -p, run:"
echo "  ANTHROPIC_BASE_URL=http://localhost:$PORT/anthropic claude -p 'hello'"
echo ""

uv run litellm --port "$PORT" --config "$SCRIPT_DIR/config.yaml"
