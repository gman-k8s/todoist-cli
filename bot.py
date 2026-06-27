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
TODOIST_SHOPPING_PROJECT_ID = os.environ.get("TODOIST_SHOPPING_PROJECT_ID") or None
TODOIST_DUE_LANG = os.environ.get("TODOIST_DUE_LANG", "de")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or None
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

_GEMINI_PROMPT = (
    "You are a task assistant. Given a task title, prepend a single fitting emoji that represents the task.\n"
    "Return ONLY the emoji followed by a space and the original title. No explanation, no quotes, nothing else.\n"
    "Task: {title}"
)

_SHOPPING_PROMPT = (
    "You parse a German shopping list voice/text instruction into individual grocery items.\n"
    "For each item return an emoji and the clean item name (capitalized German noun, singular or plural as natural).\n"
    "Strip filler phrases like 'setze ... auf die Einkaufsliste', 'füge ... hinzu', 'ich brauche', 'wir brauchen', etc.\n"
    "List conjunctions ('und', 'sowie', 'außerdem') are item separators, not part of item names.\n"
    "\n"
    "Examples:\n"
    '  "setze Milch auf die Einkaufsliste" -> [{{"emoji":"🥛","item":"Milch"}}]\n'
    '  "setze Bananen, Milch und Brot auf die Einkaufsliste" -> [{{"emoji":"🍌","item":"Bananen"}},{{"emoji":"🥛","item":"Milch"}},{{"emoji":"🍞","item":"Brot"}}]\n'
    '  "ich brauche Eier und Käse" -> [{{"emoji":"🥚","item":"Eier"}},{{"emoji":"🧀","item":"Käse"}}]\n'
    "\n"
    'Return ONLY minified JSON array: [{{"emoji":"...","item":"..."}}]. No markdown, no explanation.\n'
    "Instruction: {text}"
)

_PARSE_PROMPT = (
    "You parse a spoken German to-do instruction into a Todoist task.\n"
    "Return three things:\n"
    "1. emoji: a single emoji that best represents the task.\n"
    "2. title: the task content, WITHOUT any date/time/recurrence words, concise and natural.\n"
    "3. due: the date/time/recurrence phrase in German natural language, or null if none.\n"
    "\n"
    "The due phrase uses Todoist's natural-language syntax. Recognize ALL time expressions, "
    "including single words anywhere in the sentence:\n"
    "  'heute', 'morgen', 'übermorgen', 'heute Abend', 'morgen früh', 'nächste Woche',\n"
    "  'am Montag', 'jeden Montag', 'jeden Tag', 'alle 6 Wochen', 'am 5.', 'in 3 Tagen',\n"
    "  'um 18 Uhr', 'am Wochenende'.\n"
    "Move the due words out of the title. If no time expression exists, due is null.\n"
    "\n"
    "Examples:\n"
    '  "Ventilator einschalten heute" -> {{"emoji": "🌀", "title": "Ventilator einschalten", "due": "heute"}}\n'
    '  "Toilette in OG2 alle 6 Wochen putzen" -> {{"emoji": "🚽", "title": "Toilette in OG2 putzen", "due": "alle 6 Wochen"}}\n'
    '  "Mama anrufen" -> {{"emoji": "📞", "title": "Mama anrufen", "due": null}}\n'
    "\n"
    'Return ONLY minified JSON: {{"emoji": "...", "title": "...", "due": "..." or null}}. '
    "No markdown, no explanation.\n"
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
    """Parse a freeform instruction into (emoji-prefixed title, due) via Gemini.

    Single Gemini call also assigns the emoji, so no separate enrich step.
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
        emoji = (data.get("emoji") or "").strip()
        due = data.get("due")
        if isinstance(due, str):
            due = due.strip() or None
        if not title:
            raise ValueError("no title in parsed result")
        if emoji and not title.startswith(emoji):
            title = f"{emoji} {title}"
        return title, due
    except Exception as e:
        print(f"Warning: parse failed, using raw text as title ({e})", file=sys.stderr)
        return text, None


def parse_shopping(text: str) -> list[str]:
    """Parse German shopping list text into emoji-prefixed item names."""
    if not GOOGLE_API_KEY:
        sys.exit("Error: --shopping requires GOOGLE_API_KEY")
    try:
        raw = _gemini_text(_SHOPPING_PROMPT.format(text=text))
        if not raw:
            raise ValueError("empty response")
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        entries = json.loads(raw)
        items = []
        for entry in entries:
            item = (entry.get("item") or "").strip()
            emoji = (entry.get("emoji") or "").strip()
            if item:
                items.append(f"{emoji} {item}" if emoji else item)
        if not items:
            raise ValueError("no items parsed")
        return items
    except Exception as e:
        sys.exit(f"Error: shopping parse failed ({e})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a Todoist task from the CLI.")
    parser.add_argument("--title", help="Task title / content")
    parser.add_argument("--due", default=None, help="Due date/recurrence in natural language")
    parser.add_argument(
        "--text",
        help="Freeform instruction; Gemini extracts title + due (e.g. voice transcript)",
    )
    parser.add_argument(
        "--shopping",
        help="German shopping list text; Gemini extracts items, adds each to shopping project",
    )
    parser.add_argument("--project-id", default=None, help="Todoist project ID (overrides .env)")
    args = parser.parse_args()

    modes = [m for m in (args.title, args.text, args.shopping) if m]
    if not modes:
        parser.error("one of --title, --text, or --shopping is required")
    if len(modes) > 1:
        parser.error("--title, --text, and --shopping are mutually exclusive")

    api = TodoistAPI(TODOIST_TOKEN)

    if args.shopping:
        items = parse_shopping(args.shopping)

        shopping_project_id = args.project_id or TODOIST_SHOPPING_PROJECT_ID
        if not shopping_project_id:
            try:
                raw = api.get_projects()
                # 2.x: list[Project]; 3.x+: ([Project,...], cursor) as tuple or list
                project_list = raw[0] if (raw and isinstance(raw[0], list)) else raw
                for p in project_list:
                    if p.name.lower() == "einkaufsliste":
                        shopping_project_id = p.id
                        break
            except Exception as e:
                sys.exit(f"Error: could not fetch projects ({e})")
        if not shopping_project_id:
            sys.exit("Error: project 'Einkaufsliste' not found. Set TODOIST_SHOPPING_PROJECT_ID in .env or create the project.")

        created = []
        for title in items:
            try:
                task = api.add_task(content=title, project_id=shopping_project_id)
                created.append(task.content)
            except Exception as e:
                sys.exit(f"Error: failed to add '{title}': {e}")

        print(f"Einkaufsliste: {', '.join(created)}")
        return

    project_id = args.project_id or TODOIST_PROJECT_ID

    if args.text:
        title, parsed_due = parse_text(args.text)
        due = args.due or parsed_due
    else:
        title = enrich_title(args.title)
        due = args.due

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
