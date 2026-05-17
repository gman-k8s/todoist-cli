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
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

load_dotenv(os.path.join(_dir, ".env"))

TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")
if not TODOIST_TOKEN:
    sys.exit("Error: TODOIST_TOKEN not set in .env")

TODOIST_PROJECT_ID = os.environ.get("TODOIST_PROJECT_ID") or None
TODOIST_DUE_LANG = os.environ.get("TODOIST_DUE_LANG", "de")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or None

_GEMINI_PROMPT = (
    "You are a task assistant. Given a task title, prepend a single fitting emoji that represents the task.\n"
    "Return ONLY the emoji followed by a space and the original title. No explanation, no quotes, nothing else.\n"
    "Task: {title}"
)


def enrich_title(title: str) -> str:
    if not GOOGLE_API_KEY:
        return title
    try:
        import google.generativeai as genai
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(_GEMINI_PROMPT.format(title=title))
        enriched = response.text.strip()
        if enriched:
            return enriched
    except Exception as e:
        print(f"Warning: Gemini unavailable, using original title ({e})", file=sys.stderr)
    return title


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a Todoist task from the CLI.")
    parser.add_argument("--title", required=True, help="Task title / content")
    parser.add_argument("--due", default=None, help="Due date/recurrence in natural language")
    parser.add_argument("--project-id", default=None, help="Todoist project ID (overrides .env)")
    args = parser.parse_args()

    project_id = args.project_id or TODOIST_PROJECT_ID
    title = enrich_title(args.title)

    api = TodoistAPI(TODOIST_TOKEN)

    kwargs: dict = {"content": title}
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
