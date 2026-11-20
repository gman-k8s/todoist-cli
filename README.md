# todoist-cli

Small Todoist helpers driven from Home Assistant / Telegram:

- `bot.py` — add tasks (`--title`, `--text` via Gemini, `--shopping` for the Einkaufsliste)
- `digest.py` — daily summary of completed tasks
- `chores.py`, `time_labels.py` — chore and duration helpers
- `shopping_deals.py` — Schnäppchen-Abgleich (below)

Setup: `bash setup-venv.sh`, then copy `.env.example` to `.env` and fill it in.
Tests: `.venv/bin/python3 -m pytest`

## Schnäppchen-Abgleich

`shopping_deals.py` matches the open items of the Todoist project „Einkaufsliste“ plus learned **Stammartikel**
against current supermarket deals from [supermarket-scraper](../supermarket-scraper), and prints a German,
Telegram-sized message (≤ 4000 chars, max. 3 deals per item, cheapest first).

```bash
.venv/bin/python3 shopping_deals.py                     # deals from the scraper's text cache (missing terms fetched live)
.venv/bin/python3 shopping_deals.py --force             # reload all deals online
.venv/bin/python3 shopping_deals.py --matcher regex     # rule-based matching, no Gemini
.venv/bin/python3 shopping_deals.py --matcher compare   # print Gemini and regex results one after another
.venv/bin/python3 shopping_deals.py --dry-run           # don't save the learning history
.venv/bin/python3 shopping_deals.py --timeout 900       # scraper time limit in s (default 45, below HA's 60 s)
```

How it works:

1. Reads open tasks of „Einkaufsliste“ (`TODOIST_SHOPPING_PROJECT_ID` or lookup by name).
2. Syncs completed shopping tasks into `.shopping_history.json`. Items completed at least
   `SHOPPING_STAPLE_MIN_COUNT` (3) times within `SHOPPING_STAPLE_WINDOW_DAYS` (90) days and not currently open
   are Stammartikel.
3. Runs `$SUPERMARKET_SCRAPER_DIR/scraper.py --json --terms "<items>"` (search terms = scraper watchlist +
   open items + Stammartikel).
4. Matches with one Gemini call (`GEMINI_MODEL`); on any Gemini error it falls back to regex matching and says so
   in the message. Regex rule: every item word must appear as a word or as the *end* of a compound
   („Vollmilch“ matches „Milch“, „Milchschokolade“ doesn't).

Required `.env`: `TODOIST_TOKEN`, `SUPERMARKET_SCRAPER_DIR`; `GOOGLE_API_KEY` for Gemini.

### Home Assistant

Both repos checked out on the HA VM, `SUPERMARKET_SCRAPER_DIR` pointing to the scraper checkout there.

HA kills a `shell_command` after 60 s. `shopping_deals.py` therefore passes `--deadline <timeout − 15 s>` to the
scraper: once that budget is used up, remaining terms come from the cache (any age), and terms that were never
cached are listed as „Noch nicht geladen (kommt beim nächsten Lauf)“. If the scraper still hits the hard timeout,
a second cache-only call (`--deadline 0`) is made, so a message always goes out.

HA kills a `shell_command` after 60 s. A cached run takes well under a second, but fetching online costs about
10 s per search term (aktionspreis.de loads one page per offer), so a `--force` run with many terms does not fit.
Therefore the scheduled run is split into a background warm-up and a fast cached run:

```yaml
shell_command:
  shopping_deals_warmup: "nohup /config/todoist-cli/shopping_deals.py --force --matcher regex --timeout 900 >/dev/null 2>&1 &"
  shopping_deals: "/config/todoist-cli/shopping_deals.py"
```

- Automation 1: Monday + Wednesday 07:30 → `shell_command.shopping_deals_warmup` (returns immediately, refreshes
  `output/deals/` in the scraper checkout).
- Automation 2: Monday + Wednesday 08:00 → `shell_command.shopping_deals` with `response_variable`, send
  `stdout` to Telegram.
- Automation 3: Telegram command `/angebote` → `shell_command.shopping_deals` →
  `stdout` to Telegram. Only items not yet cached are fetched live (≈ 10 s each).

Adjust the paths to where the repos live on the VM.
