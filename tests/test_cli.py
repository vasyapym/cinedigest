"""CLI: main() с подставными площадками; полные и вырожденные прогоны, коды выхода, подкоманды."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from cinedigest import config, cli
from cinedigest.model import MSK, Screening


class FakeVenue:
    """Минимальная замена адаптера: ID/NAME/DAILY + сетевой/чистый распад."""

    def __init__(self, venue_id: str, items=None, *, fail: bool = False, daily: bool = True):
        self.ID = venue_id
        self.NAME = venue_id.upper()
        self.DAILY = daily
        self.fail = fail
        self.items = items if items is not None else []

    def fetch(self, http, days):
        if self.fail:
            raise RuntimeError("boom")
        return [("page1", '{"products": []}')]

    def parse(self, raw, days):
        return self.items

    def legit_empty(self, body):
        return body == '{"products": []}'


def _screening(title: str, *, venue: str = "domkino", hour: int = 19, day_offset: int = 0) -> Screening:
    start = datetime.now(MSK) + timedelta(days=day_offset)
    start = start.replace(hour=hour, minute=0, second=0, microsecond=0)
    return Screening(
        venue=venue,
        source_id=f"{venue}|{title}|{start.isoformat()}",
        title=title,
        start=start,
    )


@pytest.fixture(autouse=True)
def no_telegram_env(monkeypatch):
    monkeypatch.delenv(config.TELEGRAM_BOT_TOKEN_ENV, raising=False)
    monkeypatch.delenv(config.TELEGRAM_CHAT_ID_ENV, raising=False)
    monkeypatch.delenv(config.PAGE_URL_ENV, raising=False)


def test_run_success_writes_four_parseable_files(tmp_path):
    domkino = FakeVenue("domkino", [_screening("Сабрина"), _screening("Дневной", hour=14)])
    rodina = FakeVenue("rodina", daily=False)  # пусто, но это не «странное» место

    code = cli.main(["run", "--out", str(tmp_path)], venues=[domkino, rodina])

    assert code == 0
    docs = tmp_path / "docs"
    for name in ("index.html", "digest.txt", "screenings.json", "status.json"):
        assert (docs / name).is_file(), name
    html = (docs / "index.html").read_text(encoding="utf-8")
    assert "Кино вечером" in html
    assert "Сабрина" in html
    digest = (docs / "digest.txt").read_text(encoding="utf-8")
    assert "ИСТОЧНИКИ" in digest

    snapshot = json.loads((docs / "screenings.json").read_text(encoding="utf-8"))
    status_data = json.loads((docs / "status.json").read_text(encoding="utf-8"))
    assert snapshot["statuses"] == status_data
    from cinedigest.model import Snapshot

    rebuilt = Snapshot.from_json(snapshot)
    assert [s.title for s in rebuilt.screenings if s.venue == "domkino"] == ["Дневной", "Сабрина"]


def test_run_degraded_exits_two_when_any_venue_fails(tmp_path):
    ok_venue = FakeVenue("domkino", [_screening("Сабрина")])
    broken = FakeVenue("rodina", fail=True)

    code = cli.main(["run", "--out", str(tmp_path)], venues=[ok_venue, broken])

    assert code == 2
    snapshot = json.loads((tmp_path / "docs" / "screenings.json").read_text(encoding="utf-8"))
    by_venue = {st["venue"]: st for st in snapshot["statuses"]}
    assert by_venue["domkino"]["ok"] is True
    assert by_venue["rodina"]["ok"] is False
    assert "fetch failed" in by_venue["rodina"]["error"]
    # страница всё равно собрана с честным баннером
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "недоступен" in html


def test_run_does_not_crash_on_parse_error(tmp_path):
    broken = FakeVenue("domkino")
    broken.parse = lambda raw, days: (_ for _ in ()).throw(ValueError("мусор"))
    code = cli.main(["run", "--out", str(tmp_path)], venues=[broken])
    assert code == 2  # ошибка разбора — вырожденный прогон, не катастрофа


def test_run_crash_inside_pipeline_returns_one(tmp_path, monkeypatch):
    def broken_run(*args, **kwargs):
        raise RuntimeError("внезапно")

    monkeypatch.setattr(cli.pipeline, "run", broken_run)
    code = cli.main(["run", "--out", str(tmp_path)], venues=[FakeVenue("domkino")])
    assert code == 1


def test_run_only_filters_venues(tmp_path):
    first = FakeVenue("domkino", [_screening("Домкинский")])
    second = FakeVenue("rodina", daily=False)

    code = cli.main(["run", "--out", str(tmp_path), "--only", "domkino"], venues=[first, second])

    assert code == 0
    statuses = json.loads((tmp_path / "docs" / "status.json").read_text(encoding="utf-8"))
    assert [st["venue"] for st in statuses] == ["domkino"]
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "Домкинский" in html


def test_run_unknown_only_key_is_a_usage_error(tmp_path, capsys):
    venue = FakeVenue("domkino")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", "--out", str(tmp_path), "--only", "нет-такого"], venues=[venue])
    assert exit_info.value.code == 2
    assert "нет-такого" in capsys.readouterr().err


def test_run_with_date_limits_the_window_to_one_day(tmp_path):
    # --date ставит окно длиной 1: «сегодняшний» фейковый сеанс не попадает в снимок
    venue = FakeVenue("domkino", [_screening("Сегодняшний", hour=19, day_offset=0)])
    tomorrow = datetime.now(MSK) + timedelta(days=1)
    code = cli.main(["run", "--out", str(tmp_path), "--date", tomorrow.date().isoformat()], venues=[venue])
    assert code == 0
    snapshot = json.loads((tmp_path / "docs" / "screenings.json").read_text(encoding="utf-8"))
    assert snapshot["window_start"] == tomorrow.date().isoformat()
    assert snapshot["window_end"] == tomorrow.date().isoformat()
    assert [s["title"] for s in snapshot["screenings"]] == []


def test_run_with_days_extends_the_window(tmp_path):
    venue = FakeVenue("domkino", [_screening("+3 дня", hour=19, day_offset=3)])
    code = cli.main(["run", "--out", str(tmp_path), "--days", "4"], venues=[venue])
    assert code == 0
    snapshot = json.loads((tmp_path / "docs" / "screenings.json").read_text(encoding="utf-8"))
    titles = [s["title"] for s in snapshot["screenings"]]
    assert "+3 дня" in titles


def test_run_print_shows_the_telegram_body_without_sending(tmp_path, capsys):
    venue = FakeVenue("domkino", [_screening("Сабрина")])
    code = cli.main(["run", "--out", str(tmp_path), "--print"], venues=[venue])
    out = capsys.readouterr().out
    assert code == 0
    assert "СЕГОДНЯ ВЕЧЕРОМ" in out
    assert "Сабрина" in out


def test_run_without_print_dumps_nothing_to_stdout(tmp_path, capsys):
    venue = FakeVenue("domkino", [_screening("Сабрина")])
    cli.main(["run", "--out", str(tmp_path), "--no-telegram"], venues=[venue])
    out = capsys.readouterr().out
    assert "СЕГОДНЯ ВЕЧЕРОМ" not in out


def test_render_subcommand_rebuilds_from_saved_snapshot(tmp_path):
    # первый прогон создаёт снимок; потом страницу удаляем и пересобираем без сети
    venue = FakeVenue("domkino", [_screening("Сабрина")])
    assert cli.main(["run", "--out", str(tmp_path), "--no-telegram"], venues=[venue]) == 0
    index = tmp_path / "docs" / "index.html"
    html_before = index.read_text(encoding="utf-8")
    index.unlink()
    digest = tmp_path / "docs" / "digest.txt"
    digest_text_before = digest.read_text(encoding="utf-8")
    digest.unlink()

    code = cli.main(["render", "--out", str(tmp_path)], venues=[venue])

    assert code == 0
    assert index.is_file() and digest.is_file()
    assert index.read_text(encoding="utf-8") == html_before
    assert digest.read_text(encoding="utf-8") == digest_text_before


def test_render_subcommand_missing_snapshot_is_an_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["render", "--out", str(tmp_path)], venues=[])
    assert exit_info.value.code == 2
    error_text = capsys.readouterr().err
    assert "screenings.json" in error_text


def test_render_subcommand_explicit_snapshot_path(tmp_path):
    venue = FakeVenue("domkino", [_screening("Из снимка")])
    steps = cli.main(["run", "--out", str(tmp_path), "--no-telegram"], venues=[venue])
    assert steps == 0
    saved = tmp_path / "saved" / "screenings.json"
    saved.parent.mkdir()
    (tmp_path / "docs" / "screenings.json").rename(saved)
    code = cli.main(["render", "--out", str(tmp_path), "--snapshot", str(saved)], venues=[])
    assert code == 0
    assert "Из снимка" in (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")


def test_fetch_saves_raw_bodies_without_rendering(tmp_path):
    venue = FakeVenue("domkino", [])
    code = cli.main(["fetch", "--venue", "domkino", "--save", str(tmp_path)], venues=[venue])
    assert code == 0
    saved = tmp_path / "domkino" / "page1"
    assert saved.is_file()
    assert saved.read_text(encoding="utf-8") == '{"products": []}'
    assert not (tmp_path / "docs").exists()  # fetch никогда не рисует


def test_fetch_unknown_venue_is_an_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["fetch", "--venue", "нет", "--save", str(tmp_path)], venues=[])
    assert exit_info.value.code == 2
    assert "нет" in capsys.readouterr().err
