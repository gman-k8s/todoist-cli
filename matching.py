"""Match shopping items against deals: rule-based (regex) or via Gemini."""
import json
import re
from typing import Callable

_TOKEN = re.compile(r"[a-zäöüß0-9]+")
_SUFFIXES = ("en", "n", "e", "s")


def _stem(word: str) -> str:
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def _deal_text(deal: dict) -> str:
    return f"{deal.get('brand') or ''} {deal['product_name']}".strip()


def _matches(item: str, deal: dict) -> bool:
    words = [w for w in _TOKEN.findall(item.lower()) if len(w) >= 3]
    if not words:
        return False
    tokens = [_stem(t) for t in _TOKEN.findall(_deal_text(deal).lower())]
    # German compounds carry the head noun at the end: Vollmilch is milk, Milchschokolade is not.
    return all(any(tok.endswith(_stem(w)) for tok in tokens) for w in words)


def regex_match(items: list[str], deals: list[dict]) -> dict[str, list[dict]]:
    return {item: [d for d in deals if _matches(item, d)] for item in items}


def build_gemini_prompt(items: list[str], deals: list[dict]) -> str:
    lines = "\n".join(f"{d['id']}|{d['store']}|{_deal_text(d)}|{d['price']}" for d in deals)
    return (
        "Du gleichst eine deutsche Einkaufsliste mit Supermarkt-Angeboten ab.\n"
        "Ordne jedem Artikel nur Angebote zu, die tatsächlich dieses Produkt sind "
        "(z. B. Milch ≠ Milchschokolade, Butter ≠ Buttermilch, Eier ≠ Eierlikör). "
        "Marken- und Sortenvarianten des Produkts zählen (z. B. Vollmilch für Milch).\n"
        "Artikel ohne passendes Angebot bekommen eine leere Liste.\n"
        'Antworte NUR mit minifiziertem JSON: {"<artikel>": ["<id>", ...]} — '
        "Artikelnamen exakt wie unten, keine Erklärung, kein Markdown.\n\n"
        f"Artikel: {json.dumps(items, ensure_ascii=False)}\n\n"
        "Angebote (id|markt|produkt|preis):\n"
        f"{lines}\n"
    )


def parse_gemini_response(raw: str, items: list[str], deals: list[dict]) -> dict[str, list[dict]]:
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON from Gemini: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Gemini response is not a JSON object")
    result = {}
    for item in items:
        wanted = data.get(item) or []
        wanted = {x for x in wanted if isinstance(x, str)} if isinstance(wanted, list) else set()
        result[item] = [d for d in deals if d["id"] in wanted]
    return result


def gemini_match(items: list[str], deals: list[dict], call: Callable[[str], str | None]) -> dict[str, list[dict]]:
    try:
        raw = call(build_gemini_prompt(items, deals))
    except Exception as e:
        raise ValueError(f"Gemini call failed: {e}") from e
    if not raw:
        raise ValueError("empty Gemini response")
    return parse_gemini_response(raw, items, deals)
