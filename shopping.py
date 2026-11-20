"""Shared helpers for the Todoist shopping list (Einkaufsliste)."""
import re

_SHOPPING_PROJECT_NAME = "einkaufsliste"


def strip_emoji(title: str) -> str:
    """Drop leading emoji, variation selectors, ZWJ and whitespace."""
    i = 0
    while i < len(title) and not title[i].isalnum():
        i += 1
    return title[i:].strip()


def normalize(title: str) -> str:
    return re.sub(r"\s+", " ", strip_emoji(title).lower()).strip()


def find_shopping_project_id(api, override: str | None) -> str:
    if override:
        return override
    for page in api.get_projects():
        for p in page:
            if p.name.lower() == _SHOPPING_PROJECT_NAME:
                return p.id
    raise LookupError("project 'Einkaufsliste' not found")


def open_items(api, project_id: str) -> list[str]:
    items = []
    for page in api.get_tasks(project_id=project_id, limit=200):
        for t in page:
            if normalize(t.content):
                items.append(t.content)
    return items
