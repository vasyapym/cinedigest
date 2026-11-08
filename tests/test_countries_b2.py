"""Stage B2: identity registration, year hints, and the cache-fed render seam."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

import pytest

from cinedigest import countries, posters, render
from cinedigest.countries import CountryEvidence
from cinedigest.model import MSK, Screening, Snapshot, VENUES, VenueStatus

TODAY = date(2026, 11, 5)
GENERATED = datetime(2026, 11, 5, 9, 2, tzinfo=MSK)


def _row(source_id, *, title="Фильм", year=None, country=None):
    extra = {}
    if year is not None:
        extra["year"] = year
    if country is not None:
        extra["country"] = country
    return Screening(
        venue="mirage",
        source_id=source_id,
        title=title,
        start=datetime(2026, 11, 5, 19, tzinfo=MSK),
        extra=extra,
    )


def _snapshot(rows):
    return Snapshot(
        generated_at=GENERATED,
        window_start=TODAY,
        window_end=TODAY,
        statuses=[
            VenueStatus(
                venue=venue,
                ok=True,
                count=sum(row.venue == venue for row in rows),
                fetched_at=GENERATED,
            )
            for venue in VENUES
        ],
        screenings=rows,
    )


def _extras(rows, *, additional=()):
    return {
        row.source_id: row.extra
        for row in countries.enrich(rows, additional=additional)
    }


@pytest.mark.parametrize("empty_country", ["", [], ()])
def test_b2_c8_countryless_additional_registers_identity(empty_country):
    rows = [
        _row("target", year=1964),
        _row("donor", country="Россия"),
    ]
    evidence = [
        CountryEvidence("Фильм", 1970, empty_country, "local-detail:1970"),
    ]
    before_rows, before_evidence = deepcopy(rows), deepcopy(evidence)

    # One known identity allows the undated window donor.
    assert _extras(rows)["target"]["country"] == "Россия"

    # A second identity blocks that donation, whether registered by a row
    # or by additional evidence without a country.
    from_window = _extras(rows + [_row("second-identity", year=1970)])
    from_additional = _extras(rows, additional=evidence)
    assert from_window["target"] == from_additional["target"]
    assert from_additional["target"]["country_status"] == "unknown"
    assert "country" not in from_additional["target"]
    assert "country_source" not in from_additional["target"]
    assert rows == before_rows
    assert evidence == before_evidence


def test_b2_c8_matching_countryless_identity_does_not_donate_country():
    rows = [_row("target")]
    identity = CountryEvidence("Фильм", 1964, "", "local-identity:1964")

    extra = _extras(rows, additional=[identity])["target"]
    assert extra["country_status"] == "unknown"
    assert "country" not in extra
    assert "country_source" not in extra

    donor = CountryEvidence("Фильм", 1964, "Россия", "local-detail:1964")
    extra = _extras(rows, additional=[identity, donor])["target"]
    assert extra["country"] == "Россия"
    assert extra["country_source"] == "local-detail:1964"

    second_identity = CountryEvidence("Фильм", 1970, "", "local-identity:1970")
    extra = _extras(
        rows, additional=[identity, donor, second_identity],
    )["target"]
    assert extra["country_status"] == "unknown"
    assert "country" not in extra


def test_b2_identity_hints_recovers_unambiguous_window_year():
    rows = [
        _row("missing", title="  ФИЛЬМ  "),
        _row("dated", title="Фильм", year=1964),
    ]
    before = deepcopy(rows)

    assert countries.identity_hints(iter(rows)) == {
        posters.norm("Фильм"): 1964,
    }
    assert rows == before


def test_b2_identity_hints_dated_rows_keep_own_year_and_need_no_hint():
    rows = [_row("dated", year=1964)]
    evidence = [
        CountryEvidence("Фильм", 1970, "Россия", "local-detail:1970"),
    ]
    before = deepcopy(rows)

    assert countries.identity_hints(rows, additional=evidence) == {}
    enriched = countries.enrich(rows, additional=evidence)
    assert enriched[0].extra["year"] == 1964
    assert "country" not in enriched[0].extra
    assert rows == before


def test_b2_identity_hints_ambiguous_window_years_are_absent():
    rows = [
        _row("missing"),
        _row("first", year=1964),
        _row("second", year=1970),
    ]

    assert countries.identity_hints(rows) == {}


def test_b2_identity_hints_requires_a_dated_identity():
    rows = [_row("missing")]
    evidence = [
        CountryEvidence("Фильм", None, "Россия", "local-detail:undated"),
    ]

    assert countries.identity_hints(rows, additional=evidence) == {}


def test_b2_identity_hints_countryless_additional_participates():
    rows = [_row("missing", title="  ФИЛЬМ  ")]
    evidence = [
        CountryEvidence("Фильм", 1964, "", "local-identity:1964"),
    ]
    before_rows, before_evidence = deepcopy(rows), deepcopy(evidence)

    assert countries.identity_hints(
        iter(rows), additional=iter(evidence),
    ) == {posters.norm("Фильм"): 1964}
    assert rows == before_rows
    assert evidence == before_evidence

    evidence.append(
        CountryEvidence("Фильм", 1970, "", "local-identity:1970"),
    )
    assert countries.identity_hints(rows, additional=evidence) == {}


def test_b2_render_consumes_cache_country_evidence_offline(monkeypatch):
    rows = [
        _row("su", title="Морозко"),
        _row("ru", title="Российский фильм"),
    ]
    snapshot = _snapshot(rows)

    # Adapter-boundary fixture, not a claim about posters.json's entry schema.
    # country_evidence supplies normalized records under its public contract.
    entries = {
        "su-detail": {
            "country": ["Soviet Union"],
            "country_at": "2026-11-05",
            "country_via": "TMDB",
        },
        "ru-detail": {
            "country": ["Россия"],
            "country_at": "2026-11-05",
            "country_via": "TMDB",
        },
    }
    calls = []

    def country_evidence(cache_entries):
        assert cache_entries is entries
        calls.append(cache_entries)
        return [
            {
                "title": "Морозко",
                "year": 1964,
                "country": cache_entries["su-detail"]["country"],
                "source": "tmdb-detail:su",
            },
            {
                "title": "Российский фильм",
                "year": 2025,
                "country": cache_entries["ru-detail"]["country"],
                "source": "tmdb-detail:ru",
            },
        ]

    monkeypatch.setattr(posters, "country_evidence", country_evidence)
    before_snapshot, before_entries = deepcopy(snapshot), deepcopy(entries)

    context = render.render_context(snapshot, cache_entries=entries)
    extra = {
        row.source_id: row.extra
        for _, day_rows in context["days"]
        for row in day_rows
    }
    assert extra["su"]["country"] == ["Soviet Union"]
    assert extra["su"]["country_status"] == "other"
    assert extra["ru"]["country"] == ["Россия"]
    assert extra["ru"]["country_status"] == "Russian"
    assert "year" not in extra["su"]
    assert "year" not in extra["ru"]

    html = render.render(snapshot, cache_entries=entries)
    assert html.count('data-country-status="other">') == 1
    assert html.count('data-country-status="Russian">') == 1
    assert len(calls) == 2
    assert snapshot == before_snapshot
    assert entries == before_entries


def test_b2_render_empty_cache_preserves_default_bytes():
    snapshot = _snapshot([
        _row("unknown"),
        _row("known", title="Другой фильм", country="Россия"),
    ])
    before = deepcopy(snapshot)

    implicit = render.render(snapshot).encode("utf-8")
    empty = render.render(snapshot, cache_entries={}).encode("utf-8")
    explicit_none = render.render(snapshot, cache_entries=None).encode("utf-8")

    assert implicit == empty == explicit_none
    assert snapshot == before


def test_b2_real_cache_to_cli_render_offline(tmp_path):
    """The shipped contract end-to-end: real JSON envelope → real readers → CLI render, offline."""
    import json as json_lib
    import os as os_lib
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    snapshot_path = Path(__file__).parents[1] / "docs" / "screenings.json"
    if not snapshot_path.is_file():
        pytest.skip("committed snapshot is not in the tree")
    docs = tmp_path / "docs"
    docs.mkdir()
    shutil.copy(snapshot_path, docs / "screenings.json")
    entries = {
        "морозко|1964": {
            "title": "Морозко", "year": 1964, "tmdb_id": 20932,
            "resolved_at": "2026-11-05", "via": "override",
            "country": ["Soviet Union"], "country_at": "2026-11-05",
            "country_via": "tmdb:20932",
        },
        "рождение империи|2026": {
            "title": "Рождение империи", "year": 2026, "tmdb_id": 999,
            "resolved_at": "2026-11-05", "via": "override",
            "country": ["Russia"], "country_at": "2026-11-05",
            "country_via": "tmdb:999",
        },
    }
    (docs / "posters.json").write_text(json_lib.dumps({"films": entries}), encoding="utf-8")

    env = {key: value for key, value in os_lib.environ.items() if key != "TMDB_READ_TOKEN"}
    result = subprocess.run(
        [sys.executable, "-m", "cinedigest", "render", "--out", str(tmp_path)],
        capture_output=True, env=env, cwd=str(Path(__file__).parents[1]),
    )
    assert result.returncode == 0, result.stderr[-900:]
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")

    rows = [piece for piece in html.split('<li class="r')[1:]
            if "Мираж на Большом" in piece]
    ru_rows = [p for p in rows if "Рождение империи" in p]
    su_rows = [p for p in rows if "Морозко" in p]
    assert ru_rows and su_rows
    for piece in ru_rows:
        assert 'data-country-status="Russian"' in piece
    for piece in su_rows:
        #ild the window already carries the dated 2026-remake identity (Россия) AND the
        # cache adds the 1964 one (Soviet Union) — two identities = honest `unknown`.
        assert 'data-country-status="unknown"' in piece
