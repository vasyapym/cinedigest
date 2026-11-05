"""Постеры TMDB: ключи фильмов, выбор кандидата, план запросов, кэш и срок хранения, оверрайды, рендер URL."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from cinedigest import config, posters
from cinedigest.http import HttpError
from cinedigest.model import MSK, Screening

FIXTURES = Path(__file__).parent / "fixtures" / "tmdb"
TODAY = date(2026, 11, 5)
MOROZKO = posters.Film("морозко|1964", "Морозко", 1964)
# Интеграторская оговорка: три теста ниже читают РЕАЛЬНЫЕ ответы TMDB из tests/fixtures/tmdb/.
# Они пропускаются, пока фикстуры не скачаны (нужен токен владельца — README «Постеры (TMDB)»).
_FIXTURE_NAMES = ("search_morozko_1964.json", "search_morozko_any.json", "search_empty.json", "movie_morozko.json")
_NEED_FIXTURES = pytest.mark.skipif(
    any(not (FIXTURES / name).is_file() for name in _FIXTURE_NAMES),
    reason="реальные тела TMDB будут скачаны, когда появится TMDB_READ_TOKEN владельца",
)


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _screening(title, year=None, venue="mirage", original_title=None, hour=18):
    extra = {}
    if year is not None:
        extra["year"] = year
    if original_title:
        extra["original_title"] = original_title
    return Screening(venue=venue, source_id=f"{venue}-{title}-{hour}", title=title,
                     start=datetime(2026, 11, 5, hour, 0, tzinfo=MSK), extra=extra)


class FakeHttp:
    """Answers by URL path; a status in the plan raises HttpError like the real client."""

    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def get(self, url, *, params=None, headers=None, venue="", label=""):
        self.calls.append((url, dict(params or {}), label))
        answer = self.plan.get(url.rsplit("/3/", 1)[-1] + ("?any" if params and "year" not in params else ""))
        if answer is None:
            answer = self.plan.get(url.rsplit("/3/", 1)[-1])
        if isinstance(answer, int):
            raise HttpError(f"HTTP {answer}", url=url, status=answer)
        return answer if answer is not None else json.dumps({"results": []})


# ---- keys -----------------------------------------------------------------------------
def test_norm_drops_punctuation_case_and_yo():
    assert posters.norm("Сумерки. Saga. Затмение") == "сумерки saga затмение"
    assert posters.norm("Плётённый  муж!") == "плетенный муж"


def test_film_key_requires_title_and_year():
    assert posters.film_key("Морозко", 1964) == "морозко|1964"
    assert posters.film_key("Морозко", None) is None
    assert posters.film_year("2024–2025") == 2024
    assert posters.film_year(True) is None


def test_films_dedupes_and_keeps_original_title():
    rows = [_screening("Морозко", "1964"), _screening("Морозко", 1964, venue="poravkino"),
            _screening("Морозко", 1964, venue="domkino", original_title="Morozko"),
            _screening("Без года")]
    films = posters.films(rows)
    assert list(films) == ["морозко|1964"]
    assert films["морозко|1964"].original_title == "Morozko"


# ---- choose (pure) --------------------------------------------------------------------
def test_choose_prefers_exact_title_and_year():
    candidates = [
        {"id": 1, "title": "Морозко", "release_date": "2017-01-01", "popularity": 50},
        {"id": 2, "title": "Морозко", "release_date": "1964-03-24", "popularity": 5},
        {"id": 3, "title": "Другое", "release_date": "1964-01-01", "popularity": 500},
    ]
    assert posters.choose(candidates, MOROZKO)["id"] == 2


def test_choose_matches_original_title_within_one_year():
    film = posters.Film("x|2024", "Русское название", 2024, original_title="The Thing")
    candidates = [{"id": 7, "title": "Нечто другое", "original_title": "The Thing",
                   "release_date": "2025-02-01"}]
    assert posters.choose(candidates, film)["id"] == 7


def test_choose_accepts_lone_same_year_result_but_not_two():
    lone = [{"id": 9, "title": "Иное имя", "release_date": "1964-01-01"}]
    assert posters.choose(lone, MOROZKO)["id"] == 9
    assert posters.choose(lone + [{"id": 10, "title": "Ещё", "release_date": "1964-05-05"}], MOROZKO) is None


def test_choose_rejects_year_drift_beyond_one():
    assert posters.choose([{"id": 1, "title": "Морозко", "release_date": "1966-01-01"}], MOROZKO) is None


# ---- parse against fixtures (offline) -------------------------------------------------
@_NEED_FIXTURES
def test_parse_morozko_fixture_resolves_a_poster_via_any_retry():
    # Реальность TMDB (ручная проверка владельца, 2026-11-05): запись классики «Морозко»
    # несёт ре-релиз 1965-03-24, поэтому поиск с year=1964 пуст, any-ретрай без года
    # даёт 4 кандидата, и choose() берёт 20932 по строгому названию в окне ±1 года.
    entries = posters.parse(
        [(MOROZKO.key, _body("search_morozko_1964.json")),
         (MOROZKO.key + posters.ANY_SUFFIX, _body("search_morozko_any.json"))],
        [MOROZKO], today=TODAY)
    entry = entries[MOROZKO.key]
    assert entry["via"] == "any"
    assert entry["tmdb_title"] == "Морозко"
    assert entry["tmdb_id"] == 20932
    assert entry["poster_path"].startswith("/") and entry["poster_path"].endswith((".jpg", ".png"))
    assert entry["resolved_at"] == "2026-11-05"


@_NEED_FIXTURES
def test_parse_empty_fixture_is_a_miss_and_any_retry_is_used():
    film = posters.Film("zzqx|2026", "zzqx-cinedigest-no-such-film", 2026)
    empty = _body("search_empty.json")
    assert posters.results(empty) == []
    assert posters.parse([(film.key, empty)], [film], today=TODAY)[film.key]["via"] == "miss"
    hit = json.dumps({"results": [{"id": 5, "title": "zzqx-cinedigest-no-such-film",
                                   "release_date": "2026-01-01", "poster_path": "/z.jpg"}]})
    entry = posters.parse([(film.key, empty), (film.key + posters.ANY_SUFFIX, hit)], [film], today=TODAY)[film.key]
    assert entry["via"] == "any" and entry["poster_path"] == "/z.jpg"


def test_parse_leaves_films_without_a_body_untouched():
    assert posters.parse([], [MOROZKO], today=TODAY) == {}


@_NEED_FIXTURES
def test_parse_override_by_id_uses_movie_body():
    movie = json.loads(_body("movie_morozko.json"))
    overrides = {MOROZKO.key: {"tmdb_id": movie["id"]}}
    entry = posters.parse([(MOROZKO.key, json.dumps(movie))], [MOROZKO], overrides, today=TODAY)[MOROZKO.key]
    assert entry["via"] == "override" and entry["tmdb_id"] == movie["id"]
    # a body for another id is ignored
    other = dict(movie, id=movie["id"] + 1)
    assert posters.parse([(MOROZKO.key, json.dumps(other))], [MOROZKO], overrides, today=TODAY) == {}


# ---- plan, freshness, prune -----------------------------------------------------------
def _entry(days_ago, poster="/p.jpg", tmdb_id=1):
    return {"tmdb_id": tmdb_id, "poster_path": poster, "resolved_at": (TODAY - timedelta(days=days_ago)).isoformat()}


def test_plan_skips_fresh_hits_and_retries_old_misses():
    wanted = {"a|2000": posters.Film("a|2000", "a", 2000), "b|2000": posters.Film("b|2000", "b", 2000),
              "c|2000": posters.Film("c|2000", "c", 2000), "d|2000": posters.Film("d|2000", "d", 2000)}
    cache = {"a|2000": _entry(10), "b|2000": _entry(config.TMDB_REFRESH_DAYS),
             "c|2000": _entry(config.TMDB_MISS_RETRY_DAYS - 1, poster=None)}
    assert [f.key for f in posters.plan(wanted, cache, {}, TODAY)] == ["b|2000", "d|2000"]


def test_plan_honours_overrides():
    wanted = {"a|2000": posters.Film("a|2000", "a", 2000), "b|2000": posters.Film("b|2000", "b", 2000),
              "c|2000": posters.Film("c|2000", "c", 2000)}
    overrides = {"a|2000": None, "b|2000": {"poster_path": "/x.jpg"}, "c|2000": {"tmdb_id": 42}}
    assert [f.key for f in posters.plan(wanted, {}, overrides, TODAY)] == ["c|2000"]
    assert posters.plan(wanted, {"c|2000": _entry(1, tmdb_id=42)}, overrides, TODAY) == []


def test_plan_is_bounded(monkeypatch):
    monkeypatch.setattr(config, "TMDB_MAX_LOOKUPS_PER_RUN", 2)
    wanted = {f"f{i}|2000": posters.Film(f"f{i}|2000", f"f{i}", 2000) for i in range(5)}
    assert len(posters.plan(wanted, {}, {}, TODAY)) == 2


def test_prune_drops_entries_older_than_six_months_or_undated():
    cache = {"old": _entry(config.TMDB_CACHE_MAX_AGE_DAYS + 1), "edge": _entry(config.TMDB_CACHE_MAX_AGE_DAYS),
             "nodate": {"poster_path": "/p.jpg"}, "future": _entry(-1)}
    assert set(posters.prune(cache, TODAY)) == {"edge"}


# ---- cache files and overrides --------------------------------------------------------
def test_save_cache_writes_notice_and_is_idempotent(tmp_path):
    path = tmp_path / "docs" / "posters.json"
    assert posters.save_cache(path, {"a|2000": _entry(1)}, TODAY) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["_notice"] == config.TMDB_NOTICE and "a|2000" in data["films"]
    assert posters.save_cache(path, {"a|2000": _entry(1)}, TODAY) is False
    assert posters.load_cache(path) == {"a|2000": _entry(1)}
    assert posters.load_cache(tmp_path / "missing.json") == {}


def test_load_overrides_normalises_keys_and_skips_help(tmp_path):
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"_help": "…", "Морозко|1964": None, "Сумерки. Saga. Затмение|2010": {"tmdb_id": 24021},
                                "bad|2000": "nope"}), encoding="utf-8")
    loaded = posters.load_overrides(path)
    assert loaded == {"морозко|1964": None, "сумерки saga затмение|2010": {"tmdb_id": 24021}}


# ---- fetch (synthetic http) -----------------------------------------------------------
def test_fetch_sends_bearer_and_retries_without_year_only_when_empty():
    hit = json.dumps({"results": [{"id": 1, "title": "Морозко", "release_date": "1964-01-01"}]})
    http = FakeHttp({"search/movie": hit})
    raw = posters.fetch(http, "tok", [MOROZKO])
    assert [label for label, _ in raw] == [MOROZKO.key]
    url, params, _ = http.calls[0]
    assert url.endswith("/3/search/movie") and params["year"] == 1964 and params["language"] == config.TMDB_LANGUAGE
    film = posters.Film("пусто|2025", "Пусто", 2025, original_title="Empty")
    http = FakeHttp({})
    raw = posters.fetch(http, "tok", [film])
    assert [label for label, _ in raw] == [film.key, film.key + posters.ANY_SUFFIX]
    assert http.calls[1][1]["query"] == "Empty" and "year" not in http.calls[1][1]


def test_fetch_stops_after_failure_budget():
    films = [posters.Film(f"f{i}|2000", f"f{i}", 2000) for i in range(6)]
    http = FakeHttp({"search/movie": 429})
    assert posters.fetch(http, "tok", films) == []
    assert len(http.calls) == config.TMDB_FAILURE_LIMIT


def test_fetch_uses_movie_endpoint_for_id_override():
    http = FakeHttp({"movie/77": json.dumps({"id": 77, "title": "Морозко", "poster_path": "/m.jpg"})})
    raw = posters.fetch(http, "tok", [MOROZKO], {MOROZKO.key: {"tmdb_id": 77}})
    assert raw[0][0] == MOROZKO.key and http.calls[0][0].endswith("/3/movie/77")


# ---- URLs for the renderer ------------------------------------------------------------
def test_poster_urls_respect_cache_and_overrides():
    rows = [_screening("Морозко", 1964), _screening("Скрытый", 2000), _screening("Пин", 2001), _screening("Файл", 2002)]
    cache = {"морозко|1964": _entry(1, poster="/m.jpg"), "скрытый|2000": _entry(1), "пин|2001": _entry(1, tmdb_id=5)}
    overrides = {"скрытый|2000": None, "пин|2001": {"tmdb_id": 6}, "файл|2002": {"poster_path": "/f.jpg"}}
    urls = posters.poster_urls(rows, cache, overrides)
    assert urls == {"морозко|1964": f"{config.TMDB_IMAGE_BASE_URL}{config.TMDB_POSTER_SIZE}/m.jpg",
                    "файл|2002": f"{config.TMDB_IMAGE_BASE_URL}{config.TMDB_POSTER_SIZE}/f.jpg"}


def test_resolve_without_token_skips_network_and_uses_cache(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv(config.TMDB_READ_TOKEN_ENV, raising=False)
    docs = tmp_path / "docs"
    posters.save_cache(docs / config.POSTERS_FILENAME, {"морозко|1964": _entry(1, poster="/m.jpg")}, TODAY)
    http = FakeHttp({})
    with caplog.at_level("INFO"):
        urls = posters.resolve([_screening("Морозко", 1964)], http=http, out_dir=tmp_path, today=TODAY)
    assert http.calls == [] and "морозко|1964" in urls
    assert any(config.TMDB_READ_TOKEN_ENV in r.getMessage() for r in caplog.records)


def test_resolve_with_token_fills_and_persists_cache(tmp_path):
    hit = json.dumps({"results": [{"id": 3, "title": "Морозко", "release_date": "1964-03-24", "poster_path": "/m.jpg"}]})
    http = FakeHttp({"search/movie": hit})
    urls = posters.resolve([_screening("Морозко", 1964)], http=http, out_dir=tmp_path, today=TODAY, token="tok")
    assert urls["морозко|1964"].endswith("/m.jpg")
    saved = json.loads((tmp_path / "docs" / config.POSTERS_FILENAME).read_text(encoding="utf-8"))
    assert saved["films"]["морозко|1964"]["tmdb_id"] == 3
    http2 = FakeHttp({})
    posters.resolve([_screening("Морозко", 1964)], http=http2, out_dir=tmp_path, today=TODAY, token="tok")
    assert http2.calls == []  # fresh hit: no second lookup
