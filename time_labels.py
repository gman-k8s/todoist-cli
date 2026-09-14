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
import re
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI
from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from duration import is_valid_duration_label, duration_minutes as _duration_minutes

load_dotenv(os.path.join(_dir, ".env"))

TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")
if not TODOIST_TOKEN:
    sys.exit("Error: TODOIST_TOKEN not set in .env")

_NEW_LABEL = "__new__"
_SKIP = "__skip__"


def _process_task(api: TodoistAPI, task, known_time_labels: list[str], idx: int, total: int, dry_run: bool) -> list[str]:
    current_time_labels = [l for l in task.labels if is_valid_duration_label(l)]
    other_labels = [l for l in task.labels if not is_valid_duration_label(l)]

    print(f"\n[{idx}/{total}] {task.content}")
    if len(current_time_labels) > 1:
        print(f"  ⚠ Mehrere Zeitlabels gefunden ({', '.join(current_time_labels)}) — bitte eines auswählen.")
        default = None
    elif current_time_labels:
        print(f"  Aktuelles Zeitlabel: {current_time_labels[0]}")
        default = current_time_labels[0]
    else:
        print("  Aktuelles Zeitlabel: (keins)")
        default = None

    choices = [
        Choice(value=_SKIP, name="⏭  Überspringen (nichts ändern)"),
        Choice(value=_NEW_LABEL, name="✏️  Neues Zeitlabel eingeben…"),
        *known_time_labels,
    ]

    selection = inquirer.fuzzy(
        message="Zeitlabel wählen (tippen zum Filtern):",
        choices=choices,
        default=default,
    ).execute()

    if selection == _SKIP:
        print("  → übersprungen")
        return known_time_labels

    if selection == _NEW_LABEL:
        while True:
            new_label = inquirer.text(message="Neues Zeitlabel (z.B. 30m, 2h, 2h30m, 1d):").execute().strip()
            if is_valid_duration_label(new_label):
                break
            print(f"  ✗ '{new_label}' ist kein gültiges Zeitlabel-Format (Zahl + m/h/d, z.B. 2h30m).")
        selection = new_label
        if selection not in known_time_labels:
            if not dry_run:
                try:
                    api.add_label(name=selection)
                except Exception as e:
                    print(f"  ✗ Label '{selection}' konnte nicht angelegt werden: {e}", file=sys.stderr)
            known_time_labels = sorted(known_time_labels + [selection], key=_duration_minutes)

    if len(current_time_labels) == 1 and selection == current_time_labels[0]:
        print(f"  → unverändert ({selection})")
        return known_time_labels

    new_labels = other_labels + [selection]
    if dry_run:
        print(f"  [dry-run] würde Labels setzen: {new_labels}")
    else:
        try:
            api.update_task(task_id=task.id, labels=new_labels)
            print(f"  ✓ Zeitlabel gesetzt: {selection}")
        except Exception as e:
            print(f"  ✗ Update fehlgeschlagen: {e}", file=sys.stderr)

    return known_time_labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Zeitlabels interaktiv an offene Todoist-Tasks vergeben.")
    parser.add_argument("--filter", "-f", default=None, help="Regex; nur Tasks deren Titel matcht")
    parser.add_argument("--dry-run", action="store_true", help="Nichts schreiben, nur anzeigen")
    args = parser.parse_args()

    api = TodoistAPI(TODOIST_TOKEN)

    try:
        all_labels = [l.name for page in api.get_labels() for l in page]
    except Exception as e:
        sys.exit(f"Error: Labels konnten nicht geladen werden: {e}")

    time_labels = sorted(
        (l for l in all_labels if is_valid_duration_label(l)), key=_duration_minutes
    )

    try:
        tasks = [t for page in api.get_tasks() for t in page]
    except Exception as e:
        sys.exit(f"Error: Tasks konnten nicht geladen werden: {e}")

    if args.filter:
        try:
            pattern = re.compile(args.filter)
        except re.error as e:
            sys.exit(f"Error: ungültiges --filter Regex: {e}")
        tasks = [t for t in tasks if pattern.search(t.content)]

    tasks.sort(key=lambda t: t.content.casefold())

    if not tasks:
        print("Keine passenden Tasks gefunden.")
        return

    total = len(tasks)
    for idx, task in enumerate(tasks, start=1):
        time_labels = _process_task(api, task, time_labels, idx, total, args.dry_run)


if __name__ == "__main__":
    main()
