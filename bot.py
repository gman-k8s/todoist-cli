#!/usr/bin/env python3
import sys
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_venv_py = os.path.join(_dir, ".venv", "bin", "python3")

if not os.path.exists(_venv_py):
    sys.exit("Error: .venv not found. Run ./setup-venv.sh to install dependencies.")

if os.path.realpath(sys.executable) != os.path.realpath(_venv_py):
    os.execv(_venv_py, [_venv_py] + sys.argv)

import argparse
import logging
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

load_dotenv(os.path.join(_dir, ".env"))

TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")
if not TODOIST_TOKEN:
    sys.exit("Error: TODOIST_TOKEN not set in .env")

TODOIST_PROJECT_ID = os.environ.get("TODOIST_PROJECT_ID") or None
TODOIST_DUE_LANG = os.environ.get("TODOIST_DUE_LANG", "de")

logging.basicConfig(format="%(levelname)s %(message)s", level=logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a Todoist task from the CLI.")
    parser.add_argument("--title", required=True, help="Task title / content")
    parser.add_argument("--due", default=None, help="Due date/recurrence in natural language (e.g. 'tomorrow', 'every monday at 9am')")
    parser.add_argument("--project-id", default=None, help="Todoist project ID (overrides .env)")
    args = parser.parse_args()

    project_id = args.project_id or TODOIST_PROJECT_ID

    api = TodoistAPI(TODOIST_TOKEN)

    kwargs: dict = {"content": args.title}
    if project_id:
        kwargs["project_id"] = project_id
    if args.due:
        kwargs["due_string"] = args.due
        kwargs["due_lang"] = TODOIST_DUE_LANG

    try:
        task = api.add_task(**kwargs)
    except Exception as e:
        sys.exit(f"Error: failed to create task: {e}")

    msg = f"Created: {task.content}"
    if task.due:
        msg += f" (due: {task.due.string})"
    print(msg)


if __name__ == "__main__":
    main()
