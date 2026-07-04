#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find uv — may not be in PATH when called from HA shell_command
UV=""
for _p in /root/.local/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv"; do
    if [ -x "$_p" ]; then UV="$_p"; break; fi
done
if [ -z "$UV" ] && command -v uv &>/dev/null; then UV="uv"; fi
if [ -z "$UV" ]; then
    echo "Error: uv not found. Install from https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

# Recreate venv if Python binary is broken (happens after HA core update)
if [ -d .venv ] && ! .venv/bin/python3 --version &>/dev/null 2>&1; then
    echo "venv broken (Python version mismatch after update), recreating..."
    rm -rf .venv
fi

if [ ! -d .venv ]; then
    "$UV" venv .venv
fi

"$UV" pip install --python .venv/bin/python3 \
    "todoist-api-python>=2.1" \
    "python-dotenv>=1.0" \
    "google-genai>=1.0"

chmod +x bot.py

echo "Done. .venv ready at $SCRIPT_DIR/.venv"
