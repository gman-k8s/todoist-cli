from types import SimpleNamespace

import pytest

from shopping import find_shopping_project_id, normalize, open_items, strip_emoji


class FakeApi:
    def __init__(self, projects=None, tasks=None):
        self.projects = projects or []
        self.tasks = tasks or []
        self.task_calls = []

    def get_projects(self):
        yield self.projects

    def get_tasks(self, project_id=None, limit=None):
        self.task_calls.append(project_id)
        yield self.tasks


def P(name, id="1"):
    return SimpleNamespace(name=name, id=id)


def T(content):
    return SimpleNamespace(content=content)


def test_strip_emoji():
    assert strip_emoji("🥛 Milch") == "Milch"
    assert strip_emoji("👨‍👩‍👧 Familienpackung") == "Familienpackung"
    assert strip_emoji("☕️Kaffee") == "Kaffee"
    assert strip_emoji("Äpfel") == "Äpfel"


def test_normalize():
    assert normalize("  🍌  Bio  Bananen ") == "bio bananen"


def test_find_project_override():
    assert find_shopping_project_id(FakeApi(), "123") == "123"


def test_find_project_by_name():
    api = FakeApi(projects=[P("Inbox", "1"), P("EinkaufsListe", "9")])
    assert find_shopping_project_id(api, None) == "9"


def test_find_project_missing_raises():
    with pytest.raises(LookupError):
        find_shopping_project_id(FakeApi(projects=[P("Inbox")]), None)


def test_open_items_skips_emoji_only():
    api = FakeApi(tasks=[T("🥛 Milch"), T("🛒"), T("")])
    assert open_items(api, "9") == ["🥛 Milch"]
    assert api.task_calls == ["9"]
