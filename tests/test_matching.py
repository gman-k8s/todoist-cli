import pytest

from matching import build_gemini_prompt, gemini_match, parse_gemini_response, regex_match


def d(name, id=None, brand=None, price=1.0, store="lidl"):
    return {"id": id or name.lower().replace(" ", "-"), "store": store, "brand": brand,
            "product_name": name, "price": price, "original_price": None, "discount_pct": None,
            "valid_from": "2026-11-18", "valid_to": "2026-11-23", "source": "marktguru", "ean": None}


def ids(result):
    return {k: [x["id"] for x in v] for k, v in result.items()}


def test_regex_compound_head():
    deals = [d("Frische Vollmilch 1l", id="vollmilch-id", brand="Milsani"), d("Milchschokolade", brand="Milka")]
    assert ids(regex_match(["milch"], deals))["milch"] == ["vollmilch-id"]


def test_regex_butter_not_buttermilch():
    deals = [d("Buttermilch 500g", id="bm"), d("Deutsche Markenbutter 250g", id="mb"), d("Butter", id="b")]
    assert ids(regex_match(["butter"], deals))["butter"] == ["mb", "b"]


def test_regex_plural():
    deals = [d("Banane", id="ban", brand="Chiquita"), d("Freilandeier 10 Stk", id="eier")]
    r = ids(regex_match(["bananen", "eier"], deals))
    assert r["bananen"] == ["ban"]
    assert r["eier"] == ["eier"]


def test_regex_multiword():
    deals = [d("Bio Bananen 1kg", id="bio"), d("Bananen", id="plain")]
    assert ids(regex_match(["bio bananen"], deals))["bio bananen"] == ["bio"]


def test_regex_brand_counts():
    assert ids(regex_match(["jacobs"], [d("Krönung 500g", id="j", brand="Jacobs")]))["jacobs"] == ["j"]


def test_regex_short_words_only_no_match():
    assert regex_match(["ei"], [d("Ei")]) == {"ei": []}


def test_prompt_contains_items_and_deal_lines():
    p = build_gemini_prompt(["milch"], [d("Vollmilch", id="id1", brand="Milsani", price=0.99)])
    assert '"milch"' in p
    assert "id1|lidl|Milsani Vollmilch|0.99" in p
    assert "Milchschokolade" in p


def test_parse_strips_fences_and_drops_unknown():
    deals = [d("Vollmilch", id="id1"), d("Brot", id="id2")]
    raw = '```json\n{"milch":["id1","fake"],"brot":["id2"]}\n```'
    assert ids(parse_gemini_response(raw, ["milch"], deals)) == {"milch": ["id1"]}


def test_parse_keeps_input_order_and_fills_missing_items():
    deals = [d("A", id="a"), d("B", id="b")]
    r = ids(parse_gemini_response('{"x":["b","a"]}', ["x", "y"], deals))
    assert r == {"x": ["a", "b"], "y": []}


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_gemini_response("kein json", ["milch"], [])
    with pytest.raises(ValueError):
        parse_gemini_response("[1,2]", ["milch"], [])


def test_gemini_match_none_raises():
    with pytest.raises(ValueError):
        gemini_match(["milch"], [d("Milch")], lambda prompt: None)


def test_gemini_match_exception_becomes_value_error():
    def boom(prompt):
        raise RuntimeError("quota")
    with pytest.raises(ValueError):
        gemini_match(["milch"], [d("Milch")], boom)


def test_gemini_match_uses_call():
    seen = []
    r = gemini_match(["milch"], [d("Milch", id="m")], lambda p: seen.append(p) or '{"milch":["m"]}')
    assert ids(r) == {"milch": ["m"]} and len(seen) == 1
