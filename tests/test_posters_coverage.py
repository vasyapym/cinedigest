"""Stage C: invalid years, conservative qualifier retries, yearless lookup admission."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import json

import pytest

from cinedigest import config, posters
from cinedigest.http import HttpError
from cinedigest.model import MSK, Screening
from cinedigest.venues import poravkino

TODAY = date(2026, 11, 8)


class FakeHttp:
    """Query-aware, offline-only responses; unexpected endpoints fail the test."""

    def __init__(self, searches=None, details=None):
        self.searches = searches or {}
        self.details = details or {}
        self.calls = []

    def get(self, url, *, params=None, headers=None, venue="", label=""):
        params = dict(params or {})
        self.calls.append((url, params, label))
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/search/movie"):
            answer = self.searches.get((params["query"], params.get("year")), [])
            if isinstance(answer, int):
                raise HttpError(
                    f"HTTP {answer}", url=url, status=answer,
                )
            return json.dumps({"results": answer})
        tmdb_id = int(url.rsplit("/", 1)[-1])
        assert tmdb_id in self.details, f"Unexpected details request: {url}"
        return json.dumps(self.details[tmdb_id])

    def get_bytes(self, url, *, params=None, headers=None, venue="", label=""):
        self.calls.append((url, dict(params or {}), label))
        assert url.endswith("/m.jpg")
        return b"OFFLINE POSTER"


def row(title="Одиссея", year=None, source_id="one"):
    return Screening(
        venue="mirage",
        source_id=source_id,
        title=title,
        start=datetime(2026, 11, 8, 18, tzinfo=MSK),
        extra={} if year is None else {"year": year},
    )


def movie(title="Одиссея", year=2026, tmdb_id=7):
    return {
        "id": tmdb_id,
        "title": title,
        "original_title": title,
        "release_date": f"{year}-01-01",
        "poster_path": "/m.jpg",
        # Deliberately misleading: search must never supply country evidence.
        "production_countries": [{"name": "SEARCH MUST NOT WIN"}],
    }


def entry_path(root):
    return root / config.DOCS_DIRNAME / config.POSTERS_FILENAME


def searches(http):
    return [call for call in http.calls if call[0].endswith("/search/movie")]


@pytest.mark.parametrize(
    "value",
    [0, "0", "0000", -1, "-2026", 1899, "1899", 2100, "2100",
     False, True, 2026.5, "2026.5"],
)
def test_invalid_year_is_absent_at_key_boundary(value):
    assert posters.film_year(value) is None
    assert posters.film_key("Битва моторов", value) is None
    wanted = posters.films([row("Битва моторов", value)])
    assert list(wanted) == ["битва моторов|any"]
    assert next(iter(wanted.values())).year is None
    assert not any(key.endswith("|0") for key in wanted)


@pytest.mark.parametrize("value", [0, "0", 1899, "1899", 2100])
def test_poravkino_fixture_row_invalid_year_is_absent(value):
    fixture_row = {
        "year": value,
        "country": "Россия",
        "duration": 90,
        "name_secondary": "Original",
    }
    before = deepcopy(fixture_row)
    extra = poravkino._extra(fixture_row)
    assert extra.get("year") is None
    assert extra["country"] == "Россия"
    assert extra["duration_min"] == 90
    assert fixture_row == before


@pytest.mark.parametrize("value", [1900, "1964", "2024–2025", 2099])
def test_valid_year_forms_remain_supported(value):
    assert posters.film_year(value) in {1900, 1964, 2024, 2099}


def test_prune_removes_existing_zero_year_poison():
    common = {"resolved_at": TODAY.isoformat(), "poster_path": None}
    entries = {
        "битва моторов|0": dict(common, year=0),
        "любовь моя|1899": dict(common, year=1899),
        "одиссея|any": dict(common, year=None),
        "морозко|1964": dict(common, year=1964),
    }
    assert set(posters.prune(entries, TODAY)) == {
        "одиссея|any", "морозко|1964",
    }


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Фьорд (версия с субтитрами)", "Фьорд"),
        ("Фьорд (с субтитрами)", "Фьорд"),
        ("Фьорд (субтитры)", "Фьорд"),
        ("Человек-слон. АртПоказ", "Человек-слон"),
        ("Фьорд — версия с субтитрами", "Фьорд"),
        ("Фьорд с субтитрами", "Фьорд"),
        ("Фьорд (субтитры). АртПоказ", "Фьорд"),
        ("Оно (2017)", None),
        ("Любовь (Love)", None),
        ("АртПоказ", None),
        ("Версия", None),
    ],
)
def test_stripped_title_policy(title, expected):
    assert posters.stripped_title(title) == expected


@pytest.mark.parametrize(
    ("title", "clean", "year"),
    [
        ("Фьорд (версия с субтитрами)", "Фьорд", 2026),
        ("Человек-слон. АртПоказ", "Человек-слон", 1980),
    ],
)
def test_primary_miss_stripped_hit(title, clean, year):
    film = next(iter(posters.films([row(title, year)]).values()))
    http = FakeHttp({(clean, None): [movie(clean, year)]})
    raw = posters.fetch(http, "tok", [film])
    entry = posters.parse(raw, [film], today=TODAY)[film.key]
    assert entry["tmdb_id"] == 7
    assert entry["via"] == "stripped"
    assert entry["retry_query"] == clean
    assert entry["title"] == title
    assert entry["year"] == year
    assert "country" not in entry
    assert [(call[1]["query"], call[1].get("year")) for call in searches(http)] == [
        (title, year), (clean, None),
    ]


def test_qualifier_both_miss_is_recorded_and_not_immediately_retried():
    film = next(iter(posters.films([
        row("Фьорд (версия с субтитрами)", 2026),
    ]).values()))
    http = FakeHttp()
    raw = posters.fetch(http, "tok", [film])
    entry = posters.parse(raw, [film], today=TODAY)[film.key]
    assert entry["via"] == "miss"
    assert entry["tmdb_id"] is None
    assert entry["retry_query"] == "Фьорд"
    assert len(searches(http)) == 2
    assert posters.plan({film.key: film}, {film.key: entry}, {}, TODAY) == []


def test_old_qualifier_miss_gets_one_immediate_upgrade():
    film = next(iter(posters.films([
        row("Фьорд (версия с субтитрами)", 2026),
    ]).values()))
    old = {
        "via": "miss", "poster_path": None,
        "resolved_at": TODAY.isoformat(),
    }
    assert posters.plan({film.key: film}, {film.key: old}, {}, TODAY) == [film]
    upgraded = dict(old, retry_query="Фьорд")
    assert posters.plan(
        {film.key: film}, {film.key: upgraded}, {}, TODAY,
    ) == []


@pytest.mark.parametrize(
    "candidate",
    [
        movie("Совсем другой фильм", 2026),
        movie("Фьорд", 2024),
        movie("Фьорд", 2028),
        movie("Фьорд", 2026, tmdb_id=0),
    ],
)
def test_stripped_retry_collision_guard(candidate):
    film = next(iter(posters.films([
        row("Фьорд (версия с субтитрами)", 2026),
    ]).values()))
    http = FakeHttp({("Фьорд", None): [candidate]})
    entry = posters.parse(
        posters.fetch(http, "tok", [film]), [film], today=TODAY,
    )[film.key]
    assert entry["via"] == "miss"
    assert entry["tmdb_id"] is None


@pytest.mark.parametrize("year", [2025, 2027])
def test_stripped_retry_preserves_one_year_tolerance(year):
    film = next(iter(posters.films([
        row("Фьорд (субтитры)", 2026),
    ]).values()))
    http = FakeHttp({("Фьорд", None): [movie("Фьорд", year)]})
    entry = posters.parse(
        posters.fetch(http, "tok", [film]), [film], today=TODAY,
    )[film.key]
    assert entry["tmdb_id"] == 7


def test_nonempty_but_unusable_primary_gets_stripped_retry():
    title = "Фьорд (субтитры)"
    film = next(iter(posters.films([row(title, 2026)]).values()))
    http = FakeHttp({
        (title, 2026): [movie(title, 2020)],
        ("Фьорд", None): [movie("Фьорд")],
    })
    entry = posters.parse(
        posters.fetch(http, "tok", [film]), [film], today=TODAY,
    )[film.key]
    assert entry["via"] == "stripped"
    assert len(searches(http)) == 2


def test_successful_primary_never_gets_stripped_retry():
    title = "Фьорд (субтитры)"
    film = next(iter(posters.films([row(title, 2026)]).values()))
    http = FakeHttp({(title, 2026): [movie(title)]})
    entry = posters.parse(
        posters.fetch(http, "tok", [film]), [film], today=TODAY,
    )[film.key]
    assert entry["via"] == "year"
    assert "retry_query" not in entry
    assert len(searches(http)) == 1


def test_existing_dated_any_retry_still_works():
    film = posters.Film("морозко|1964", "Морозко", 1964)
    http = FakeHttp({("Морозко", None): [movie("Морозко", 1965)]})
    entry = posters.parse(
        posters.fetch(http, "tok", [film]), [film], today=TODAY,
    )[film.key]
    assert entry["via"] == "any"
    assert len(searches(http)) == 2
    assert "year" not in searches(http)[1][1]


def test_yearless_single_candidate_resolves_details_and_local_file(tmp_path):
    screening = row()
    before = deepcopy(screening)
    details = dict(
        movie(),
        production_countries=[{"name": "DETAILS COUNTRY"}],
    )
    http = FakeHttp(
        {("Одиссея", None): [movie()]},
        {7: details},
    )
    ready = posters.resolve(
        [screening], http=http, out_dir=tmp_path, today=TODAY, token="tok",
    )
    assert ready == {"одиссея|any": "posters/m.jpg"}
    assert (
        tmp_path / config.DOCS_DIRNAME / config.POSTERS_DIRNAME / "m.jpg"
    ).read_bytes() == b"OFFLINE POSTER"
    assert screening == before
    assert "year" not in screening.extra
    assert len(searches(http)) == 1
    assert "year" not in searches(http)[0][1]

    entry = posters.load_cache(entry_path(tmp_path))["одиссея|any"]
    assert entry["year"] is None
    assert entry["via"] == "yearless"
    assert entry["country"] == ["DETAILS COUNTRY"]
    assert entry["country_via"] == "tmdb:7"
    assert posters.identity_evidence({"одиссея|any": entry}) == []
    assert posters.cached_urls(
        [screening], tmp_path / config.DOCS_DIRNAME, TODAY,
    ) == ready

    reused = FakeHttp()
    assert posters.resolve(
        [screening], http=reused, out_dir=tmp_path, today=TODAY, token="tok",
    ) == ready
    assert reused.calls == []


@pytest.mark.parametrize(
    "candidates",
    [
        [],
        [movie(), movie("Другая Одиссея", tmdb_id=8)],
        [movie(), movie("Неизвестный", tmdb_id=0)],
        [movie(tmdb_id=0)],
        [movie(tmdb_id=True)],
    ],
)
def test_yearless_zero_multi_or_invalid_candidate_is_honest_miss(
    tmp_path, candidates,
):
    http = FakeHttp({("Одиссея", None): candidates})
    assert posters.resolve(
        [row()], http=http, out_dir=tmp_path, today=TODAY, token="tok",
    ) == {}
    entry = posters.load_cache(entry_path(tmp_path))["одиссея|any"]
    assert entry["via"] == "miss"
    assert entry["year"] is None
    assert entry["tmdb_id"] is None
    assert len(http.calls) == 1
    assert "year" not in http.calls[0][1]


def test_yearless_qualifier_retry_still_requires_single_exact_title():
    film = next(iter(posters.films([row("Фьорд (субтитры)")]).values()))
    for candidates, expected in [
        ([movie("Фьорд")], 7),
        ([movie("Другое название")], None),
        ([movie("Фьорд"), movie("Фьорд", 2025, tmdb_id=8)], None),
    ]:
        http = FakeHttp({("Фьорд", None): candidates})
        entry = posters.parse(
            posters.fetch(http, "tok", [film]), [film], today=TODAY,
        )[film.key]
        assert entry["tmdb_id"] == expected
        assert len(searches(http)) == 2
        assert all("year" not in call[1] for call in searches(http))


def test_dated_sibling_prevents_yearless_identity_regardless_of_row_order():
    missing = row()
    dated = row(year=2026, source_id="dated")
    before = deepcopy((missing, dated))
    for rows in ([missing, dated], [dated, missing]):
        wanted = posters.films(iter(rows))
        assert list(wanted) == ["одиссея|2026"]
        assert wanted["одиссея|2026"].year == 2026
    assert (missing, dated) == before


def test_ambiguous_dated_siblings_do_not_create_third_yearless_identity():
    wanted = posters.films([
        row(), row(year=1968, source_id="old"),
        row(year=2026, source_id="new"),
    ])
    assert set(wanted) == {"одиссея|1968", "одиссея|2026"}


def test_later_hint_retires_yearless_entry_and_revalidates_identity(tmp_path):
    screening = row()
    first = FakeHttp(
        {("Одиссея", None): [movie()]},
        {7: dict(movie(), production_countries=[])},
    )
    posters.resolve(
        [screening], http=first, out_dir=tmp_path, today=TODAY, token="tok",
    )
    hints = {"одиссея": 2026}
    before = deepcopy((screening, hints))
    second = FakeHttp(
        {("Одиссея", 2026): [movie()]},
        {7: dict(movie(), production_countries=[])},
    )
    ready = posters.resolve(
        [screening], http=second, out_dir=tmp_path, today=TODAY,
        token="tok", year_hints=hints,
    )
    assert ready == {"одиссея|2026": "posters/m.jpg"}
    entries = posters.load_cache(entry_path(tmp_path))
    assert set(entries) == {"одиссея|2026"}
    assert searches(second)[0][1]["year"] == 2026
    assert (screening, hints) == before


def test_later_hint_does_not_blindly_promote_wrong_yearless_identity(tmp_path):
    screening = row()
    first = FakeHttp(
        {("Одиссея", None): [movie(year=1968)]},
        {7: dict(movie(year=1968), production_countries=[])},
    )
    posters.resolve(
        [screening], http=first, out_dir=tmp_path, today=TODAY, token="tok",
    )
    second = FakeHttp({
        ("Одиссея", 2026): [movie(year=1968)],
    })
    assert posters.resolve(
        [screening], http=second, out_dir=tmp_path, today=TODAY,
        token="tok", year_hints={"одиссея": 2026},
    ) == {}
    entries = posters.load_cache(entry_path(tmp_path))
    assert set(entries) == {"одиссея|2026"}
    assert entries["одиссея|2026"]["tmdb_id"] is None


def test_hint_retirement_also_runs_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv(config.TMDB_READ_TOKEN_ENV, raising=False)
    posters.save_cache(
        entry_path(tmp_path),
        {
            "одиссея|any": {
                "title": "Одиссея", "year": None,
                "tmdb_id": 7, "poster_path": "/m.jpg",
                "resolved_at": TODAY.isoformat(), "via": "yearless",
            },
        },
        TODAY,
    )
    http = FakeHttp()
    assert posters.resolve(
        [row()], http=http, out_dir=tmp_path, today=TODAY,
        year_hints={"одиссея": 2026},
    ) == {}
    assert posters.load_cache(entry_path(tmp_path)) == {}
    assert http.calls == []


def test_yearless_override_key_roundtrip(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps({"Одиссея|any": None}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert posters.load_overrides(path) == {"одиссея|any": None}


def test_lookup_budget_counts_films_and_allows_only_one_extra_request(monkeypatch):
    monkeypatch.setattr(config, "TMDB_MAX_LOOKUPS_PER_RUN", 2)
    wanted = posters.films([
        row("Фьорд (субтитры)", 2026, "qualified"),
        row("Одиссея", source_id="yearless"),
        row("Третий", 2026, "over-budget"),
    ])
    due = posters.plan(wanted, {}, {}, TODAY)
    http = FakeHttp()
    posters.fetch(http, "tok", due)
    assert len(due) == 2
    assert len(searches(http)) == 3
    assert [call[1]["query"] for call in searches(http)] == [
        "Фьорд (субтитры)", "Фьорд", "Одиссея",
    ]


def test_qualifier_retry_http_failure_uses_existing_failure_limit(monkeypatch):
    monkeypatch.setattr(config, "TMDB_FAILURE_LIMIT", 1)
    films = list(posters.films([
        row("Фьорд (субтитры)", 2026, "first"),
        row("Второй", 2026, "second"),
    ]).values())
    http = FakeHttp({("Фьорд", None): 429})
    raw = posters.fetch(http, "tok", films)
    assert len(searches(http)) == 2
    assert [label for label, _ in raw] == [films[0].key]
