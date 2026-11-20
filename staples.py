"""Learn staple shopping items from the completion history of the shopping project."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from shopping import normalize

_MAX_WINDOW = timedelta(days=89)  # completed-tasks endpoint accepts up to ~3 months per request


def _empty() -> dict:
    return {"last_sync": None, "items": {}}


def load_history(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            return _empty()
        data.setdefault("last_sync", None)
        return data
    except (OSError, ValueError):
        return _empty()


def save_history(path: Path, history: dict) -> None:
    Path(path).write_text(json.dumps(history, ensure_ascii=False, indent=1), "utf-8")


def fetch_completed(api, project_id: str, since: datetime, until: datetime) -> list:
    tasks = []
    start = since
    while start < until:
        end = min(start + _MAX_WINDOW, until)
        for page in api.get_completed_tasks_by_completion_date(since=start, until=end, limit=200):
            tasks.extend(t for t in page if t.project_id == project_id)
        start = end
    return tasks


def sync_history(history: dict, tasks: list, now: datetime) -> dict:
    items = history["items"]
    for t in tasks:
        key = normalize(t.content)
        if not key:
            continue
        entry = items.setdefault(key, {"display": t.content, "completed": [], "ids": []})
        if t.id in entry["ids"]:
            continue
        entry["display"] = t.content
        entry["ids"].append(t.id)
        entry["completed"].append(t.completed_at.date().isoformat())
    history["last_sync"] = now.isoformat()
    return history


def sync_since(history: dict, now: datetime, window_days: int) -> datetime:
    if history.get("last_sync"):
        return datetime.fromisoformat(history["last_sync"])
    return now - timedelta(days=window_days)


def compute_staples(history: dict, open_normalized: set[str], min_count: int, window_days: int,
                    today: date) -> list[str]:
    cutoff = (today - timedelta(days=window_days)).isoformat()
    scored = []
    for key, entry in history["items"].items():
        if key in open_normalized:
            continue
        count = sum(1 for d in entry["completed"] if d >= cutoff)
        if count >= min_count:
            scored.append((-count, entry["display"]))
    return [display for _, display in sorted(scored, key=lambda x: (x[0], normalize(x[1])))]
