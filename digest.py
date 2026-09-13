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
from datetime import datetime, timezone
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

load_dotenv(os.path.join(_dir, ".env"))

TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")
if not TODOIST_TOKEN:
    sys.exit("Error: TODOIST_TOKEN not set in .env")

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or None
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

_COMMENT_PROMPT = (
    "Du kommentierst die heutige Erledigt-Liste einer Todoist-Liste auf Deutsch.\n"
    "Schreib einen kurzen (ein Satz), sarkastischen, liebevoll-fiesen (\"sassy\") Kommentar dazu.\n"
    "Nimm wenn sinnvoll konkret Bezug auf die Aufgaben.\n"
    "Keine Emojis, keine Anführungszeichen, keine Erklärung, nur der Kommentar.\n"
    "\n"
    "Erledigte Aufgaben heute:\n{tasks}\n"
)

_COMMENT_PROMPT_EMPTY = (
    "Der Nutzer hat heute noch kein einziges Todo aus seiner Todoist-Liste erledigt.\n"
    "Schreib einen kurzen (ein Satz), sarkastischen, liebevoll-fiesen (\"sassy\") Kommentar auf Deutsch dazu.\n"
    "Keine Emojis, keine Anführungszeichen, keine Erklärung, nur der Kommentar."
)


def _gemini_text(contents: str) -> str | None:
    if not GOOGLE_API_KEY:
        return None
    from google import genai
    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
    return response.text.strip()


def get_comment(task_titles: list[str]) -> str | None:
    try:
        if task_titles:
            prompt = _COMMENT_PROMPT.format(tasks="\n".join(f"- {t}" for t in task_titles))
        else:
            prompt = _COMMENT_PROMPT_EMPTY
        return _gemini_text(prompt)
    except Exception as e:
        print(f"Warning: Gemini commentary unavailable ({e})", file=sys.stderr)
        return None


def completed_today(api: TodoistAPI, day: datetime) -> list[str]:
    local_midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
    since_utc = local_midnight.astimezone(timezone.utc)
    until_utc = local_end.astimezone(timezone.utc)

    titles = []
    try:
        for page in api.get_completed_tasks_by_completion_date(
            since=since_utc, until=until_utc, limit=200
        ):
            titles.extend(t.content for t in page)
    except Exception as e:
        sys.exit(f"Error: failed to fetch completed tasks: {e}")
    return titles


def build_message(task_titles: list[str]) -> str:
    count = len(task_titles)
    if count == 0:
        header = "📋 Heute wurde noch nichts erledigt."
    else:
        lines = "\n".join(f"• {t}" for t in task_titles)
        noun = "Todo" if count == 1 else "Todos"
        header = f"📋 Heute wurden {count} {noun} erledigt:\n{lines}"

    comment = get_comment(task_titles)
    return f"{header}\n\n{comment}" if comment else header


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Todoist completion digest.")
    parser.add_argument(
        "--date",
        default=None,
        help="Day to report on, YYYY-MM-DD (default: today, local time)",
    )
    args = parser.parse_args()

    if args.date:
        try:
            day = datetime.strptime(args.date, "%Y-%m-%d").astimezone()
        except ValueError:
            sys.exit(f"Error: --date must be YYYY-MM-DD, got '{args.date}'")
    else:
        day = datetime.now().astimezone()

    api = TodoistAPI(TODOIST_TOKEN)
    task_titles = completed_today(api, day)
    print(build_message(task_titles))


if __name__ == "__main__":
    main()
