#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
"$DIR/.venv/bin/python3" - <<'EOF'
import os
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
token = os.environ.get("TODOIST_TOKEN")
if not token:
    raise SystemExit("Error: TODOIST_TOKEN not set in .env")

api = TodoistAPI(token)
for page in api.get_projects():
    for p in page:
        print(f"{p.id}\t{p.name}")
EOF
