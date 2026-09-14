#!/usr/bin/env python3
import sys
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_venv_py = os.path.join(_dir, ".venv", "bin", "python3")

if not os.path.exists(_venv_py):
    sys.exit("Error: .venv not found. Run ./setup-venv.sh to install dependencies.")

if os.path.realpath(sys.prefix) != os.path.realpath(os.path.join(_dir, ".venv")):
    os.execv(_venv_py, [_venv_py] + sys.argv)

import argparse
import json
import re
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

from duration import is_valid_duration_label, duration_minutes

load_dotenv(os.path.join(_dir, ".env"))

TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")
if not TODOIST_TOKEN:
    sys.exit("Error: TODOIST_TOKEN not set in .env")

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or None
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

PROMPT_FILE = os.path.join(_dir, "prompts", "chores.txt")


def _gemini_text(contents: str) -> str | None:
    if not GOOGLE_API_KEY:
        return None
    from google import genai
    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
    return response.text.strip()


def eligible_tasks(api: TodoistAPI) -> list[dict]:
    tasks = [t for page in api.get_tasks() for t in page]
    result = []
    for t in tasks:
        time_labels = [l for l in t.labels if is_valid_duration_label(l)]
        if not time_labels:
            continue
        result.append({
            "id": t.id,
            "content": t.content,
            "minutes": duration_minutes(time_labels[0]),
            "due": t.due.date.isoformat() if t.due else None,
        })
    return result


def build_prompt(budget_minutes: int, tasks: list[dict]) -> str:
    with open(PROMPT_FILE, encoding="utf-8") as f:
        template = f.read()
    lines = []
    for t in tasks:
        due = f", fällig: {t['due']}" if t["due"] else ""
        lines.append(f"- {t['id']} | {t['content']} ({t['minutes']}min{due})")
    return (
        template
        .replace("__BUDGET_MINUTES__", str(budget_minutes))
        .replace("__TASK_LIST__", "\n".join(lines))
    )


def suggest(budget_minutes: int, tasks: list[dict]) -> tuple[list[dict], str]:
    if not GOOGLE_API_KEY:
        sys.exit("Error: GOOGLE_API_KEY not set in .env")
    try:
        raw = _gemini_text(build_prompt(budget_minutes, tasks))
    except Exception as e:
        sys.exit(f"Error: Gemini-Anfrage fehlgeschlagen: {e}")
    if not raw:
        sys.exit("Error: leere Antwort von Gemini")

    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"Error: Gemini-Antwort war kein gültiges JSON ({e}): {raw}")

    by_id = {t["id"]: t for t in tasks}
    selected = [
        {**by_id[entry["id"]], "group": entry.get("group")}
        for entry in data.get("selected", [])
        if entry.get("id") in by_id
    ]

    # Safety net: don't blindly trust the model's arithmetic on the budget
    # constraint — trim lowest-priority (last) picks until back under budget.
    while selected and sum(t["minutes"] for t in selected) > budget_minutes:
        selected.pop()

    return selected, (data.get("note") or "").strip()


def format_message(budget_minutes: int, selected: list[dict], note: str) -> str:
    if not selected:
        return (
            f"🧹 Für {budget_minutes} Minuten hab ich nichts Passendes gefunden "
            "— entweder ist alles erledigt oder nichts hat ein Zeitlabel."
        )
    total = sum(t["minutes"] for t in selected)
    lines = "\n".join(f"• {t['content']} ({t['minutes']}min)" for t in selected)
    header = f"🧹 Vorschlag für {budget_minutes} Minuten (genutzt: {total}min):\n{lines}"
    return f"{header}\n\n💡 {note}" if note else header


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Schlägt Todos vor, die in ein Zeitfenster passen (mit Synergien)."
    )
    parser.add_argument("--budget", required=True, help="Zeitfenster, z.B. 90m, 1h, 1h30m")
    args = parser.parse_args()

    if not is_valid_duration_label(args.budget):
        sys.exit(f"Error: '{args.budget}' ist kein gültiges Zeitformat (z.B. 90m, 1h, 1h30m)")
    budget_minutes = duration_minutes(args.budget)

    api = TodoistAPI(TODOIST_TOKEN)
    try:
        tasks = eligible_tasks(api)
    except Exception as e:
        sys.exit(f"Error: Tasks konnten nicht geladen werden: {e}")

    if not tasks:
        print("🧹 Keine Tasks mit Zeitlabel gefunden.")
        return

    selected, note = suggest(budget_minutes, tasks)
    print(format_message(budget_minutes, selected, note))


if __name__ == "__main__":
    main()
