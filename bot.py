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
import json
import re
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

load_dotenv(os.path.join(_dir, ".env"))

TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")
if not TODOIST_TOKEN:
    sys.exit("Error: TODOIST_TOKEN not set in .env")

TODOIST_PROJECT_ID = os.environ.get("TODOIST_PROJECT_ID") or None
TODOIST_DUE_LANG = os.environ.get("TODOIST_DUE_LANG", "de")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or None
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

_GEMINI_PROMPT = (
    "You are a task assistant. Given a task title, prepend a single fitting emoji that represents the task.\n"
    "Return ONLY the emoji followed by a space and the original title. No explanation, no quotes, nothing else.\n"
    "Task: {title}"
)

_PARSE_PROMPT = (
    "You parse a spoken German to-do instruction into a Todoist task.\n"
    "Extract the task content (title) and the due/recurrence phrase separately.\n"
    "The due phrase is natural-language Todoist syntax (e.g. 'alle 6 Wochen', 'morgen', "
    "'jeden Montag', 'am 5.'). If no due/recurrence is present, use null.\n"
    "Remove the due phrase from the title. Keep the title concise and natural.\n"
    'Return ONLY minified JSON: {{"title": "...", "due": "..." or null}}. No markdown, no explanation.\n'
    "Instruction: {text}"
)


def _gemini_text(contents: str) -> str | None:
    if not GOOGLE_API_KEY:
        return None
    from google import genai
    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
    return response.text.strip()


def enrich_title(title: str) -> str:
    try:
        enriched = _gemini_text(_GEMINI_PROMPT.format(title=title))
        if enriched:
            return enriched
    except Exception as e:
        print(f"Warning: Gemini unavailable, using original title ({e})", file=sys.stderr)
    return title


def parse_text(text: str) -> tuple[str, str | None]:
    """Split a freeform instruction into (title, due) via Gemini.

    Falls back to (text, None) if Gemini is unavailable or returns garbage.
    """
    if not GOOGLE_API_KEY:
        sys.exit("Error: --text requires GOOGLE_API_KEY for parsing")
    try:
        raw = _gemini_text(_PARSE_PROMPT.format(text=text))
        if not raw:
            raise ValueError("empty response")
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        title = (data.get("title") or "").strip()
        due = data.get("due")
        if isinstance(due, str):
            due = due.strip() or None
        if not title:
            raise ValueError("no title in parsed result")
        return title, due
    except Exception as e:
        print(f"Warning: parse failed, using raw text as title ({e})", file=sys.stderr)
        return text, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a Todoist task from the CLI.")
    parser.add_argument("--title", help="Task title / content")
    parser.add_argument("--due", default=None, help="Due date/recurrence in natural language")
    parser.add_argument(
        "--text",
        help="Freeform instruction; Gemini extracts title + due (e.g. voice transcript)",
    )
    parser.add_argument("--project-id", default=None, help="Todoist project ID (overrides .env)")
    args = parser.parse_args()

    if not args.title and not args.text:
        parser.error("one of --title or --text is required")
    if args.title and args.text:
        parser.error("--title and --text are mutually exclusive")

    project_id = args.project_id or TODOIST_PROJECT_ID

    if args.text:
        raw_title, parsed_due = parse_text(args.text)
        due = args.due or parsed_due
    else:
        raw_title, due = args.title, args.due

    title = enrich_title(raw_title)

    api = TodoistAPI(TODOIST_TOKEN)

    kwargs: dict = {"content": title}
    if project_id:
        kwargs["project_id"] = project_id
    if due:
        kwargs["due_string"] = due
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
