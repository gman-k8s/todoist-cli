# Einkaufsliste × Supermarkt-Schnäppchen — Design

Datum: 2026-11-20
Repos: `todoist-cli` (Orchestrierung, dieses Dokument) und `supermarket-scraper` (Datenquelle)

## Intent

Zweimal pro Woche (sonntags, mittwochs) automatisch oder auf Telegram-Befehl soll der Nutzer erfahren,
welche Dinge, die er kaufen will oder regelmäßig kauft, gerade im Angebot sind. Grundlage:

- offene Punkte der Todoist-Einkaufsliste,
- „Stammartikel“: Dinge, die regelmäßig auf der Einkaufsliste landen, auch wenn sie gerade nicht drauf stehen,
- die Angebote von marktguru.de / aktionspreis.de, die `supermarket-scraper` liefert.

Beide Repos sind auf der Home-Assistant-VM ausgecheckt; Telegram-Nachrichten werden über Node-RED zu
HA-Events, HA-Automationen rufen die Skripte auf und schicken stdout zurück an Telegram.
Alles muss auch lokal lauffähig sein.

## Ziele

1. Abgleich offene Einkaufspunkte + Stammartikel gegen Angebote, Ergebnis als kompakte deutsche Telegram-Nachricht.
2. Angebote werden als Textdateien zwischengespeichert; standardmäßig wird der Zwischenspeicher gelesen,
   `--force` lädt frisch aus den Online-Quellen.
3. Stammartikel werden aus der Erledigt-Historie des Einkaufslisten-Projekts gelernt und über die Zeit lokal gesammelt.
4. Matching per Gemini (Favorit) mit regelbasiertem Fallback; ein Vergleichsmodus zeigt beide Verfahren nebeneinander,
   damit wir entscheiden können, welches besser ist.

## Nicht-Ziele

- Nichts wird in Todoist zurückgeschrieben (keine Kommentare, Labels, neuen Tasks).
- Keine neuen Angebotsquellen, keine Preisverlaufs-Auswertung.
- Die bestehende Ausgabe von `scraper.py` ohne neue Flags bleibt, wie sie ist.

## Anti-Ziele (wäre ein Fehlschlag, selbst wenn es technisch läuft)

- Telegram-Nachricht, die so lang ist, dass sie niemand liest oder Telegram sie ablehnt (> 4096 Zeichen).
- Bestehende HA-Automationen, die `scraper.py` heute aufrufen (inkl. `--force`), verhalten sich anders als vorher
  in dem, was sie ausgeben.
- Gemini-Free-Tier wird überschritten oder ein Gemini-Ausfall lässt den ganzen Lauf scheitern.
- Ein frisch auf die Einkaufsliste gesetzter Artikel wird nie gesucht, weil nur der Zwischenspeicher gelesen wird.

## Ansätze

| | Ansatz | Trade-off |
|---|---|---|
| **A (gewählt)** | Orchestrierung in `todoist-cli` (`shopping_deals.py`); Scraper bekommt `--terms`, Textdatei-Cache, JSON-Ausgabe | Todoist- und Gemini-Logik bleiben an einem Ort, Scraper braucht keine Todoist-Credentials. Kosten: `todoist-cli` muss den Pfad zum Scraper kennen. |
| B | Alles in `supermarket-scraper` | Ein Einstiegspunkt für HA, aber Todoist-Projektsuche, Gemini-Client und `.env` doppelt. |
| C | Drittes Glue-Skript | Mehr Pflege ohne Nutzen. |

Der Nutzer hat **A** gewählt.

Suchbegriffe: Der Scraper sucht nur nach Stichworten, es gibt keinen „Gesamtkatalog“. Der Nutzer hat entschieden:
**Suchbegriffe = Watchlist (`products.txt`) ∪ offene Einkaufspunkte ∪ Stammartikel.**

## Design

### Teil 1 — `supermarket-scraper`

**Neue Flags**

| Flag | Wirkung |
|---|---|
| `--terms "milch,eier,kaffee"` | Zusätzliche Suchbegriffe (kommagetrennt), werden mit `products.txt` vereinigt (lowercase, dedupliziert). |
| `--force` | Lädt **alle** Suchbegriffe frisch online **und** zeigt alle Treffer ohne Seen-Cache (bisherige Bedeutung bleibt damit erhalten — Obermenge). |
| `--all` | Zeigt alle Treffer ohne Seen-Cache, liest aber aus dem Textdatei-Cache (die alte `--force`-Ausgabe ohne Netz). |
| `--json` | Maschinenausgabe statt deutscher Textausgabe (siehe unten). Kein Matching, kein Seen-Cache, kein `cache.json`/`results.json`. |

`--dry-run` bleibt: schreibt weder `cache.json`, `results.json`, Preis-DB noch Textdatei-Cache.

**Textdatei-Cache** — `output/deals/<slug>.txt`, eine Datei pro Suchbegriff
(`slug` = Begriff lowercase, Umlaute erhalten, alles außer `[a-z0-9äöüß]` → `-`).

```
# term: milch
# fetched: 2026-11-20T08:00:12
# sources: marktguru,aktionspreis
<id>\t<store>\t<brand>\t<product_name>\t<price>\t<original_price>\t<discount_pct>\t<valid_from>\t<valid_to>\t<source>\t<ean>
...
```

TSV, leere Felder als leerer String; Tabs/Zeilenumbrüche in Feldern werden durch Leerzeichen ersetzt.
Eine Datei mit nur Header bedeutet „gesucht, nichts gefunden“ (und ist damit ein gültiger Cache-Eintrag).

**Lade-Regel pro Suchbegriff**

1. `--force` → online laden, Datei überschreiben.
2. Datei existiert und `fetched` jünger als `cache.deals_max_age_days` (neu in `settings.toml`, Default `7`) → aus Datei lesen.
3. Sonst (fehlt oder zu alt) → online laden, Datei schreiben.

Beim Lesen werden Deals mit `valid_to < heute` verworfen.
Schlägt der Online-Abruf einer Quelle für einen Begriff fehl und es gibt eine (auch alte) Datei, wird die Datei benutzt
und eine `Warnung:` auf stderr ausgegeben. Die bestehende Regel „Exit 1 nur wenn beide Quellen ausfallen“ gilt weiter,
bezogen auf die Begriffe, die tatsächlich online geladen werden mussten.

Dafür werden die Scraper pro Begriff aufgerufen (`products=[term]`) oder `fetch()` liefert Deals gruppiert nach Begriff —
Umsetzung dem Builder überlassen. Der `x-clientkey` von marktguru soll pro Lauf nur einmal geholt werden.

Eine Cache-Datei wird nur geschrieben, wenn **beide** Quellen für den Begriff erfolgreich waren; bei Teilausfall
werden die Deals der erfolgreichen Quelle verwendet, aber nicht gecacht (sonst läge eine halbe Liste 7 Tage im Cache).

Die Preis-DB bekommt weiterhin alle **online** geladenen Deals.

**`--json`-Ausgabe** (stdout, UTF-8):

```json
{
  "generated_at": "2026-11-20T08:00:15",
  "terms": {
    "milch": {"fetched": "2026-11-20T08:00:12", "from_cache": false, "deals": [ {Deal.to_dict()}, ... ]},
    ...
  },
  "warnings": ["..."]
}
```

Alle Deals der angefragten Begriffe (Watchlist + `--terms`), gefiltert auf konfigurierte Märkte, abgelaufene entfernt.

### Teil 2 — `todoist-cli/shopping_deals.py`

Neues Skript mit derselben venv-Re-exec-Präambel wie `bot.py`.

```
shopping_deals.py [--force] [--matcher gemini|regex|compare] [--dry-run]
```

- `--force` wird an den Scraper durchgereicht.
- `--matcher` Default `gemini`; fällt bei Fehler (kein Key, Timeout, ungültiges JSON) automatisch auf `regex` zurück und
  hängt eine Zeile `(Abgleich ohne KI – Gemini nicht verfügbar)` an.
- `compare` gibt beide Ergebnisse nacheinander aus (für den Test, welches Verfahren besser ist).
- `--dry-run` schreibt die Lern-Historie nicht.

**Ablauf**

1. Einkaufslisten-Projekt bestimmen: `TODOIST_SHOPPING_PROJECT_ID` oder Suche nach Name „Einkaufsliste“.
   Die Logik aus `bot.py` wird in ein kleines gemeinsames Modul (`shopping.py`) ausgelagert und von beiden genutzt.
2. Offene Tasks des Projekts holen → Artikelnamen (führendes Emoji und Whitespace entfernen).
3. Lern-Historie aktualisieren (s. u.) → Stammartikel, die nicht offen sind.
4. Scraper aufrufen:
   `$SUPERMARKET_SCRAPER_DIR/.venv/bin/python $SUPERMARKET_SCRAPER_DIR/scraper.py --json --terms "<offen ∪ stamm>" [--force]`
   Timeout großzügig (Default 300 s). Exit ≠ 0 → Fehlermeldung `Fehler: Angebote konnten nicht geladen werden.` und Exit 1.
5. Matching (s. u.) → pro Artikel Liste passender Deals.
6. Ausgabe auf stdout.

**Lernen (Stammartikel)**

- Lokale Datei `.shopping_history.json` (gitignored):
  `{"last_sync": "<iso>", "items": {"<normalisiert>": {"display": "🥛 Milch", "completed": ["2026-11-02", ...]}}}`
- Jeder Lauf holt erledigte Tasks des Einkaufsprojekts seit `last_sync` (erster Lauf: die letzten
  `SHOPPING_STAPLE_WINDOW_DAYS` Tage, in Fenstern, die der Endpoint akzeptiert — `get_completed_tasks_by_completion_date`, wie in `digest.py`) und hängt
  Erledigungsdaten an. Duplikate (gleiche Task-ID) werden ignoriert; dafür die IDs mitspeichern.
- `display` = zuletzt gesehener Original-Titel. Gelöschte (statt erledigte) Tasks zählen nicht.
- Normalisierung: Emoji entfernen, lowercase, Whitespace zusammenfassen.
- Stammartikel = Einträge mit **≥ `SHOPPING_STAPLE_MIN_COUNT` (Default 3) Erledigungen in den letzten
  `SHOPPING_STAPLE_WINDOW_DAYS` (Default 90) Tagen**, die gerade nicht offen sind.

**Matching**

Eingabe: Artikel (offen + Stamm) und alle Deals aus der Scraper-JSON (dedupliziert per `id`).

- `regex`: Ein Deal passt zu einem Artikel, wenn jedes Wort des Artikels (≥ 3 Zeichen) als Wort oder
  Kompositum-**Ende** in `brand + product_name` vorkommt (deutsche Komposita tragen das Grundwort hinten:
  „Vollmilch“ passt zu „Milch“, „Milchschokolade“ und „Buttermilch“ (für „Butter“) nicht) (case-insensitiv, einfache Pluralreduktion: Endungen `n`, `en`, `e`, `s` abschneiden,
  wenn danach ≥ 3 Zeichen bleiben). Deals, die über den Suchbegriff des Artikels gefunden wurden, sind Kandidaten;
  Deals aus anderen Begriffen (z. B. Watchlist) ebenfalls.
- `gemini`: **Ein** Aufruf pro Lauf. Prompt auf Deutsch, enthält Artikel-Liste und kompakte Deal-Zeilen
  (`<id>|<store>|<brand> <product_name>|<price>`). Anweisung: Ordne jedem Artikel nur Deals zu, die tatsächlich dieses
  Produkt sind (z. B. „Milch“ ≠ „Milchschokolade“, „Butter“ ≠ „Buttermilch“). Antwort: minifiziertes JSON
  `{"<artikel>": ["<id>", ...]}`. Unbekannte IDs werden verworfen. Modell aus `GEMINI_MODEL`.
  Budget: ~1 Aufruf je Lauf, geschätzt 10–30 k Input-Tokens → weit unter Free-Tier-Limits.

**Ausgabe** (deutsch, Telegram-tauglich)

```
🛒 Angebote für deine Einkaufsliste (20.11.)

🥛 Milch
  LIDL  Milsani Frische Vollmilch 1l — 0,99€ (statt 1,29€, -23%) | 18.11–23.11
  ALDI  Milsani H-Milch 1l — 0,89€ | 20.11–22.11

⭐ Stammartikel
☕ Kaffee
  NETTO  Jacobs Krönung 500g — 4,99€ (statt 7,49€, -33%) | 20.11–25.11

Keine Angebote: Brot, Eier
```

- Pro Artikel höchstens 3 Deals, sortiert nach Preis.
- Preis-/Datumsformat wie `supermarket-scraper/formatter.py`.
- Nichts gefunden → `Keine Angebote für deine Einkaufsliste gefunden.`
- Gesamtausgabe auf 4000 Zeichen begrenzt; bei Überlauf werden die letzten Artikel abgeschnitten und
  `… und N weitere` angehängt.

### Konfiguration (`todoist-cli/.env`, in `.env.example` dokumentiert)

| Variable | Pflicht | Default |
|---|---|---|
| `SUPERMARKET_SCRAPER_DIR` | ja | — (Fehlermeldung, wenn fehlt) |
| `SHOPPING_STAPLE_MIN_COUNT` | nein | 3 |
| `SHOPPING_STAPLE_WINDOW_DAYS` | nein | 90 |
| `TODOIST_SHOPPING_PROJECT_ID` | nein | Suche nach „Einkaufsliste“ |

`supermarket-scraper/config.example/settings.toml` bekommt `[cache] deals_max_age_days = 7`.

### Home Assistant

Außerhalb der Repos, vom Nutzer einzurichten (Claude erreicht HA nicht); die README von `todoist-cli` beschreibt es:

- Zeitgesteuert sonntags und mittwochs 08:00: `shopping_deals.py --force` → stdout an Telegram.
- Telegram-Befehl (Text „angebote“ bzw. `/angebote`): `shopping_deals.py` (liest Cache) → stdout an Telegram.

## Tests

- `supermarket-scraper`: Cache schreiben/lesen/Ablauf, Lade-Regel (frisch/alt/fehlend/`--force`), `--json`-Format,
  `--terms`-Vereinigung, Fallback auf alte Datei bei Netzfehler, unveränderte Default-Ausgabe. Netz gemockt wie bisher.
- `todoist-cli` hat bisher keine Python-Tests; für `shopping_deals.py` pytest neu einführen: Normalisierung,
  Stammartikel-Berechnung, regex-Matcher (inkl. Milch/Milchschokolade, Butter/Buttermilch), Gemini-Antwort-Parsing und
  Fallback, Ausgabeformat und Kürzung. Todoist, Gemini und Scraper-Subprozess gemockt.

## Dem Builder überlassen

- Ob die Scraper pro Begriff aufgerufen werden oder `fetch()` gruppiert zurückgibt.
- Genaue Prompt-Formulierung für Gemini.
- Interne Struktur von `shopping_deals.py` (Module), solange `shopping.py` die Projektsuche teilt.

## Calls, die Claude ohne Rückfrage getroffen hat

- `--force` behält die alte Bedeutung und lädt zusätzlich frisch; neues `--all` für die alte Ausgabe ohne Netz.
- Fehlende/zu alte Cache-Einträge werden auch ohne `--force` online geladen (sonst würden neue Einkaufspunkte nie gesucht).
- Zeitgesteuerte Läufe nutzen `--force`, Telegram-Befehl nicht.
- Stammartikel-Schwelle 3× in 90 Tagen, lokale Historie-Datei.
- Max. 3 Deals pro Artikel, keine Rückschreibung nach Todoist.
- Cache-Datei nur bei vollständigem Abruf beider Quellen; Erst-Backfill der Historie = 90 Tage.
- HA-Zeitplan 08:00 und Befehlswort „angebote“ — beides frei in HA änderbar. Auch bei „keine Angebote“ wird eine Nachricht geschickt.
