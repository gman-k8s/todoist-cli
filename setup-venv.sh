#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv &>/dev/null; then
    echo "Error: uv not found. Install from https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

if [ ! -d .venv ]; then
    uv venv .venv
fi
uv pip install --python .venv/bin/python3 \
    "todoist-api-python>=2.1" \
    "python-dotenv>=1.0" \
    "google-genai>=1.0"

chmod +x bot.py

echo ""
echo "Done. .venv ready."
echo "Copy .env.example to .env and fill in TODOIST_TOKEN and GOOGLE_API_KEY."
