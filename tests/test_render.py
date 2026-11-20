from datetime import date

from render import format_message

TODAY = date(2026, 11, 20)


def d(store, brand, name, price, vf, vt, orig=None, id=None):
    disc = (1 - price / orig) * 100 if orig else None
    return {"id": id or f"{store}-{name}", "store": store, "brand": brand, "product_name": name, "price": price,
            "original_price": orig, "discount_pct": disc, "valid_from": vf, "valid_to": vt,
            "source": "marktguru", "ean": None}


SPEC_MATCHES = {
    "milch": [
        d("lidl", "Milsani", "Frische Vollmilch 1l", 0.99, "2026-11-18", "2026-11-23", orig=1.29),
        d("aldi", "Milsani", "H-Milch 1l", 0.89, "2026-11-20", "2026-11-22"),
    ],
    "brot": [], "eier": [],
    "kaffee": [d("netto", "Jacobs", "Krönung 500g", 4.99, "2026-11-20", "2026-11-25", orig=7.49)],
}


def test_format_matches_spec_example():
    out = format_message(["🥛 Milch", "Brot", "🥚 Eier"], ["☕ Kaffee"], SPEC_MATCHES, TODAY)
    assert out == (
        "🛒 Angebote für deine Einkaufsliste (20.11.)\n"
        "\n"
        "🥛 Milch\n"
        "  ALDI  Milsani H-Milch 1l — 0,89€ | 20.11–22.11\n"
        "  LIDL  Milsani Frische Vollmilch 1l — 0,99€ (statt 1,29€, -23%) | 18.11–23.11\n"
        "\n"
        "⭐ Stammartikel\n"
        "☕ Kaffee\n"
        "  NETTO  Jacobs Krönung 500g — 4,99€ (statt 7,49€, -33%) | 20.11–25.11\n"
        "\n"
        "Keine Angebote: Brot, Eier"
    )


def test_brand_not_duplicated():
    m = {"kaffee": [d("lidl", "Melitta", "Melitta Auslese", 5.99, "2026-11-18", "2026-11-21")]}
    assert "  LIDL  Melitta Auslese — 5,99€" in format_message(["Kaffee"], [], m, TODAY)


def test_max_three_sorted_by_price():
    m = {"milch": [d("lidl", None, f"M{p}", p, "2026-11-18", "2026-11-23") for p in (3.0, 1.0, 4.0, 2.0)]}
    lines = [l for l in format_message(["Milch"], [], m, TODAY).splitlines() if l.startswith("  ")]
    assert [l.split("  ")[2].split(" ")[0] for l in lines] == ["M1.0", "M2.0", "M3.0"]


def test_nothing_found():
    assert format_message(["Brot"], ["Kaffee"], {"brot": [], "kaffee": []}, TODAY) == \
        "Keine Angebote für deine Einkaufsliste gefunden."


def test_staple_without_deals_not_listed():
    m = {"milch": SPEC_MATCHES["milch"], "kaffee": []}
    out = format_message(["Milch"], ["Kaffee"], m, TODAY)
    assert "Stammartikel" not in out and "Kaffee" not in out


def test_ai_fallback_line():
    out = format_message(["🥛 Milch"], [], {"milch": SPEC_MATCHES["milch"]}, TODAY, ai_fallback=True)
    assert out.endswith("\n(Abgleich ohne KI – Gemini nicht verfügbar)")
    out = format_message(["Brot"], [], {"brot": []}, TODAY, ai_fallback=True)
    assert out.endswith("(Abgleich ohne KI – Gemini nicht verfügbar)")


def test_header_override():
    out = format_message(["🥛 Milch"], [], {"milch": SPEC_MATCHES["milch"]}, TODAY, header="🛒 Abgleich: Regex")
    assert out.startswith("🛒 Abgleich: Regex\n\n🥛 Milch")


def test_truncation():
    items = [f"Artikel Nummer {i}" for i in range(60)]
    m = {f"artikel nummer {i}": [d("lidl", "Marke", f"Ein ziemlich langer Produktname {j}", 1.0 + j,
                                    "2026-11-18", "2026-11-23", orig=9.99) for j in range(3)] for i in range(60)}
    out = format_message(items, [], m, TODAY)
    assert len(out) <= 4000
    shown = sum(1 for i in items if f"\n{i}\n" in out)
    assert out.endswith(f"… und {60 - shown} weitere")
    assert 0 < shown < 60
