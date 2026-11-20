from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from staples import compute_staples, fetch_completed, load_history, save_history, sync_history, sync_since

NOW = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)


def T(id, content, days_ago, project_id="9"):
    return SimpleNamespace(id=id, content=content, project_id=project_id,
                           completed_at=NOW - timedelta(days=days_ago))


def test_load_missing_and_corrupt(tmp_path):
    assert load_history(tmp_path / "nope.json") == {"last_sync": None, "items": {}}
    bad = tmp_path / "bad.json"
    bad.write_text("{kaputt", "utf-8")
    assert load_history(bad) == {"last_sync": None, "items": {}}


def test_save_load_roundtrip(tmp_path):
    h = sync_history(load_history(tmp_path / "h.json"), [T("1", "🥛 Milch", 1)], NOW)
    save_history(tmp_path / "h.json", h)
    assert load_history(tmp_path / "h.json") == h


def test_sync_dedupes_by_task_id():
    h = {"last_sync": None, "items": {}}
    h = sync_history(h, [T("1", "Milch", 2)], NOW)
    h = sync_history(h, [T("1", "Milch", 2)], NOW)
    assert h["items"]["milch"]["completed"] == [(NOW - timedelta(days=2)).date().isoformat()]
    assert h["last_sync"] == NOW.isoformat()


def test_sync_merges_emoji_variants():
    h = sync_history({"last_sync": None, "items": {}}, [T("1", "🥛 Milch", 5), T("2", "Milch", 1)], NOW)
    assert list(h["items"]) == ["milch"]
    assert h["items"]["milch"]["display"] == "Milch"
    assert len(h["items"]["milch"]["completed"]) == 2


def test_sync_skips_empty_titles():
    h = sync_history({"last_sync": None, "items": {}}, [T("1", "🛒", 1)], NOW)
    assert h["items"] == {}


def _hist(*entries):
    h = {"last_sync": None, "items": {}}
    return sync_history(h, list(entries), NOW)


def test_staples_threshold():
    today = NOW.date()
    h = _hist(T("1", "☕ Kaffee", 1), T("2", "Kaffee", 30), T("3", "Kaffee", 60),
              T("4", "Brot", 1), T("5", "Brot", 2),
              T("6", "Eier", 1), T("7", "Eier", 2), T("8", "Eier", 100))
    assert compute_staples(h, set(), 3, 90, today) == ["Kaffee"]


def test_staples_sorted_by_frequency_then_alpha():
    h = _hist(*[T(f"a{i}", "Butter", i) for i in range(4)],
              *[T(f"b{i}", "Apfel", i) for i in range(3)],
              *[T(f"c{i}", "Zucker", i) for i in range(3)])
    assert compute_staples(h, set(), 3, 90, NOW.date()) == ["Butter", "Apfel", "Zucker"]


def test_staples_exclude_open():
    h = _hist(T("1", "Kaffee", 1), T("2", "Kaffee", 2), T("3", "Kaffee", 3))
    assert compute_staples(h, {"kaffee"}, 3, 90, NOW.date()) == []


class FakeApi:
    def __init__(self, tasks):
        self.tasks = tasks
        self.windows = []

    def get_completed_tasks_by_completion_date(self, since, until, limit=None):
        self.windows.append((since, until))
        yield [t for t in self.tasks if since <= t.completed_at <= until]


def test_fetch_completed_filters_project_and_windows():
    api = FakeApi([T("1", "Milch", 10), T("2", "Arbeit", 10, project_id="1"), T("3", "Eier", 150)])
    got = fetch_completed(api, "9", NOW - timedelta(days=200), NOW)
    assert sorted(t.id for t in got) == ["1", "3"]
    assert len(api.windows) == 3
    assert all(u - s <= timedelta(days=89) for s, u in api.windows)
    assert api.windows[0][0] == NOW - timedelta(days=200) and api.windows[-1][1] == NOW


def test_sync_since_first_run():
    assert sync_since({"last_sync": None, "items": {}}, NOW, 90) == NOW - timedelta(days=90)
    assert sync_since({"last_sync": "2026-11-19T08:00:00+00:00", "items": {}}, NOW, 90) == \
        datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)
