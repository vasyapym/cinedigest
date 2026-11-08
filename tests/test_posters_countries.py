"""Posters-layer country metadata and recovered-year contracts; no render integration."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path

import pytest

from cinedigest import config, posters
from cinedigest.http import HttpError
from cinedigest.model import MSK, Screening

TODAY = date(2026, 11, 5)
FILM = posters.Film("морозко|1964", "Морозко", 1964)
FIXTURE = Path(__file__).parent / "fixtures" / "tmdb" / "movie_morozko.json"


class FakeHttp:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def get(self, url, *, params=None, headers=None, venue="", label=""):
        self.calls.append((url, dict(params or {}), label))
        answer = self.plan.get(url.rsplit("/3/", 1)[-1], {"results": []})
        if isinstance(answer, int):
            raise HttpError(f"HTTP {answer}", url=url, status=answer)
        return answer if isinstance(answer, str) else json.dumps(answer)

    def get_bytes(self, url, *, params=None, headers=None, venue="", label=""):
        self.calls.append((url, dict(params or {}), label))
        return b"POSTER"


def movie(tmdb_id=20932, country="Soviet Union"):
    return {
        "id": tmdb_id,
        "title": "Морозко",
        "release_date": "1964-01-01",
        "poster_path": "/m.jpg",
        "production_countries": [
            {"iso_3166_1": "SU", "name": country},
        ],
        "origin_country": ["SU"],
    }


def row(year=None):
    return Screening(
        venue="mirage",
        source_id="mirage-morozko",
        title="Морозко",
        start=datetime(2026, 11, 5, 18, tzinfo=MSK),
        extra={} if year is None else {"year": year},
    )


def cache_path(root):
    return root / config.DOCS_DIRNAME / config.POSTERS_FILENAME


def test_existing_details_fixture_and_id_pin():
    if not FIXTURE.is_file():
        pytest.skip("owner's TMDB fixture has not been downloaded")
    body = FIXTURE.read_text(encoding="utf-8")
    detail = json.loads(body)
    overrides = {FILM.key: {"tmdb_id": detail["id"]}}
    http = FakeHttp({f"movie/{detail['id']}": body})
    raw = posters.fetch(http, "tok", [FILM], overrides)
    entry = posters.parse(raw, [FILM], overrides, TODAY)[FILM.key]
    assert entry["country"] == ["Soviet Union"]
    assert detail["production_countries"][0]["iso_3166_1"] == "SU"
    assert entry["country_via"] == f"tmdb:{detail['id']}"
    assert entry["country_at"] == TODAY.isoformat()
    assert entry["via"] == "override"
    assert len(http.calls) == 1


def test_pin_uses_one_details_request_and_never_searches(tmp_path):
    path = tmp_path / config.DOCS_DIRNAME / config.POSTER_OVERRIDES_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({FILM.key: {"tmdb_id": 20932}}), encoding="utf-8")
    http = FakeHttp({"movie/20932": movie()})
    posters.resolve([row(1964)], http=http, out_dir=tmp_path, today=TODAY, token="tok")
    assert [call[0].rsplit("/3/", 1)[-1] for call in http.calls[:-1]] == [
        "movie/20932",
    ]
    entry = posters.load_cache(cache_path(tmp_path))[FILM.key]
    assert entry["country"] == ["Soviet Union"]
    assert entry["file"] == "m.jpg"


def test_hint_search_details_and_bytes_without_mutating_inputs(tmp_path):
    screening = row()
    hints = {posters.norm(screening.title): 1964}
    before = deepcopy((screening.to_json(), hints))
    http = FakeHttp({
        "search/movie": {"results": [movie()]},
        "movie/20932": movie(),
    })
    ready = posters.resolve(
        [screening], http=http, out_dir=tmp_path, today=TODAY,
        token="tok", year_hints=hints,
    )
    assert ready == {FILM.key: "posters/m.jpg"}
    assert http.calls[0][1]["year"] == 1964
    assert http.calls[1][0].endswith("/movie/20932")
    assert http.calls[1][2] == FILM.key + "@details"
    assert (screening.to_json(), hints) == before
    entry = posters.load_cache(cache_path(tmp_path))[FILM.key]
    assert entry["title"] == "Морозко" and entry["year"] == 1964
    assert entry["country"] == ["Soviet Union"]

    reused = FakeHttp({})
    posters.resolve(
        [screening], http=reused, out_dir=tmp_path, today=TODAY,
        token="tok", year_hints=hints,
    )
    assert reused.calls == []


def test_absent_hint_and_explicit_year_keep_existing_identity_rules():
    screening = row()
    assert posters.films([screening]) == posters.films([screening], None) == {}
    assert posters.films([row(1964)], {"морозко": 2000}) == {FILM.key: FILM}
    http = FakeHttp({})
    raw = posters.fetch(http, "tok", [FILM])
    assert [label for label, _ in raw] == [FILM.key, FILM.key + posters.ANY_SUFFIX]
    assert "year" in http.calls[0][1]
    assert "year" not in http.calls[1][1]


def test_old_format_loads_without_migration_or_rewriting(tmp_path):
    path = cache_path(tmp_path)
    path.parent.mkdir(parents=True)
    old = {
        FILM.key: {
            "title": FILM.title, "year": FILM.year, "tmdb_id": 20932,
            "poster_path": "/m.jpg", "resolved_at": TODAY.isoformat(),
            "via": "year",
        },
    }
    text = json.dumps({"films": old})
    path.write_text(text, encoding="utf-8")
    assert posters.load_cache(path) == old
    assert path.read_text(encoding="utf-8") == text
    assert posters.plan({FILM.key: FILM}, old, {}, TODAY) == []
    assert posters.country_evidence(old) == []


def test_country_fields_do_not_bypass_refresh_or_prune(tmp_path):
    entry = {
        "title": FILM.title, "year": FILM.year, "tmdb_id": 20932,
        "poster_path": "/m.jpg",
        "resolved_at": (TODAY - timedelta(days=config.TMDB_REFRESH_DAYS)).isoformat(),
        "country": ["Soviet Union"], "country_at": TODAY.isoformat(),
        "country_via": "tmdb:20932",
    }
    assert posters.plan({FILM.key: FILM}, {FILM.key: entry}, {}, TODAY) == [FILM]
    old = dict(
        entry,
        resolved_at=(TODAY - timedelta(days=config.TMDB_CACHE_MAX_AGE_DAYS + 1)).isoformat(),
    )
    posters.save_cache(cache_path(tmp_path), {FILM.key: old}, TODAY)
    assert posters.load_cache(cache_path(tmp_path)) == {}


def test_details_add_fields_without_touching_poster_or_byte_dates():
    entry = {
        "title": FILM.title, "year": FILM.year, "tmdb_id": 20932,
        "poster_path": "/m.jpg", "resolved_at": "2026-10-01",
        "file": "m.jpg", "file_downloaded_at": "2026-09-01",
    }
    before = deepcopy(entry)
    fields = posters.fetch_details(
        FakeHttp({"movie/20932": movie()}), "tok", {FILM.key: entry}, TODAY,
    )[FILM.key]
    assert entry == before
    combined = dict(entry, **fields)
    assert all(combined[key] == value for key, value in before.items())
    assert combined["country"] == ["Soviet Union"]


@pytest.mark.parametrize("answer", [
    429,
    "not JSON",
    {"id": 999, "production_countries": [{"name": "Russia"}]},
])
def test_failed_or_mismatched_details_do_not_fabricate_country(answer):
    fields = posters.fetch_details(
        FakeHttp({"movie/20932": answer}),
        "tok", {FILM.key: {"tmdb_id": 20932}}, TODAY,
    )
    assert fields == {}


def test_search_country_and_origin_country_are_not_evidence():
    search_movie = movie()
    parsed = posters.parse(
        [(FILM.key, json.dumps({"results": [search_movie]}))],
        [FILM], today=TODAY,
    )
    assert posters.country_evidence(parsed) == []
    http = FakeHttp({"movie/20932": {"id": 20932, "origin_country": ["RU"]}})
    fields = posters.fetch_details(http, "tok", parsed, TODAY)
    assert fields == {FILM.key: {}}


def test_identity_change_and_details_failure_drop_previous_country(tmp_path):
    old = {
        "title": FILM.title, "year": FILM.year, "tmdb_id": 20932,
        "poster_path": "/m.jpg",
        "resolved_at": (TODAY - timedelta(days=config.TMDB_REFRESH_DAYS)).isoformat(),
        "country": ["Soviet Union"], "country_via": "tmdb:20932",
    }
    posters.save_cache(cache_path(tmp_path), {FILM.key: old}, TODAY)
    http = FakeHttp({"search/movie": {"results": [movie(7)]}, "movie/7": 503})
    posters.resolve([row(1964)], http=http, out_dir=tmp_path, today=TODAY, token="tok")
    saved = posters.load_cache(cache_path(tmp_path))[FILM.key]
    assert saved["tmdb_id"] == 7
    assert "country" not in saved
    assert saved["file"] == "m.jpg"


def test_details_budget_and_failure_limit(monkeypatch):
    entries = {str(i): {"tmdb_id": i + 1} for i in range(5)}
    monkeypatch.setattr(config, "TMDB_MAX_LOOKUPS_PER_RUN", 2)
    http = FakeHttp({f"movie/{i}": movie(i) for i in range(1, 6)})
    assert len(posters.fetch_details(http, "tok", entries, TODAY)) == 2
    assert len(http.calls) == 2

    monkeypatch.setattr(config, "TMDB_MAX_LOOKUPS_PER_RUN", 150)
    monkeypatch.setattr(config, "TMDB_FAILURE_LIMIT", 2)
    failed = FakeHttp({f"movie/{i}": 429 for i in range(1, 6)})
    assert posters.fetch_details(failed, "tok", entries, TODAY) == {}
    assert len(failed.calls) == 2


def test_country_evidence_is_pure_preserves_names_and_provenance():
    entries = {
        "a": {
            "title": "Полное название фильма", "year": 1964,
            "tmdb_id": 20932, "country": ["Soviet Union"],
            "country_via": "tmdb:20932",
        },
        "b": {"title": "Без года", "year": None, "tmdb_id": 7, "country": "France"},
        "c": {"title": "Пусто", "country": []},
        "d": {"title": "Нет данных"},
        "e": {"title": "Пробел", "country": "  "},
        "f": {"title": "Пустой список", "country": [""]},
    }
    before = deepcopy(entries)
    evidence = posters.country_evidence(entries)
    assert evidence == [
        {"title": "Полное название фильма", "year": 1964,
         "country": ["Soviet Union"], "source": "tmdb:20932"},
        {"title": "Без года", "year": None, "country": "France", "source": "tmdb:7"},
    ]
    assert entries == before
    evidence[0]["country"].append("France")
    assert entries == before


def test_cache_publication_failure_preserves_previous_json(tmp_path, monkeypatch):
    path = cache_path(tmp_path)
    posters.save_cache(path, {}, TODAY)
    before = path.read_bytes()

    def fail_replace(*args):
        raise OSError("disk full")

    monkeypatch.setattr(posters.os, "replace", fail_replace)
    with pytest.raises(OSError):
        posters.save_cache(
            path, {FILM.key: {"resolved_at": TODAY.isoformat()}}, TODAY,
        )
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.part"))
