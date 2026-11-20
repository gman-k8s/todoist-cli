"""Render matched deals as a German, Telegram-sized message."""
from datetime import date

from shopping import normalize, strip_emoji

MAX_LEN = 4000
MAX_DEALS_PER_ITEM = 3
_FALLBACK_NOTE = "(Abgleich ohne KI – Gemini nicht verfügbar)"
_NOTHING = "Keine Angebote für deine Einkaufsliste gefunden."


def _price(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + "€"


def _ddmm(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d.%m")


def _deal_line(d: dict) -> str:
    brand, name = d.get("brand"), d["product_name"]
    if brand and not name.lower().startswith(brand.lower()):
        name = f"{brand} {name}"
    disc = ""
    if d.get("original_price") is not None and d.get("discount_pct") is not None:
        disc = f" (statt {_price(d['original_price'])}, -{d['discount_pct']:.0f}%)"
    return f"  {d['store'].upper()}  {name} — {_price(d['price'])}{disc} | {_ddmm(d['valid_from'])}–{_ddmm(d['valid_to'])}"


def _block(title: str, deals: list[dict]) -> str:
    best = sorted(deals, key=lambda d: d["price"])[:MAX_DEALS_PER_ITEM]
    return "\n".join([title] + [_deal_line(d) for d in best])


def _assemble(header: str, open_blocks: list[str], staple_blocks: list[str], footer: list[str]) -> str:
    parts = [header] + open_blocks
    if staple_blocks:
        parts.append("⭐ Stammartikel\n" + staple_blocks[0])
        parts.extend(staple_blocks[1:])
    parts.extend(footer)
    return "\n\n".join(parts)


def format_message(open_items: list[str], staples: list[str], matches: dict[str, list[dict]], today: date,
                   *, ai_fallback: bool = False, header: str | None = None,
                   not_loaded: list[str] | None = None) -> str:
    open_blocks = [_block(t, matches[normalize(t)]) for t in open_items if matches.get(normalize(t))]
    staple_blocks = [_block(t, matches[normalize(t)]) for t in staples if matches.get(normalize(t))]
    pending = set(not_loaded or [])
    missing = [strip_emoji(t) for t in open_items if not matches.get(normalize(t)) and t not in pending]
    tail = ([f"Noch nicht geladen (kommt beim nächsten Lauf): {', '.join(strip_emoji(t) for t in not_loaded)}"]
            if not_loaded else [])
    tail += [_FALLBACK_NOTE] if ai_fallback else []

    if not open_blocks and not staple_blocks:
        return "\n\n".join(([header] if header else []) + [_NOTHING] + tail)

    head = header or f"🛒 Angebote für deine Einkaufsliste ({today:%d.%m.})"
    footer = ([f"Keine Angebote: {', '.join(missing)}"] if missing else []) + tail
    text = _assemble(head, open_blocks, staple_blocks, footer)
    dropped = 0
    while len(text) > MAX_LEN and (open_blocks or staple_blocks):
        (staple_blocks or open_blocks).pop()
        dropped += 1
        text = _assemble(head, open_blocks, staple_blocks, footer + [f"… und {dropped} weitere"])
    return text
