import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import shopping_deals as sd


def deal(id, name, price=1.0, store="lidl", brand=None):
    return {"id": id, "store": store, "brand": brand, "product_name": name, "price": price,
            "original_price": None, "discount_pct": None, "valid_from": "2026-11-18",
            "valid_to": "2099-11-23", "source": "marktguru", "ean": None}


SCRAPER_JSON = {
    "generated_at": "2026-11-20T08:00:00",
    "terms": {
        "milch": {"fetched": "x", "from_cache": True, "deals": [deal("m1", "Vollmilch"), deal("s1", "Milchschokolade")]},
        "kaffee": {"fetched": "x", "from_cache": True, "deals": [deal("k1", "Kaffee Auslese", brand="Melitta")]},
        "butter": {"fetched": "x", "from_cache": True, "deals": [deal("m1", "Vollmilch")]},
    },
    "warnings": [],
}


class FakeApi:
    def __init__(self, open_titles, completed=()):
        self.open_titles = open_titles
        self.completed = list(completed)

    def get_projects(self):
        yield [SimpleNamespace(name="Einkaufsliste", id="9")]

    def get_tasks(self, project_id=None, limit=None):
        yield [SimpleNamespace(content=t) for t in self.open_titles]

    def get_completed_tasks_by_completion_date(self, since, until, limit=None):
        yield [t for t in self.completed if since <= t.completed_at <= until]


def _completed_kaffee():
    now = datetime.now(timezone.utc)
    return [SimpleNamespace(id=str(i), content="☕ Kaffee", project_id="9", completed_at=now - timedelta(days=i + 1))
            for i in range(3)]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TODOIST_TOKEN", "t")
    monkeypatch.setenv("SUPERMARKET_SCRAPER_DIR", str(tmp_path / "scraper"))
    monkeypatch.delenv("TODOIST_SHOPPING_PROJECT_ID", raising=False)
    monkeypatch.delenv("SHOPPING_STAPLE_MIN_COUNT", raising=False)
    monkeypatch.delenv("SHOPPING_STAPLE_WINDOW_DAYS", raising=False)
    monkeypatch.setattr(sd, "HISTORY_FILE", tmp_path / "history.json")
    return tmp_path


def _run(argv, api, gemini=None, scraper=None):
    with patch.object(sd, "TodoistAPI", return_value=api), \
         patch.object(sd, "run_scraper", scraper or MagicMock(return_value=SCRAPER_JSON)), \
         patch.object(sd, "_gemini_text", gemini or MagicMock(return_value='{"milch":["m1"],"kaffee":["k1"]}')):
        return sd.main(argv)


def test_run_scraper_builds_command(tmp_path):
    done = subprocess.CompletedProcess([], 0, stdout=json.dumps(SCRAPER_JSON), stderr="")
    with patch("shopping_deals.subprocess.run", return_value=done) as run:
        sd.run_scraper(tmp_path, ["milch", "kaffee"], force=False)
        sd.run_scraper(tmp_path, ["milch"], force=True)
    first, second = run.call_args_list[0].args[0], run.call_args_list[1].args[0]
    assert first[0] == str(tmp_path / ".venv/bin/python") and first[1] == str(tmp_path / "scraper.py")
    assert first[2:] == ["--json", "--terms", "milch,kaffee"]
    assert second[-1] == "--force"


def test_run_scraper_nonzero_raises(tmp_path):
    with patch("shopping_deals.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "boom")):
        with pytest.raises(RuntimeError):
            sd.run_scraper(tmp_path, ["milch"], force=False)


def test_run_scraper_invalid_json_raises(tmp_path):
    with patch("shopping_deals.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "nope", "")):
        with pytest.raises(RuntimeError):
            sd.run_scraper(tmp_path, ["milch"], force=False)


def test_terms_from_open_and_staples():
    assert sd.search_terms(["🥛 Milch", "Äpfel, rot", "milch"], ["☕ Kaffee"]) == ["milch", "äpfel rot", "kaffee"]


def test_collect_deals_dedupes():
    assert [d["id"] for d in sd.collect_deals(SCRAPER_JSON)] == ["m1", "s1", "k1"]


def test_gemini_happy_path_with_staple(env, capsys):
    scraper = MagicMock(return_value=SCRAPER_JSON)
    assert _run([], FakeApi(["🥛 Milch", "Brot"], _completed_kaffee()), scraper=scraper) == 0
    out = capsys.readouterr().out
    assert "🥛 Milch\n  LIDL  Vollmilch — 1,00€" in out
    assert "Milchschokolade" not in out
    assert "⭐ Stammartikel\n☕ Kaffee" in out
    assert "Keine Angebote: Brot" in out
    assert scraper.call_args.args[1] == ["milch", "brot", "kaffee"]
    assert scraper.call_args.kwargs["force"] is False


def test_gemini_failure_falls_back(env, capsys):
    rc = _run([], FakeApi(["🥛 Milch"]), gemini=MagicMock(side_effect=RuntimeError("quota")))
    out, err = capsys.readouterr()
    assert rc == 0
    assert out.rstrip("\n").endswith("(Abgleich ohne KI – Gemini nicht verfügbar)")
    assert "Warnung:" in err


def test_compare_prints_both(env, capsys):
    gemini = MagicMock(return_value='{"milch":["m1"]}')
    _run(["--matcher", "compare"], FakeApi(["🥛 Milch"]), gemini=gemini)
    out = capsys.readouterr().out
    assert "🛒 Abgleich: Gemini" in out and "🛒 Abgleich: Regex" in out
    assert gemini.call_count == 1


def test_force_passed_to_scraper(env):
    scraper = MagicMock(return_value=SCRAPER_JSON)
    _run(["--force", "--matcher", "regex"], FakeApi(["Milch"]), scraper=scraper)
    assert scraper.call_args.kwargs["force"] is True


def test_missing_scraper_dir(env, monkeypatch, capsys):
    monkeypatch.delenv("SUPERMARKET_SCRAPER_DIR")
    assert _run([], FakeApi(["Milch"])) == 1
    assert "Fehler: SUPERMARKET_SCRAPER_DIR nicht gesetzt (.env)." in capsys.readouterr().err


def test_scraper_failure_exit_1(env, capsys):
    assert _run([], FakeApi(["Milch"]), scraper=MagicMock(side_effect=RuntimeError("x"))) == 1
    assert "Fehler: Angebote konnten nicht geladen werden." in capsys.readouterr().err


def test_empty_list_and_no_staples_skips_scraper(env, capsys):
    scraper = MagicMock()
    assert _run([], FakeApi([]), scraper=scraper) == 0
    scraper.assert_not_called()
    assert "Keine Angebote für deine Einkaufsliste gefunden." in capsys.readouterr().out


def test_dry_run_does_not_save_history(env):
    _run(["--dry-run"], FakeApi(["Milch"], _completed_kaffee()))
    assert not (env / "history.json").exists()


def test_history_saved_and_reused(env):
    _run([], FakeApi(["Milch"], _completed_kaffee()))
    data = json.loads((env / "history.json").read_text("utf-8"))
    assert len(data["items"]["kaffee"]["completed"]) == 3


def test_scraper_timeout_default_and_flag(env):
    scraper = MagicMock(return_value=SCRAPER_JSON)
    _run(["--matcher", "regex"], FakeApi(["Milch"]), scraper=scraper)
    assert scraper.call_args.kwargs["timeout"] == 45
    _run(["--matcher", "regex", "--timeout", "900"], FakeApi(["Milch"]), scraper=scraper)
    assert scraper.call_args.kwargs["timeout"] == 900


def test_unexpected_gemini_error_falls_back(env, capsys):
    with patch.object(sd, "gemini_match", side_effect=TypeError("weird")):
        rc = _run([], FakeApi(["🥛 Milch"]))
    assert rc == 0
    assert "(Abgleich ohne KI – Gemini nicht verfügbar)" in capsys.readouterr().out


def test_gemini_client_has_timeout(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = "{}"
    with patch("google.genai.Client", return_value=fake_client) as client:
        sd._gemini_text("p")
    assert client.call_args.kwargs["http_options"]["timeout"] == 20000


def test_gemini_call_disables_afc(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = "{}"
    with patch("google.genai.Client", return_value=fake_client):
        sd._gemini_text("p")
    config = fake_client.models.generate_content.call_args.kwargs["config"]
    assert config.automatic_function_calling.disable is True


def test_run_scraper_passes_deadline(tmp_path):
    done = subprocess.CompletedProcess([], 0, stdout=json.dumps(SCRAPER_JSON), stderr="")
    with patch("shopping_deals.subprocess.run", return_value=done) as run:
        sd.run_scraper(tmp_path, ["milch"], force=False, timeout=45, deadline=30)
    cmd = run.call_args.args[0]
    assert cmd[cmd.index("--deadline") + 1] == "30"


def test_run_scraper_timeout_raises_scraper_timeout(tmp_path):
    with patch("shopping_deals.subprocess.run", side_effect=subprocess.TimeoutExpired("x", 45)):
        with pytest.raises(sd.ScraperTimeout):
            sd.run_scraper(tmp_path, ["milch"], force=False)


def test_deadline_derived_from_timeout(env):
    scraper = MagicMock(return_value=SCRAPER_JSON)
    _run(["--matcher", "regex"], FakeApi(["Milch"]), scraper=scraper)
    assert scraper.call_args.kwargs["deadline"] == 30
    _run(["--matcher", "regex", "--timeout", "900"], FakeApi(["Milch"]), scraper=scraper)
    assert scraper.call_args.kwargs["deadline"] == 885


def test_timeout_retries_cache_only(env, capsys):
    scraper = MagicMock(side_effect=[sd.ScraperTimeout("slow"), dict(SCRAPER_JSON, skipped=["brot"])])
    rc = _run(["--matcher", "regex"], FakeApi(["🥛 Milch", "Brot"]), scraper=scraper)
    out = capsys.readouterr().out
    assert rc == 0
    assert scraper.call_args_list[1].kwargs["deadline"] == 0
    assert "🥛 Milch\n  LIDL  Vollmilch" in out
    assert "Noch nicht geladen (kommt beim nächsten Lauf): Brot" in out
    assert "Keine Angebote: Brot" not in out


def test_skipped_terms_shown(env, capsys):
    scraper = MagicMock(return_value=dict(SCRAPER_JSON, skipped=["äpfel rot"]))
    _run(["--matcher", "regex"], FakeApi(["Milch", "Äpfel, rot"]), scraper=scraper)
    assert "Noch nicht geladen (kommt beim nächsten Lauf): Äpfel, rot" in capsys.readouterr().out


def _gemini_config(monkeypatch, level=None):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    if level is None:
        monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    else:
        monkeypatch.setenv("GEMINI_THINKING_LEVEL", level)
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = "{}"
    with patch("google.genai.Client", return_value=fake_client):
        sd._gemini_text("p")
    return fake_client.models.generate_content.call_args.kwargs["config"]


def test_gemini_thinking_level_low_by_default(monkeypatch):
    # default thinking on gemini-3.x flash takes >60 s for this prompt (HA limit); "low" answers in ~3 s
    assert _gemini_config(monkeypatch).thinking_config.thinking_level.value.lower() == "low"


def test_gemini_thinking_level_from_env(monkeypatch):
    assert _gemini_config(monkeypatch, "high").thinking_config.thinking_level.value.lower() == "high"


def test_gemini_thinking_level_empty_disables_config(monkeypatch):
    # models without thinking support (e.g. gemini-2.0-flash-lite) reject thinking_config
    assert _gemini_config(monkeypatch, "").thinking_config is None
