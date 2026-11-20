#!/usr/bin/env python3
"""Match the Todoist shopping list (plus learned staples) against supermarket deals."""
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
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

from matching import gemini_match, regex_match
from render import format_message
from shopping import find_shopping_project_id, normalize, open_items
from staples import compute_staples, fetch_completed, load_history, save_history, sync_history, sync_since

load_dotenv(os.path.join(_dir, ".env"))

HISTORY_FILE = Path(_dir) / ".shopping_history.json"
SCRAPER_TIMEOUT = 300


def _gemini_text(prompt: str) -> str | None:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    from google import genai
    client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")
    return client.models.generate_content(model=model, contents=prompt).text


def run_scraper(scraper_dir: Path, terms: list[str], force: bool, timeout: int = SCRAPER_TIMEOUT) -> dict:
    cmd = [str(scraper_dir / ".venv/bin/python"), str(scraper_dir / "scraper.py"),
           "--json", "--terms", ",".join(terms)] + (["--force"] if force else [])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"scraper failed: {e}") from e
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"scraper exited with {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"scraper returned invalid JSON: {e}") from e


def collect_deals(scraper_json: dict) -> list[dict]:
    seen: dict[str, dict] = {}
    for term in scraper_json.get("terms", {}).values():
        for d in term.get("deals", []):
            seen.setdefault(d["id"], d)
    return list(seen.values())


def search_terms(open_titles: list[str], staple_titles: list[str]) -> list[str]:
    terms = [" ".join(normalize(t).replace(",", " ").split()) for t in open_titles + staple_titles]
    return list(dict.fromkeys(t for t in terms if t))


def _fail(msg: str) -> int:
    print(f"Fehler: {msg}", file=sys.stderr)
    return 1


def _learn_staples(api, project_id: str, open_titles: list[str], dry_run: bool) -> list[str]:
    min_count = int(os.environ.get("SHOPPING_STAPLE_MIN_COUNT") or 3)
    window = int(os.environ.get("SHOPPING_STAPLE_WINDOW_DAYS") or 90)
    now = datetime.now(timezone.utc)
    history = load_history(HISTORY_FILE)
    try:
        tasks = fetch_completed(api, project_id, sync_since(history, now, window), now)
        history = sync_history(history, tasks, now)
        if not dry_run:
            save_history(HISTORY_FILE, history)
    except Exception as e:
        print(f"Warnung: Erledigt-Historie nicht abrufbar ({e})", file=sys.stderr)
    return compute_staples(history, {normalize(t) for t in open_titles}, min_count, window, date.today())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Einkaufsliste mit Supermarkt-Angeboten abgleichen.")
    parser.add_argument("--force", action="store_true", help="Angebote frisch online laden")
    parser.add_argument("--matcher", choices=["gemini", "regex", "compare"], default="gemini")
    parser.add_argument("--dry-run", action="store_true", help="Lern-Historie nicht speichern")
    args = parser.parse_args(argv)

    token = os.environ.get("TODOIST_TOKEN")
    if not token:
        return _fail("TODOIST_TOKEN nicht gesetzt (.env).")
    scraper_dir = os.environ.get("SUPERMARKET_SCRAPER_DIR")
    if not scraper_dir:
        return _fail("SUPERMARKET_SCRAPER_DIR nicht gesetzt (.env).")

    api = TodoistAPI(token)
    try:
        project_id = find_shopping_project_id(api, os.environ.get("TODOIST_SHOPPING_PROJECT_ID") or None)
        open_titles = open_items(api, project_id)
    except LookupError:
        return _fail("Projekt 'Einkaufsliste' nicht gefunden.")
    except Exception as e:
        return _fail(f"Todoist nicht erreichbar ({e}).")

    staples = _learn_staples(api, project_id, open_titles, args.dry_run)
    terms = search_terms(open_titles, staples)
    today = date.today()
    if not terms:
        print(format_message([], [], {}, today))
        return 0

    try:
        deals = collect_deals(run_scraper(Path(scraper_dir), terms, force=args.force))
    except RuntimeError as e:
        print(f"Warnung: {e}", file=sys.stderr)
        return _fail("Angebote konnten nicht geladen werden.")

    items = list(dict.fromkeys(normalize(t) for t in open_titles + staples))

    def _gemini():
        try:
            return gemini_match(items, deals, _gemini_text), None
        except ValueError as e:
            print(f"Warnung: Gemini-Abgleich fehlgeschlagen ({e})", file=sys.stderr)
            return regex_match(items, deals), e

    if args.matcher == "compare":
        g, err = _gemini()
        print(format_message(open_titles, staples, g, today, ai_fallback=err is not None,
                             header="🛒 Abgleich: Gemini"))
        print()
        print(format_message(open_titles, staples, regex_match(items, deals), today, header="🛒 Abgleich: Regex"))
        return 0

    if args.matcher == "regex":
        print(format_message(open_titles, staples, regex_match(items, deals), today))
        return 0

    matches, err = _gemini()
    print(format_message(open_titles, staples, matches, today, ai_fallback=err is not None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
