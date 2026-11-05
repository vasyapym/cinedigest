"""Ленфильм: kinokassa-фид (механика АВроры на cinema 2387), маркер пустого окна и дедуп."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path

import pytest

from cinedigest import config, pipeline
from cinedigest.http import HttpError
from cinedigest.model import MSK
from cinedigest.venues import lenfilm

FIXTURES = Path(__file__).parent / "fixtures" / "lenfilm"
APP_BODY = (FIXTURES / "feed-1-app.json").read_text(encoding="utf-8")
INFO_BODY = (FIXTURES / "feed-3-playbill-info.json").read_text(encoding="utf-8")

# Окно внутри зафиксированных seance_dates (плеи feed-4/6/7 есть на эти дни).
COVERED_DAYS = [date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 7)]
# Порядок сеансов в плеях — как в файле, не по времени.
DAY_05_ROWS = [
    ("6adf39843f0000bc009b33c5", "Барашек Шон и чудище лохматое", (11, 15), "1", (250, 250), 192, 25760),
    ("6adde5184000005000f8b99a", "Плетёный муж", (13, 0), "1", (300, 300), 149, 25872),
    ("6ae496683e00004200ebc7c1", "Навар", (19, 0), "1", (450, 450), 147, 24668),
    ("6ae48fd53e0000be00ebbaa6", "Лето в Бадене", (15, 20), "1", (400, 400), 192, 26051),
]


def _fixture(filename: str) -> str:
    return (FIXTURES / filename).read_text(encoding="utf-8")


def _day_bodies() -> list[tuple[str, str]]:
    """(label, body) каждого дневного плея, label = дата из имени файла."""
    raw: list[tuple[str, str]] = []
    for path in sorted(FIXTURES.glob("feed-*-playbill-*.json")):
        match = re.search(r"playbill-(\d{4}-\d{2}-\d{2})", path.name)
        if match:  # feed-3-playbill-info.json — не дневной файл
            raw.append((match.group(1), path.read_text(encoding="utf-8")))
    return raw


def _seance_count(body: str) -> int:
    data = json.loads(body)
    return sum(len(release.get("seances", [])) for release in data["releases"])


class FakeHttp:
    """Мини-замена http.Http: отдаёт заготовленные тела по меткам и запоминает запросы."""

    def __init__(self, bodies: dict[str, str]):
        self.bodies = bodies
        self.calls: list[tuple[str, str, str, dict | None, dict | None]] = []
        self.request_count = 0

    def get(self, url, params=None, headers=None, venue="", label=""):
        self.calls.append((venue, label, url, params, headers))
        self.request_count += 1
        return self.bodies[label]


class FlakyBootstrapHttp(FakeHttp):
    """Загрузка приложения: первая попытка — HTTP 400 «Invalid headers», далее — тело.
    Каждый запрос записывается ДО решения об ошибке, чтобы обе попытки были видны."""

    def __init__(self, bodies: dict[str, str]):
        super().__init__(bodies)
        self.app_attempts = 0

    def get(self, url, params=None, headers=None, venue="", label=""):
        self.calls.append((venue, label, url, params, dict(headers or {})))
        self.request_count += 1
        if label == lenfilm.APP_LABEL and headers:
            self.app_attempts += 1
            if headers.get("X-Platform") == "widget":
                raise HttpError("HTTP 400", url=url, status=400)
        return self.bodies[label]


def test_app_credentials_pin_token_title_and_time_zone():
    token, title, time_zone = lenfilm.app_credentials(json.loads(APP_BODY))

    assert token == "SoJJpqee6emqZn6cGSK8sbHFxt5V7Nvn"
    assert title == "Ленфильм, Санкт-Петербург"
    assert time_zone == 3  # в замороженном аккаунте time_zone сидит внутри cinemas[0]


def test_bootstrap_without_a_token_fails_loudly():
    http = FakeHttp({lenfilm.APP_LABEL: json.dumps({"title": "Ленфильм"})})

    with pytest.raises(ValueError, match="carries no 'token'"):
        lenfilm.fetch(http, COVERED_DAYS)


def test_seance_dates_are_read_under_their_real_key():
    info = json.loads(INFO_BODY)
    assert isinstance(info["calendar"]["seance_dates"], list)  # путь calendar.seance_dates

    dates = lenfilm.seance_dates(info)

    assert len(dates) == 21
    assert dates[0] == date(2026, 11, 5)
    assert dates[-1] == date(2026, 11, 30)
    assert date(2026, 11, 13) not in dates  # дыра фида: 13 ноября
    assert all(date(2026, 11, day) not in dates for day in (16, 17, 18))  # и 16–18
    assert date(2026, 11, 23) not in dates  # 23-я тоже отсутствует (факт файла)
    assert date(2026, 11, 14) in dates and date(2026, 11, 19) in dates


def test_day_playbill_2026_11_05_yields_pinned_rows():
    raw = [
        (lenfilm.APP_LABEL, APP_BODY),
        (lenfilm.INFO_LABEL, INFO_BODY),
        ("2026-11-05", _fixture("feed-4-playbill-2026-11-05.json")),
    ]

    items = lenfilm.parse(raw, COVERED_DAYS)

    assert len(items) == 4
    assert [s.source_id for s in items] == [row[0] for row in DAY_05_ROWS]
    for screening, (source_id, title, (hour, minute), hall, (low, high), free, release) in zip(items, DAY_05_ROWS):
        assert screening.title == title
        assert screening.start == datetime(2026, 11, 5, hour, minute, tzinfo=MSK)
        assert screening.hall == hall
        assert (screening.price_min, screening.price_max) == (low, high)
        assert screening.extra["free_places"] == free
        assert screening.extra["release_id"] == release
        assert screening.venue == "lenfilm"
        assert screening.url == config.LENFILM_SITE_URL
        assert screening.source_url == f"{config.KINOKASSA_API_URL}/api/v2/release/playbill?cinema_id=2387&date=2026-11-05"
    assert items[2].tags == ()  # «Навар»: только 2D → без бейджей
    assert items[1].tags == ("SUB",)  # «Плетёный муж»: формат SUB → бейдж
    assert all(s.language is None for s in items)  # в фиде дня 5 нет сеансовых/релизных языка


def test_window_outside_seance_dates_parses_to_nothing_and_the_marker_blesses_it():
    late_october = [date(2026, 10, 1) + timedelta(days=offset) for offset in range(7)]
    raw = [
        (lenfilm.APP_LABEL, APP_BODY),
        (lenfilm.INFO_LABEL, INFO_BODY),
        (lenfilm.EMPTY_LABEL, lenfilm.EMPTY_WINDOW_BODY),
    ]

    assert lenfilm.parse(raw, late_october) == []  # даты фида не попадают в окно
    assert lenfilm.legit_empty(lenfilm.EMPTY_WINDOW_BODY) is True
    assert lenfilm.legit_empty(INFO_BODY) is False  # сам info-фид не благословляет окно
    assert lenfilm.legit_empty('{"lenfilm_window_empty": false}') is False
    assert lenfilm.legit_empty("[]") is False
    assert lenfilm.legit_empty("начинка") is False


def test_parse_skips_app_info_and_marker_bodies_without_a_marker():
    # реды в прежнем стиле (без маркера): parse должен молча вернуть [] и не упасть
    raw = [(lenfilm.APP_LABEL, APP_BODY), (lenfilm.INFO_LABEL, INFO_BODY)]
    late_october = [date(2026, 10, 1) + timedelta(days=offset) for offset in range(7)]

    assert lenfilm.parse(raw, late_october) == []
    # info-фид без списка дат — не «легитимно пусто», а структурный сбой
    with pytest.raises(ValueError, match="calendar.seance_dates"):
        lenfilm.seance_dates({"cinemas": []})


def test_fetch_serves_app_info_and_only_scheduled_day_bodies():
    bodies = {
        lenfilm.APP_LABEL: APP_BODY,
        lenfilm.INFO_LABEL: INFO_BODY,
        "2026-11-05": _fixture("feed-4-playbill-2026-11-05.json"),
        "2026-11-06": _fixture("feed-6-playbill-2026-11-06.json"),
        "2026-11-07": _fixture("feed-7-playbill-2026-11-07.json"),
    }
    http = FakeHttp(bodies)

    raw = lenfilm.fetch(http, COVERED_DAYS)

    assert [label for label, _body in raw] == [
        "app", "info", "2026-11-05", "2026-11-06", "2026-11-07",
    ]
    assert len(http.calls) == 5  # нет запросов и меток для никем не покрытых дней (дыр нет)
    assert raw[0] == ("app", APP_BODY)  # архивируются настоящие тела ответов
    assert raw[1] == ("info", INFO_BODY)
    # загрузка: без токена, платформенная «шапка»_по брифу
    assert http.calls[0][2] == f"{config.KINOKASSA_API_URL}/api/v2/app"
    assert http.calls[0][3] == {"with_cities": "true", "cinema_id": config.LENFILM_CINEMA_ID}
    assert http.calls[0][4] == {"X-Platform": "widget"}
    # ниже идёт app-токен
    assert http.calls[1][4] == {"X-Application-Token": "SoJJpqee6emqZn6cGSK8sbHFxt5V7Nvn", "X-Platform": "widget"}
    assert http.calls[2][3] == {"cinema_id": 2387, "date": "2026-11-05"}

    items = lenfilm.parse(raw, COVERED_DAYS)
    assert len(items) == 15  # 4 + 5 + 6 сеансов по файлам дней, пересечений id между датами нет


def test_bootstrap_400_is_retried_once_with_the_verified_widget_casing():
    bodies = {
        lenfilm.APP_LABEL: APP_BODY,
        lenfilm.INFO_LABEL: INFO_BODY,
        "2026-11-05": _fixture("feed-4-playbill-2026-11-05.json"),
    }
    http = FlakyBootstrapHttp(bodies)

    raw = lenfilm.fetch(http, [date(2026, 11, 5)])

    assert http.app_attempts == 2
    assert http.calls[0][4]["X-Platform"] == "widget"  # первая попытка — как обычно
    assert http.calls[1][4]["X-Platform"] == "WIDGET"  # повтор на HTTP 400 — проверенный кейс
    assert [label for label, _body in raw] == ["app", "info", "2026-11-05"]


def test_fetch_marks_an_uncovered_window_with_the_empty_marker():
    late_october = [date(2026, 10, 1) + timedelta(days=offset) for offset in range(7)]
    http = FakeHttp({lenfilm.APP_LABEL: APP_BODY, lenfilm.INFO_LABEL: INFO_BODY})

    raw = lenfilm.fetch(http, late_october)

    assert [label for label, _body in raw] == ["app", "info", "empty-window"]
    assert raw[-1][1] == '{"lenfilm_window_empty": true}'
    assert len(http.calls) == 2  # плеи дня не запрашиваются: окна seance_dates не дотягиваются
    assert lenfilm.parse(raw, late_october) == []
    assert lenfilm.legit_empty(raw[-1][1]) is True


def test_pipeline_blesses_the_empty_window_marker_and_the_covered_window():
    now = datetime(2026, 11, 1, 9, 0, tzinfo=MSK)

    uncovered = [date(2026, 10, 1) + timedelta(days=offset) for offset in range(7)]
    http = FakeHttp({lenfilm.APP_LABEL: APP_BODY, lenfilm.INFO_LABEL: INFO_BODY})
    status, items = pipeline.run_venue(lenfilm, http, uncovered, clock=lambda: now)
    assert status.ok is True
    assert status.count == 0
    assert status.suspicious is False  # маркер empty-window благословил окно
    assert items == []

    covered_bodies = {
        lenfilm.APP_LABEL: APP_BODY,
        lenfilm.INFO_LABEL: INFO_BODY,
        "2026-11-05": _fixture("feed-4-playbill-2026-11-05.json"),
        "2026-11-06": _fixture("feed-6-playbill-2026-11-06.json"),
        "2026-11-07": _fixture("feed-7-playbill-2026-11-07.json"),
    }
    status, items = pipeline.run_venue(lenfilm, FakeHttp(covered_bodies), COVERED_DAYS, clock=lambda: now)
    assert status.ok is True
    assert status.count == 15
    assert status.suspicious is False


def test_dedupe_across_all_saved_day_files_and_zero_intersection():
    raw = _day_bodies()
    labels = [label for label, _body in raw]
    unique_dates = sorted({date.fromisoformat(label) for label in labels})
    entries = sum(_seance_count(body) for _label, body in raw)

    assert entries == 62  # атрибированные ноты: сечь по всем файлам, дубли только в паре feed-4/5

    items = lenfilm.parse(raw, unique_dates)
    ids = [s.source_id for s in items]
    assert len(set(ids)) == 58        # 62 записи − 4 дубля идентичных feed-4/feed-5
    assert len(items) == 58           # всё свелось к дедупу по source_id
    assert len(ids) == len(set(ids))  # повторов не осталось вообще

    per_date: dict[str, set[str]] = {}
    for label in labels:
        bodies = [body for day_label, body in raw if day_label == label]
        parsed_ids = {s.source_id for s in lenfilm.parse([(label, b) for b in bodies], unique_dates)}
        file_ids = {str(seance["id"]) for body in bodies for rel in json.loads(body)["releases"] for seance in rel.get("seances", [])}
        assert parsed_ids == file_ids  # разбор каждой даты === файлам этой даты
        per_date[label] = parsed_ids

    every = [sid for date_ids in per_date.values() for sid in date_ids]
    assert len(every) == 58
    assert len(set(every)) == 58  # пересечения id между разными датами: 0 (как наблюдается)
    combined = [len(per_date[a] & per_date[b]) for a, b in combinations(sorted(per_date), 2)]
    assert max(combined) == 0
