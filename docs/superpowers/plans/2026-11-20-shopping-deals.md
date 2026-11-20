# Einkaufsliste × Schnäppchen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offene Todoist-Einkaufspunkte und gelernte Stammartikel gegen Supermarkt-Angebote abgleichen und als Telegram-taugliche Nachricht ausgeben.

**Architecture:** `supermarket-scraper` bekommt einen TSV-Cache pro Suchbegriff, `--terms`, `--all` und `--json`. `todoist-cli` bekommt `shopping_deals.py`, das Todoist liest, Stammartikel lernt, den Scraper per Subprozess mit `--json` aufruft und per Gemini (Fallback: Regex) abgleicht.

**Tech Stack:** Python 3.11+, requests, rapidfuzz (Scraper), todoist-api-python 4.x, google-genai, python-dotenv, pytest.

**Spec:** `/home/agarbe/git/todoist-cli/docs/superpowers/specs/2026-11-20-shopping-deals-design.md`

Zwei Repos: Tasks 1–3 in `/home/agarbe/git/supermarket-scraper` (Pfade relativ dazu), Tasks 4–8 in `/home/agarbe/git/todoist-cli`. Scraper-Tests: `.venv/bin/python -m pytest`; todoist-cli-Tests: `.venv/bin/python3 -m pytest`.

## Global Constraints

- Nutzertexte auf Deutsch; Fehler/Warnungen beginnen mit `Fehler:` bzw. `Warnung:` und gehen auf stderr.
- `scraper.py` ohne neue Flags: Ausgabe unverändert. `--force` = online neu laden **und** alle Treffer ohne Seen-Cache zeigen.
- `[cache] deals_max_age_days` Default `7`, fehlt der Schlüssel → 7.
- Cache-Datei nur schreiben, wenn beide Quellen für den Begriff erfolgreich waren; nie bei `--dry-run`.
- Deals mit `valid_to < heute` werden beim Lesen verworfen.
- `Deal.id`-Ableitung bleibt unverändert.
- Max. 3 Deals pro Artikel (nach Preis), Nachricht ≤ 4000 Zeichen.
- Stammartikel: ≥ `SHOPPING_STAPLE_MIN_COUNT` (3) Erledigungen in `SHOPPING_STAPLE_WINDOW_DAYS` (90) Tagen, nicht offen.
- Genau ein Gemini-Aufruf pro Lauf (bei `compare` ebenfalls einer). Gemini-Fehler → Regex-Fallback, nie Abbruch.
- Nichts nach Todoist zurückschreiben.

## Review Focus

1. Einkaufspunkt ist nur ein Emoji oder leer → wird ignoriert, kein leerer Suchbegriff an den Scraper (Task 4).
2. Artikelname mit Komma („Äpfel, rot“) → darf `--terms` nicht in zwei Begriffe zerreißen; Kommas im Begriff werden durch Leerzeichen ersetzt (Task 8).
3. Gemini antwortet mit ```json-Fences, unbekannten Artikel-Schlüsseln oder erfundenen IDs → Fences entfernen, Unbekanntes verwerfen (Task 6).
4. Kaputte/fremde Cache-Datei (fehlender Header, falsche Spaltenzahl) → als „nicht gecacht“ behandeln und neu laden, kein Crash (Task 1).
5. Erster Lauf ohne `.shopping_history.json` bzw. kaputte JSON-Datei → leere Historie, Backfill 90 Tage (Task 5).

---

### Task 1: TSV-Deal-Cache (`supermarket-scraper`)

**Files:**
- Create: `deal_cache.py`
- Test: `tests/test_deal_cache.py`

**Interfaces:**
- Produces:
  - `slugify(term: str) -> str` — lowercase, alles außer `[a-z0-9äöüß]` → `-`, Mehrfach-`-` zusammengefasst, Rand-`-` entfernt.
  - `@dataclass CachedTerm: term: str; fetched: datetime; sources: list[str]; deals: list[Deal]`
  - `write_term(cache_dir: Path, term: str, deals: list[Deal], sources: list[str], fetched: datetime) -> None`
  - `read_term(cache_dir: Path, term: str, today: date) -> CachedTerm | None` — `None` bei fehlender oder unlesbarer Datei; abgelaufene Deals entfernt.
  - `is_fresh(cached: CachedTerm, now: datetime, max_age_days: int) -> bool`

Dateiformat exakt wie in der Spec (3 Header-Zeilen `# term:`, `# fetched:` ISO ohne Mikrosekunden, `# sources:` kommagetrennt; dann TSV mit 11 Spalten `id store brand product_name price original_price discount_pct valid_from valid_to source ean`). `None` → leerer String; Tab/`\n` in Feldern → Leerzeichen. Beim Lesen wird `Deal(...)` neu konstruiert (die `id`-Spalte ist informativ; `discount_pct` aus Datei übernehmen, wenn gesetzt).

- [ ] **Step 1: Failing tests schreiben**

```python
def test_slugify(): assert slugify("Äpfel, rot!") == "äpfel-rot"
def test_roundtrip(tmp_path):  # Deal mit brand=None, original_price=None und einer mit allen Feldern
    write_term(tmp_path, "milch", deals, ["marktguru", "aktionspreis"], datetime(2026, 11, 20, 8, 0, 12))
    c = read_term(tmp_path, "milch", date(2026, 11, 20))
    assert [d.to_dict() for d in c.deals] == [d.to_dict() for d in deals]
    assert c.fetched == datetime(2026, 11, 20, 8, 0, 12) and c.sources == ["marktguru", "aktionspreis"]
def test_header_only_file_is_valid_empty(tmp_path): ...  # deals == [], nicht None
def test_expired_deals_dropped(tmp_path): ...  # valid_to 2026-11-19, today 2026-11-20 → weg
def test_tab_in_name_sanitized(tmp_path): ...  # "A\tB" → "A B"
def test_missing_file_returns_none(tmp_path): assert read_term(tmp_path, "x", date.today()) is None
def test_corrupt_file_returns_none(tmp_path):  # kein Header / 3 Spalten → None
def test_is_fresh():  # fetched vor 6 Tagen, max 7 → True; vor 8 Tagen → False
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_deal_cache.py -v` → FAIL (ModuleNotFoundError)
- [ ] **Step 3:** `deal_cache.py` gemäß Interfaces implementieren.
- [ ] **Step 4:** Tests → PASS
- [ ] **Step 5:** Commit `feat: add per-term TSV deal cache`

---

### Task 2: Laden pro Suchbegriff mit Cache-Regel (`supermarket-scraper`)

**Files:**
- Create: `deal_loader.py`
- Modify: `scrapers/marktguru.py` (`_get_client_key` Ergebnis auf der Instanz memoizen, `self._client_key`)
- Test: `tests/test_deal_loader.py`, Ergänzung in `tests/test_scrapers.py`

**Interfaces:**
- Consumes: Task 1 (`read_term`, `write_term`, `is_fresh`).
- Produces:
  - `@dataclass TermResult: deals: list[Deal]; fetched: datetime; from_cache: bool`
  - `@dataclass LoadResult: terms: dict[str, TermResult]; warnings: list[str]; online_deals: list[Deal]; all_sources_failed: bool`
  - `load_deals(terms: list[str], scrapers: list[BaseScraper], cache_dir: Path, *, force: bool, max_age_days: int, write_cache: bool, now: datetime) -> LoadResult`

Algorithmus: pro Begriff Lade-Regel aus der Spec. Online: für jede Scraper-Instanz `s.products = [term]; s.fetch()`; Instanzen werden über alle Begriffe wiederverwendet (marktguru holt den Client-Key so nur einmal). `ScraperError` einer Quelle → Warnung `"<Quelle>: <msg>"`, Begriff gilt als Teilausfall (nicht cachen). Keine Quelle erfolgreich und alte Datei vorhanden → alte Deals, `from_cache=True`, Warnung. `all_sources_failed` = mindestens ein Begriff musste online geladen werden und **jede** Quelle ist bei **allen** online geladenen Begriffen gescheitert. Ein Deal, der über zwei Begriffe gefunden wird, steht in beiden `TermResult`s.

- [ ] **Step 1: Failing tests** (Scraper als Fakes mit `products`-Attribut und `fetch()`; `now=datetime(2026,11,20,8)`)

```python
def test_fresh_cache_is_used_without_fetch(tmp_path)        # fetch nicht aufgerufen, from_cache True
def test_stale_cache_triggers_fetch_and_rewrite(tmp_path)   # fetched vor 8 Tagen
def test_missing_term_fetched_and_written(tmp_path)
def test_force_refetches_fresh_cache(tmp_path)
def test_partial_failure_not_written(tmp_path)              # Quelle B wirft → Deals von A, keine Datei, 1 Warnung
def test_total_failure_falls_back_to_old_file(tmp_path)     # beide werfen, alte Datei → from_cache True
def test_all_sources_failed_flag(tmp_path)                  # beide werfen für alle Begriffe → True
def test_write_cache_false_writes_nothing(tmp_path)
def test_online_deals_collected(tmp_path)                   # nur online geladene, nicht gecachte
```
In `tests/test_scrapers.py`: `test_marktguru_client_key_fetched_once` — zwei `fetch()`-Aufrufe mit gemocktem `requests.get`, `/configurations/web` genau einmal angefragt.

- [ ] **Step 2:** Tests → FAIL
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** `.venv/bin/python -m pytest` → alles PASS
- [ ] **Step 5:** Commit `feat: load deals per term with cache freshness rule`

---

### Task 3: CLI-Flags in `scraper.py` (`supermarket-scraper`)

**Files:**
- Modify: `scraper.py`, `config.example/settings.toml` (`deals_max_age_days = 7` unter `[cache]`), `README.md`, `CLAUDE.md`
- Test: `tests/test_scraper.py`

**Interfaces:**
- Consumes: Task 2 `load_deals`.
- Produces (für Task 8): `scraper.py --json --terms "a,b" [--force]` druckt das JSON aus der Spec auf stdout: `{"generated_at", "terms": {term: {"fetched", "from_cache", "deals": [Deal.to_dict()]}}, "warnings"}`, Exit 1 nur bei `all_sources_failed`. Neues Modul-Attribut `_DEALS_DIR = _OUTPUT_DIR / "deals"`.

Verhalten: Suchbegriffe = `products.txt` ∪ `--terms` (split an `,`, strip, lowercase, leere weg, Reihenfolge stabil dedupliziert). `--json`: kein Matching, kein `cache.json`/`results.json`, Preis-DB weiterhin mit `online_deals` (außer `--dry-run`); Warnungen zusätzlich auf stderr. Nicht-JSON-Pfad: Deals aller Begriffe (dedupliziert per id) → bestehendes `match_deals` → Seen-Cache; `display = matched if (args.force or args.all) else truly_new`. Preis-DB bekommt `online_deals` statt `all_deals`.

- [ ] **Step 1: Bestehenden `_run`-Helper anpassen**, damit er `scraper._DEALS_DIR` auf `tmp_path` patcht (sonst lesen/schreiben Tests den echten Cache) — patch nach `importlib.reload`, z. B. über `monkeypatch`/`patch.object` direkt vor `main()`; Tests laufen weiterhin grün.
- [ ] **Step 2: Failing tests**

```python
def test_terms_are_searched(capsys)          # --terms "kaffee" → fetch mit products == ["kaffee"] aufgerufen
def test_json_output_shape(capsys)           # --json → json.loads(out)["terms"]["butter"]["deals"][0]["store"] == "lidl"
def test_json_skips_results_and_seen_cache() # write_results_json und Cache.add_all nicht aufgerufen
def test_all_flag_shows_seen_without_fetch() # frischer Cache-Eintrag + Cache.contains True + --all → LIDL in out, fetch nicht aufgerufen
def test_force_still_shows_seen(capsys)      # bestehender Test bleibt grün
def test_default_output_unchanged(capsys)    # bestehende Tests bleiben grün
def test_missing_max_age_defaults_to_7()     # settings ohne deals_max_age_days → load_deals(max_age_days=7)
def test_dry_run_writes_no_text_cache(tmp_path)  # --dry-run → load_deals(write_cache=False), tmp_path/deals leer
```
- [ ] **Step 3:** Tests → FAIL
- [ ] **Step 4:** Implementieren; `config.example/settings.toml` ergänzen; README-Usage um `--all`, `--terms`, `--json` und den Cache unter `output/deals/` erweitern; CLAUDE.md Pipeline-Abschnitt (Punkt Cache/Output) entsprechend.
- [ ] **Step 5:** `.venv/bin/python -m pytest` → alles PASS
- [ ] **Step 6:** Smoke: `.venv/bin/python scraper.py --json --terms "kaffee" --dry-run | head -c 400` → gültiges JSON (Netz nötig; bei Netzfehler Warnung + Exit 1 ist akzeptabel, im Report vermerken).
- [ ] **Step 7:** Commit `feat: add --terms, --all, --json and text deal cache to scraper`

---

### Task 4: Gemeinsames `shopping.py` + pytest-Setup (`todoist-cli`)

**Files:**
- Create: `shopping.py`, `tests/__init__.py`, `tests/test_shopping.py`, `pytest.ini` (`[pytest]\ntestpaths = tests`)
- Modify: `bot.py` (Projektsuche durch `find_shopping_project_id` ersetzen), `setup-venv.sh` (`pytest` mitinstallieren)

**Interfaces:**
- Produces:
  - `strip_emoji(title: str) -> str` — entfernt führende Nicht-Buchstaben/Ziffern-Zeichen (Emoji, Variation Selectors, ZWJ, Leerzeichen) am Anfang.
  - `normalize(title: str) -> str` — `strip_emoji`, lowercase, Whitespace zusammengefasst, strip.
  - `find_shopping_project_id(api, override: str | None) -> str` — `override` falls gesetzt, sonst Projekt mit Name (case-insensitiv) „einkaufsliste“; nicht gefunden → `LookupError`.
  - `open_items(api, project_id: str) -> list[str]` — Titel aller aktiven Tasks; Titel mit leerem `normalize` werden ausgelassen.

`shopping.py` darf beim Import keine Env-Variablen verlangen. `bot.py` fängt `LookupError` und gibt die bestehende Fehlermeldung aus (Text unverändert).

- [ ] **Step 1: Failing tests**

```python
def test_strip_emoji(): assert strip_emoji("🥛 Milch") == "Milch"; assert strip_emoji("👨‍👩‍👧 Familienpackung") == "Familienpackung"
def test_normalize(): assert normalize("  🍌  Bio  Bananen ") == "bio bananen"
def test_find_project_override(): assert find_shopping_project_id(fake_api, "123") == "123"
def test_find_project_by_name(): ...  # Seiten [[P("Inbox"), P("EinkaufsListe", id="9")]] → "9"
def test_find_project_missing_raises(): ...
def test_open_items_skips_emoji_only(): ...  # ["🥛 Milch", "🛒", ""] → ["🥛 Milch"]
```
- [ ] **Step 2:** `bash setup-venv.sh && .venv/bin/python3 -m pytest` → FAIL
- [ ] **Step 3:** Implementieren, `bot.py` umstellen.
- [ ] **Step 4:** Tests → PASS; `.venv/bin/python3 bot.py --help` läuft.
- [ ] **Step 5:** Commit `refactor: share shopping project lookup; add pytest`

---

### Task 5: Lern-Historie und Stammartikel (`todoist-cli`)

**Files:**
- Create: `staples.py`, `tests/test_staples.py`
- Modify: `.gitignore` (`.shopping_history.json`)

**Interfaces:**
- Consumes: Task 4 `normalize`.
- Produces:
  - `load_history(path: Path) -> dict` — fehlend/kaputt → `{"last_sync": None, "items": {}}`.
  - `save_history(path: Path, history: dict) -> None`
  - `fetch_completed(api, project_id: str, since: datetime, until: datetime) -> list[Task]` — `api.get_completed_tasks_by_completion_date(since=, until=, limit=200)`, clientseitig auf `task.project_id == project_id` gefiltert. Spanne > 89 Tage in Fenster ≤ 89 Tage zerlegen.
  - `sync_history(history: dict, tasks: list, now: datetime) -> dict` — pro Task: Schlüssel `normalize(content)` (leer → überspringen), `display = content` (letzter gewinnt), Datum `completed_at.date().isoformat()` in `completed`, `task.id` in `ids` (schon vorhanden → überspringen). Setzt `last_sync = now.isoformat()`.
  - `sync_since(history: dict, now: datetime, window_days: int) -> datetime` — `last_sync` oder `now - window_days`.
  - `compute_staples(history: dict, open_normalized: set[str], min_count: int, window_days: int, today: date) -> list[str]` — Display-Titel, sortiert nach Häufigkeit absteigend, dann alphabetisch.

Format pro Eintrag: `{"display": str, "completed": [iso-date], "ids": [str]}`.

- [ ] **Step 1: Failing tests**

```python
def test_load_missing_and_corrupt(tmp_path)
def test_sync_dedupes_by_task_id()
def test_sync_merges_emoji_variants()          # "🥛 Milch" und "Milch" → ein Schlüssel "milch"
def test_staples_threshold()                   # 3× in 90 Tagen → drin; 2× → nicht; 3× davon 1 vor 100 Tagen → nicht
def test_staples_exclude_open()
def test_fetch_completed_filters_project_and_windows()  # Fake-API zeichnet (since, until) auf; 200 Tage → 3 Fenster
def test_sync_since_first_run()                # last_sync None → now - 90 Tage
```
- [ ] **Step 2:** Tests → FAIL
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests → PASS
- [ ] **Step 5:** Commit `feat: learn staple shopping items from completion history`

---

### Task 6: Matching Regex + Gemini (`todoist-cli`)

**Files:**
- Create: `matching.py`, `tests/test_matching.py`

**Interfaces:**
- Produces (Deals sind Dicts im `Deal.to_dict()`-Format aus Task 3; Artikel-Schlüssel = `normalize(title)`):
  - `regex_match(items: list[str], deals: list[dict]) -> dict[str, list[dict]]`
  - `build_gemini_prompt(items: list[str], deals: list[dict]) -> str`
  - `parse_gemini_response(raw: str, items: list[str], deals: list[dict]) -> dict[str, list[dict]]` — wirft `ValueError` bei ungültigem JSON/kein Objekt.
  - `gemini_match(items: list[str], deals: list[dict], call: Callable[[str], str | None]) -> dict[str, list[dict]]` — `call` liefert Rohtext; `None`/Exception → `ValueError` weiterreichen (Fallback entscheidet der Aufrufer).

Regex-Regel (Spec): Tokens = `re.findall(r"[a-zäöüß0-9]+", (brand + " " + product_name).lower())`. `stem(w)`: erste passende Endung aus `("en", "n", "e", "s")` abschneiden, wenn danach ≥ 3 Zeichen. Artikelwort (≥ 3 Zeichen) passt, wenn `stem(token).endswith(stem(wort))` für ein Token. Alle Artikelwörter müssen passen; Artikel ohne Wörter ≥ 3 Zeichen → keine Treffer.

Gemini-Prompt: deutsch; Deal-Zeilen `<id>|<store>|<brand> <product_name>|<price>`; Regel „nur Deals, die tatsächlich dieses Produkt sind (Milch ≠ Milchschokolade, Butter ≠ Buttermilch)“; Antwort nur minifiziertes JSON `{"<artikel>": ["<id>", ...]}` mit den Artikelnamen exakt wie übergeben. Beim Parsen ```-Fences entfernen (wie `bot.py`), unbekannte Artikel und IDs verwerfen, Reihenfolge der Deals wie in der Eingabe.

- [ ] **Step 1: Failing tests**

```python
def test_regex_compound_head():
    assert ids(regex_match(["milch"], [d("Milsani Frische Vollmilch 1l"), d("Milka Milchschokolade")]))["milch"] == ["vollmilch-id"]
def test_regex_butter_not_buttermilch()
def test_regex_plural(): # "bananen" passt "Chiquita Banane"; "eier" passt "Freilandeier 10 Stk"
def test_regex_multiword(): # "bio bananen" braucht beide Wörter
def test_regex_brand_counts(): # Artikel "jacobs" passt brand="Jacobs"
def test_prompt_contains_items_and_deal_lines()
def test_parse_strips_fences_and_drops_unknown(): # ```json{"milch":["id1","fake"],"brot":["id2"]}``` mit items=["milch"] → {"milch":[deal id1]}
def test_parse_invalid_raises()
def test_gemini_match_none_raises()
```
- [ ] **Step 2:** Tests → FAIL
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests → PASS
- [ ] **Step 5:** Commit `feat: add regex and Gemini deal matching`

---

### Task 7: Nachrichtenformat (`todoist-cli`)

**Files:**
- Create: `render.py`, `tests/test_render.py`

**Interfaces:**
- Produces: `format_message(open_items: list[str], staples: list[str], matches: dict[str, list[dict]], today: date, *, ai_fallback: bool = False, header: str | None = None) -> str`
  - `open_items`/`staples` sind Display-Titel; Lookup in `matches` über `normalize(title)`.
  - `header` überschreibt die Kopfzeile (für `compare`: „🛒 Abgleich: Gemini“ / „🛒 Abgleich: Regex“).

Format exakt wie Spec-Beispiel: Kopf `🛒 Angebote für deine Einkaufsliste (DD.MM.)`, Leerzeile, pro Artikel mit Treffern Display-Titel, darunter bis zu 3 Deals nach Preis aufsteigend als `  <STORE>  <name> — <preis>[ (statt <orig>, -<n>%)] | DD.MM–DD.MM` (Name/Preis/Datum wie `supermarket-scraper/formatter.py::_fmt_deal_line`: Brand voranstellen, wenn der Name nicht schon damit beginnt; `0,99€`). Stammartikel mit Treffern unter Zeile `⭐ Stammartikel`. Am Ende `Keine Angebote: <Titel ohne Emoji, kommagetrennt>` nur für offene Artikel. Keine Treffer überhaupt → `Keine Angebote für deine Einkaufsliste gefunden.` (statt Kopf + Liste). `ai_fallback` → letzte Zeile `(Abgleich ohne KI – Gemini nicht verfügbar)`. Länge > 4000 → ganze Artikelblöcke von hinten entfernen, bis Text inkl. `… und N weitere` ≤ 4000.

- [ ] **Step 1: Failing tests**

```python
def test_format_matches_spec_example()   # erwarteter String 1:1 aus der Spec (Milch: 2 Deals, Kaffee als Stammartikel, Keine Angebote: Brot, Eier)
def test_max_three_sorted_by_price()
def test_nothing_found()
def test_staple_without_deals_not_listed()
def test_ai_fallback_line()
def test_truncation(): # 60 Artikel à 3 Deals → len <= 4000, endet mit "… und N weitere" (N korrekt)
```
- [ ] **Step 2:** Tests → FAIL
- [ ] **Step 3:** Implementieren.
- [ ] **Step 4:** Tests → PASS
- [ ] **Step 5:** Commit `feat: render shopping deal message`

---

### Task 8: `shopping_deals.py` CLI, Konfiguration, Doku (`todoist-cli`)

**Files:**
- Create: `shopping_deals.py`, `tests/test_shopping_deals.py`
- Modify: `.env.example`, `setup-venv.sh` (`chmod +x … shopping_deals.py`), `README.md` (falls nicht vorhanden: anlegen mit Abschnitt „Schnäppchen-Abgleich“ inkl. HA-Einrichtung aus der Spec)

**Interfaces:**
- Consumes: Tasks 4–7; Scraper-JSON aus Task 3.
- Produces:
  - `run_scraper(scraper_dir: Path, terms: list[str], force: bool, timeout: int = 300) -> dict` — `subprocess.run([scraper_dir/".venv/bin/python", scraper_dir/"scraper.py", "--json", "--terms", ",".join(terms)] + (["--force"] if force else []), capture_output=True, text=True, timeout=timeout)`; Exit ≠ 0, Timeout oder ungültiges JSON → `RuntimeError`. Scraper-stderr wird auf eigenes stderr durchgereicht.
  - `collect_deals(scraper_json: dict) -> list[dict]` — alle Deals aller Begriffe, dedupliziert per `id`.
  - `main(argv: list[str] | None = None) -> int`

Ablauf wie Spec-„Ablauf“ 1–6. Präambel (venv-Re-exec, `load_dotenv`) wie `bot.py`, aber Env-Prüfung (`TODOIST_TOKEN`, `SUPERMARKET_SCRAPER_DIR`) in `main()`, damit Tests importieren können. Fehltexte: `Fehler: SUPERMARKET_SCRAPER_DIR nicht gesetzt (.env).`, `Fehler: Projekt 'Einkaufsliste' nicht gefunden.`, `Fehler: Angebote konnten nicht geladen werden.` → Exit 1. Suchbegriffe = `normalize` der offenen + Stamm-Titel, Kommas → Leerzeichen, dedupliziert. Historie: `.shopping_history.json` neben dem Skript; `--dry-run` speichert sie nicht. `--matcher gemini`: `gemini_match` mit `bot`-artigem Aufruf (eigene kleine `_gemini_text` mit `GOOGLE_API_KEY`/`GEMINI_MODEL`, Default `gemini-2.0-flash-lite`); `ValueError`/Exception → `regex_match` + `ai_fallback=True` + Warnung auf stderr. `compare`: beide Nachrichten mit eigenen Headern, getrennt durch Leerzeile, stdout.

- [ ] **Step 1: Failing tests** (Todoist-API, `run_scraper` bzw. `subprocess.run` und Gemini-Aufruf gemockt; `tmp_path` für Historie)

```python
def test_run_scraper_builds_command(tmp_path)        # argv enthält --json, --terms "milch,kaffee", --force nur wenn gesetzt
def test_run_scraper_nonzero_raises()
def test_terms_from_open_and_staples()               # offene ["🥛 Milch", "Äpfel, rot"] + Stamm ["☕ Kaffee"] → ["milch", "äpfel rot", "kaffee"]
def test_collect_deals_dedupes()
def test_gemini_failure_falls_back(capsys)           # Gemini wirft → stdout endet mit "(Abgleich ohne KI – Gemini nicht verfügbar)", Exit 0
def test_compare_prints_both(capsys)                 # "Abgleich: Gemini" und "Abgleich: Regex" in stdout, Gemini 1× aufgerufen
def test_missing_scraper_dir(capsys)                 # Exit 1, Fehltext auf stderr
def test_dry_run_does_not_save_history(tmp_path)
```
- [ ] **Step 2:** Tests → FAIL
- [ ] **Step 3:** Implementieren; `.env.example` um `SUPERMARKET_SCRAPER_DIR=/config/supermarket-scraper` (Beispielpfad, kommentiert), `SHOPPING_STAPLE_MIN_COUNT=3`, `SHOPPING_STAPLE_WINDOW_DAYS=90` ergänzen; README-Abschnitt inkl. HA: Zeitplan So+Mi 08:00 mit `--force`, Telegram-Befehl „angebote“ ohne.
- [ ] **Step 4:** `.venv/bin/python3 -m pytest` → alles PASS
- [ ] **Step 5:** Lokaler Smoke-Test (braucht `SUPERMARKET_SCRAPER_DIR` in `.env` und Netz): `.venv/bin/python3 shopping_deals.py --matcher compare --dry-run` → zwei Nachrichtenblöcke. Fehlt die Variable, Nutzer fragen statt `.env` selbst zu ändern.
- [ ] **Step 6:** Commit `feat: add shopping_deals.py to match shopping list against deals`
