"""Постеры TMDB: ключи фильмов, выбор кандидата, план запросов, кэш и срок хранения, оверрайды,
локальные копии байтов и рендер src."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from cinedigest import config, deliver, posters
from cinedigest.http import HttpError
from cinedigest.model import MSK, Screening, Snapshot, VenueStatus, VENUES

FIXTURES = Path(__file__).parent / "fixtures" / "tmdb"
POSTER_FIXTURES = Path(__file__).parent / "fixtures" / "posters"
POSTER_FIXTURE_NAME = "bHZyAtkMFeJXpUYV9pcOofzQ1I6.jpg"
TODAY = date(2026, 11, 5)
GENERATED = datetime(2026, 11, 5, 9, 2, tzinfo=MSK)
MOROZKO = posters.Film("морозко|1964", "Морозко", 1964)
MOROZKO_PATH = "/bHZyAtkMFeJXpUYV9pcOofzQ1I6.jpg"  # живая запись кэша (была в docs/posters.json)
MOROZKO_FILE = MOROZKO_PATH[1:]

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


def _snapshot(rows, days=7):
    """A valid snapshot over TODAY's window (rows: Screening) for render/deliver asserts."""
    statuses = [VenueStatus(venue=key, ok=True, count=1, fetched_at=GENERATED) for key in VENUES]
    return Snapshot(generated_at=GENERATED, window_start=TODAY,
                    window_end=TODAY + timedelta(days=days - 1), statuses=statuses, screenings=rows)


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

    def get_bytes(self, url, *, params=None, headers=None, venue="", label=""):
        """Байты ищутся по полному URL или по имени файла; отсутствие в плане — HTTP 404."""
        self.calls.append((url, dict(params or {}), label))
        answer = self.plan.get(url)
        if answer is None:
            answer = self.plan.get(url.rsplit("/", 1)[-1])
        if isinstance(answer, int):
            raise HttpError(f"HTTP {answer}", url=url, status=answer)
        if answer is None:
            raise HttpError("HTTP 404", url=url, status=404)
        return answer if isinstance(answer, bytes) else str(answer).encode("utf-8")


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
    assert list(films) == ["морозко|1964", "без года|any"]
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
def _entry(days_ago, poster="/p.jpg", tmdb_id=1, days_bytes=None, file=None):
    """Cache entry fixture; days_bytes counts the byte age back from TODAY (None = undated)."""
    entry = {"tmdb_id": tmdb_id, "poster_path": poster,
             "resolved_at": (TODAY - timedelta(days=days_ago)).isoformat()}
    if file is not None:
        entry["file"] = file
    if days_bytes is not None:
        entry["file_downloaded_at"] = (TODAY - timedelta(days=days_bytes)).isoformat()
    return entry


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


# ---- local files for the renderer ------------------------------------------------------
def test_file_name_validates_basenames_and_rejects_everything_else():
    assert posters.file_name("/bHZyAtkMFeJXpUYV9pcOofzQ1I6.jpg") == MOROZKO_FILE
    assert posters.file_name("/a/b/m.jpg") == "m.jpg"  # directory parts are stripped, not followed
    assert posters.file_name("../m.jpg") == "m.jpg"    # and the result stays inside docs/posters/
    assert posters.file_name(".") is None and posters.file_name("..") is None
    assert posters.file_name(".hidden.jpg") is None and posters.file_name("a\\b.jpg") is None
    assert posters.file_name("") is None and posters.file_name(None) is None and posters.file_name(7) is None


def test_file_recent_binds_the_same_retention_clause_as_the_metadata():
    fresh = timedelta(days=config.TMDB_CACHE_MAX_AGE_DAYS)
    assert posters.file_recent((TODAY - fresh).isoformat(), TODAY) is True
    assert posters.file_recent((TODAY - fresh - timedelta(days=1)).isoformat(), TODAY) is False
    assert posters.file_recent(None, TODAY) is False and posters.file_recent("x", TODAY) is False
    assert posters.file_recent((TODAY + timedelta(days=1)).isoformat(), TODAY) is False


def test_poster_files_respect_cache_overrides_date_and_disk(tmp_path):
    docs = tmp_path / "docs"
    (docs / config.POSTERS_DIRNAME).mkdir(parents=True)
    (docs / config.POSTERS_DIRNAME / "m.jpg").write_bytes(b"m")
    cache = {
        "морозко|1964": _entry(1, poster="/m.jpg", file="m.jpg", days_bytes=5),  # файл на диске, дата свежая
        "скрытый|2000": _entry(1, poster="/s.jpg", file="s.jpg", days_bytes=5),  # переопределён на null
        "пин|2001": _entry(1, poster="/p.jpg", file="p.jpg", days_bytes=0),     # айди-пин на чужой tmdb_id
        "файл|2002": {"tmdb_id": 7, "poster_path": "/f.jpg", "resolved_at": TODAY.isoformat(),
                      "file": "wrong.jpg", "file_downloaded_at": TODAY.isoformat()},  # запись о другом файле
        "пропал|2003": _entry(1, poster="/z.jpg", file="z.jpg", days_bytes=0),   # файла нет на диске
    }
    overrides = {"скрытый|2000": None, "пин|2001": {"tmdb_id": 6},
                 "файл|2002": {"poster_path": "/f.jpg"},
                 "пропал|2003": {"poster_path": "/z.jpg"}}
    wanted = {"морозко|1964": posters.Film("морозко|1964", "Морозко", 1964),
              "скрытый|2000": posters.Film("скрытый|2000", "Скрытый", 2000),
              "пин|2001": posters.Film("пин|2001", "Пин", 2001),
              "файл|2002": posters.Film("файл|2002", "Файл", 2002),
              "пропал|2003": posters.Film("пропал|2003", "Пропал", 2003)}
    files = posters.poster_files(wanted, cache, overrides, TODAY, docs / config.POSTERS_DIRNAME)
    assert files == {"морозко|1964": "posters/m.jpg"}  # ни CDN-, ни «файл просто есть»
    # запись о байтах «wrong.jpg» расходится с эффективным /f.jpg — качаем заново; без файла — тоже
    assert posters.download_plan(
        [_screening("Файл", 2002), _screening("Пропал", 2003)],
        cache, overrides, TODAY, docs / config.POSTERS_DIRNAME,
    ) == ["/f.jpg", "/z.jpg"]


def test_missing_local_file_renders_no_poster_and_no_cdn_fallback(tmp_path):
    docs = tmp_path / "docs"
    rows = [_screening("Морозко", 1964, venue="poravkino"), _screening("Морозко", 1964, venue="mirage")]
    posters.save_cache(docs / config.POSTERS_FILENAME,
                       {"морозко|1964": _entry(1, poster=MOROZKO_PATH, file=MOROZKO_FILE, days_bytes=3)},
                       TODAY)
    html_path, digest_path = deliver.write(_snapshot(rows), tmp_path)
    html = html_path.read_text(encoding="utf-8")
    assert 'class="p"' not in html
    assert "image.tmdb.org" not in html and config.TMDB_NOTICE not in html  # никакой замены на CDN
    digest = digest_path.read_text(encoding="utf-8")
    assert "image.tmdb.org" not in digest and "posters/" not in digest


def test_expired_or_undated_byte_age_is_not_rendered_even_when_the_file_exists(tmp_path):
    docs = tmp_path / "docs"
    dir = docs / config.POSTERS_DIRNAME
    dir.mkdir(parents=True)
    for name in ("x.jpg", "y.jpg", "z.jpg"):
        (dir / name).write_bytes(b"present")
    cache = {
        "a|2000": _entry(1, poster="/x.jpg", file="x.jpg",
                         days_bytes=config.TMDB_CACHE_MAX_AGE_DAYS + 1),  # просрочена
        "b|2000": _entry(1, poster="/y.jpg", file="y.jpg", days_bytes=None),  # дата не записана
        "c|2000": {"tmdb_id": 1, "poster_path": "/z.jpg", "resolved_at": TODAY.isoformat(),
                   "file": "z.jpg", "file_downloaded_at": (TODAY + timedelta(days=1)).isoformat()},  # из будущего
    }
    wanted = {f"{k}|2000": posters.Film(f"{k}|2000", k, 2000) for k in ("a", "b", "c")}
    assert posters.poster_files(wanted, cache, {}, TODAY, dir) == {}
    save_path = docs / config.POSTERS_FILENAME
    posters.save_cache(save_path, cache, TODAY)
    rows = [_screening("a", 2000, venue="mirage"), _screening("b", 2000, venue="mirage"),
            _screening("c", 2000, venue="mirage")]
    assert posters.cached_urls(rows, docs, TODAY) == {}  # и на живом файле кэша — тоже ничего


def test_failed_publication_leaves_existing_bytes_intact(tmp_path, monkeypatch):
    name_dir = tmp_path / config.POSTERS_DIRNAME
    name_dir.mkdir()
    (name_dir / "m.jpg").write_bytes(b"GOOD BYTES")

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)
    stored = posters.download_files(FakeHttp({"m.jpg": b"NEW BYTES"}), ["/m.jpg"], name_dir)
    assert stored == {}
    assert (name_dir / "m.jpg").read_bytes() == b"GOOD BYTES"
    assert sorted(p.name for p in name_dir.iterdir()) == ["m.jpg"]  # нет даже временных следов


def test_resolve_without_token_skips_network_uses_cache_and_keeps_docs_honest(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv(config.TMDB_READ_TOKEN_ENV, raising=False)
    docs = tmp_path / "docs"
    posters.save_cache(
        docs / config.POSTERS_FILENAME,
        {"морозко|1964": _entry(1, poster="/m.jpg", file="m.jpg", days_bytes=2)}, TODAY,
    )
    (docs / config.POSTERS_DIRNAME).mkdir(parents=True)
    (docs / config.POSTERS_DIRNAME / "m.jpg").write_bytes(b"reused")
    http = FakeHttp({})
    with caplog.at_level("INFO"):
        urls = posters.resolve([_screening("Морозко", 1964)], http=http, out_dir=tmp_path, today=TODAY)
    assert http.calls == [] and urls == {"морозко|1964": "posters/m.jpg"}
    assert any(config.TMDB_READ_TOKEN_ENV in r.getMessage() for r in caplog.records)


def test_resolve_without_token_still_prunes_expired_entries_and_files(tmp_path, monkeypatch, caplog):
    docs = tmp_path / "docs"
    cache = {
        "fresh|2000": _entry(1, poster="/f.jpg", file="f.jpg", days_bytes=1),
        "old|2000": _entry(config.TMDB_CACHE_MAX_AGE_DAYS + 1, poster="/o.jpg", file="o.jpg",
                           days_bytes=2),  # просроченная запись: её файлы тоже должны уйти
    }
    posters.save_cache(docs / config.POSTERS_FILENAME, cache, TODAY)
    (docs / config.POSTERS_DIRNAME).mkdir(parents=True)
    (docs / config.POSTERS_DIRNAME / "f.jpg").write_bytes(b"f")
    (docs / config.POSTERS_DIRNAME / "o.jpg").write_bytes(b"o")          # ссылка умерла вместе с записью
    (docs / config.POSTERS_DIRNAME / "orphan.jpg").write_bytes(b"x")     # ссылок не было и раньше
    monkeypatch.delenv(config.TMDB_READ_TOKEN_ENV, raising=False)
    with caplog.at_level("INFO"):
        posters.resolve([], http=FakeHttp({}), out_dir=tmp_path, today=TODAY)
    saved = json.loads((docs / config.POSTERS_FILENAME).read_text(encoding="utf-8"))
    assert "old|2000" not in saved["films"] and "fresh|2000" in saved["films"]
    assert sorted(p.name for p in (docs / config.POSTERS_DIRNAME).iterdir()) == ["f.jpg"]
    assert any("pruned 2 stale image file" in r.getMessage() for r in caplog.records)


def test_resolve_with_token_fills_and_persists_cache(tmp_path):
    hit = json.dumps({"results": [{"id": 3, "title": "Морозко", "release_date": "1964-03-24", "poster_path": "/m.jpg"}]})
    fixture = (POSTER_FIXTURES / POSTER_FIXTURE_NAME).read_bytes()
    http = FakeHttp({"search/movie": hit, "m.jpg": fixture})
    urls = posters.resolve([_screening("Морозко", 1964)], http=http, out_dir=tmp_path, today=TODAY, token="tok")
    assert urls == {"морозко|1964": "posters/m.jpg"}
    saved = json.loads((tmp_path / "docs" / config.POSTERS_FILENAME).read_text(encoding="utf-8"))["films"]["морозко|1964"]
    assert saved["tmdb_id"] == 3 and saved["file"] == "m.jpg"
    assert saved["file_downloaded_at"] == TODAY.isoformat()
    assert [call[0] for call in http.calls] == [
        "https://api.themoviedb.org/3/search/movie",
        "https://api.themoviedb.org/3/movie/3",
        f"{config.TMDB_IMAGE_BASE_URL}w185/m.jpg",
    ]
    http2 = FakeHttp({"m.jpg": fixture})
    posters.resolve([_screening("Морозко", 1964)], http=http2, out_dir=tmp_path, today=TODAY, token="tok")
    assert http2.calls == []  # свежий хит и свежий файл: ни второго поиска, ни второго скачивания


# ---- byte stage: хранение, дедупликация, миграция, сломанная запись --------------------
def test_downloaded_bytes_are_stored_exactly(tmp_path):
    docs = tmp_path / "docs"
    posters.save_cache(docs / config.POSTERS_FILENAME, {"морозко|1964": _entry(0, poster=MOROZKO_PATH)}, TODAY)
    fixture = (POSTER_FIXTURES / POSTER_FIXTURE_NAME).read_bytes()
    http = FakeHttp({MOROZKO_FILE: fixture})
    urls = posters.resolve([_screening("Морозко", 1964)], http=http, out_dir=tmp_path, today=TODAY, token="tok")
    stored = (docs / config.POSTERS_DIRNAME / MOROZKO_FILE).read_bytes()
    assert stored == fixture  # байты до последнего: и размер, и содержимое
    assert hashlib.sha256(stored).hexdigest() == hashlib.sha256(fixture).hexdigest()
    assert urls == {"морозко|1964": f"posters/{MOROZKO_FILE}"}


def test_metadata_only_entries_become_download_candidates(tmp_path):
    docs = tmp_path / "docs"
    posters.save_cache(
        docs / config.POSTERS_FILENAME,
        {"морозко|1964": _entry(0, poster=MOROZKO_PATH),
         "second|2001": _entry(2, poster="/s.jpg", tmdb_id=9)},
        TODAY,
    )
    rows = [_screening("Морозко", 1964, venue="poravkino"), _screening("Second", 2001, venue="mirage")]
    fixture = (POSTER_FIXTURES / POSTER_FIXTURE_NAME).read_bytes()
    http = FakeHttp({MOROZKO_FILE: fixture, "s.jpg": b"S BYTES"})
    urls = posters.resolve(rows, http=http, out_dir=tmp_path, today=TODAY, token="tok")
    assert [call[2] for call in http.calls] == [MOROZKO_FILE, "s.jpg"]  # только скачивания байтов
    saved = json.loads((docs / config.POSTERS_FILENAME).read_text(encoding="utf-8"))["films"]
    assert saved["морозко|1964"]["file"] == MOROZKO_FILE
    assert saved["second|2001"]["file"] == "s.jpg"
    assert saved["second|2001"]["file_downloaded_at"] == TODAY.isoformat()
    assert urls == {"морозко|1964": f"posters/{MOROZKO_FILE}", "second|2001": "posters/s.jpg"}


def test_shared_poster_path_downloads_once_and_dates_entries_together(tmp_path):
    """Реальный пример кэша: у «Безумного дня в Комеди Франсез» и его версии с субтитрами
    один и тот же poster_path — повторного скачивания быть не должно."""
    docs = tmp_path / "docs"
    shared_file = "3ykToOKrgIlKBOkxpRscXNAkzET.jpg"
    posters.save_cache(
        docs / config.POSTERS_FILENAME,
        {"безумный день в комеди франсез|2026": _entry(1, poster=f"/{shared_file}"),
         "безумный день в комеди франсез субтитры|2026": _entry(1, poster=f"/{shared_file}")},
        TODAY,
    )
    rows = [_screening("Безумный день в Комеди Франсез", 2026, venue="mirage"),
            _screening("Безумный день в Комеди Франсез (субтитры)", 2026, venue="rodina")]
    http = FakeHttp({shared_file: b"SHARED BYTES"})
    urls = posters.resolve(rows, http=http, out_dir=tmp_path, today=TODAY, token="tok")
    assert [call[2] for call in http.calls] == [shared_file]  # ровно одно скачивание на один файл
    saved = json.loads((docs / config.POSTERS_FILENAME).read_text(encoding="utf-8"))["films"]
    assert {entry["file"] for entry in saved.values()} == {shared_file}
    assert {entry["file_downloaded_at"] for entry in saved.values()} == {TODAY.isoformat()}
    assert urls == {key: f"posters/{shared_file}" for key in saved}


def test_metadata_refresh_does_not_renew_the_byte_age(tmp_path):
    docs = tmp_path / "docs"
    byte_age = (TODAY - timedelta(days=10)).isoformat()
    posters.save_cache(
        docs / config.POSTERS_FILENAME,
        {"морозко|1964": _entry(config.TMDB_REFRESH_DAYS, poster=MOROZKO_PATH,
                                file=MOROZKO_FILE, days_bytes=10)},  # метадата устарела, байты ещё нет
        TODAY,
    )
    hit = json.dumps({"results": [{"id": 20932, "title": "Морозко", "release_date": "1965-03-24",
                                   "poster_path": MOROZKO_PATH}]})
    http = FakeHttp({"search/movie": hit})  # байтов в плане нет — обновление байтов сорвётся
    posters.resolve([_screening("Морозко", 1964)], http=http, out_dir=tmp_path, today=TODAY, token="tok")
    saved = json.loads((docs / config.POSTERS_FILENAME).read_text(encoding="utf-8"))["films"]["морозко|1964"]
    assert saved["resolved_at"] == TODAY.isoformat()  # метаданные обновлены
    assert saved["file"] == MOROZKO_FILE and saved["file_downloaded_at"] == byte_age  # возраст байтов не тронут


def test_unsafe_poster_paths_never_touch_the_network_or_escape_the_folder(tmp_path):
    docs = tmp_path / "docs"
    cache = {"bad|2000": _entry(1, poster="/..\\evil.jpg"), "ok|2000": _entry(1, poster="/ok.jpg")}
    posters.save_cache(docs / config.POSTERS_FILENAME, cache, TODAY)
    rows = [_screening("bad", 2000, venue="mirage"), _screening("ok", 2000, venue="poravkino")]
    http = FakeHttp({"ok.jpg": b"OK BYTES"})
    urls = posters.resolve(rows, http=http, out_dir=tmp_path, today=TODAY, token="tok")
    assert [call[2] for call in http.calls] == ["ok.jpg"]  # у небезопасного имени нет и скачивания
    assert urls == {"ok|2000": "posters/ok.jpg"}
    assert not (docs / "evil.jpg").exists()  # ничего вне docs/posters/
    assert not (docs / config.POSTERS_DIRNAME / "evil.jpg").exists()  # и не в самом каталоге
    unverifiable = {"ok|2000": _entry(1, poster="/ok.jpg", file="../evil.jpg", days_bytes=0)}
    assert posters.poster_files({"ok|2000": posters.Film("ok|2000", "ok", 2000)},
                                unverifiable, {}, TODAY, docs) == {}  # посторонний `file` не читается


def test_path_override_is_downloaded_and_rendered_locally(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True)
    (docs / config.POSTER_OVERRIDES_FILENAME).write_text(
        json.dumps({"Дежавю|2006": {"poster_path": "/d.jpg"}}), encoding="utf-8")
    rows = [_screening("Дежавю", 2006, venue="avrora")]
    http = FakeHttp({"d.jpg": b"OVERRIDE BYTES"})
    urls = posters.resolve(rows, http=http, out_dir=tmp_path, today=TODAY, token="tok")
    assert urls == {"дежавю|2006": "posters/d.jpg"}
    assert (docs / config.POSTERS_DIRNAME / "d.jpg").read_bytes() == b"OVERRIDE BYTES"
    html_path, digest_path = deliver.write(_snapshot(rows), tmp_path)
    html = html_path.read_text(encoding="utf-8")
    assert 'src="posters/d.jpg"' in html and "image.tmdb.org" not in html
    digest = digest_path.read_text(encoding="utf-8")
    assert "posters/d.jpg" not in digest and "image.tmdb.org" not in digest


def test_download_bounds_are_separate_from_the_lookup_bounds(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TMDB_MAX_DOWNLOADS_PER_RUN", 2)
    monkeypatch.setattr(config, "TMDB_DOWNLOAD_FAILURE_LIMIT", 1)
    target_dir = tmp_path / config.POSTERS_DIRNAME
    http = FakeHttp({"a.jpg": b"a", "b.jpg": b"b", "c.jpg": 500, "d.jpg": 500})
    stored = posters.download_files(http, ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg"], target_dir)
    assert stored == {"/a.jpg": "a.jpg", "/b.jpg": "b.jpg"}  # лишние ждут следующего запуска
    assert len(http.calls) == 2  # сверх бюджета не начинаются
    http = FakeHttp({"a.jpg": b"a", "b.jpg": 500, "c.jpg": 500})
    stored = posters.download_files(http, ["/a.jpg", "/b.jpg", "/c.jpg"], target_dir)
    assert stored == {"/a.jpg": "a.jpg"} and len(http.calls) == 2  # после первой неудачи — стоп
    assert sorted(p.name for p in target_dir.iterdir()) == ["a.jpg", "b.jpg"]
