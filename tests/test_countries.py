"""Country classification, conservative local fill, and static filter markup."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest

from cinedigest import countries, posters, render
from cinedigest.countries import CountryEvidence
from cinedigest.model import MSK, Screening, Snapshot, VENUES, VenueStatus

TODAY = date(2026, 11, 5)
GENERATED = datetime(2026, 11, 5, 9, 2, tzinfo=MSK)
COUNTRY_HIDE = (
    '#no-russia:checked ~ main .list '
    '.r[data-country-status="Russian"]{display:none!important}'
)


def _row(
    source_id,
    *,
    venue="mirage",
    title="Фильм",
    year=None,
    country=None,
    day=TODAY,
    hour=19,
):
    extra = {}
    if year is not None:
        extra["year"] = year
    if country is not None:
        extra["country"] = country
    return Screening(
        venue=venue,
        source_id=source_id,
        title=title,
        start=datetime(day.year, day.month, day.day, hour, tzinfo=MSK),
        extra=extra,
    )


def _snapshot(rows, days=2):
    return Snapshot(
        generated_at=GENERATED,
        window_start=TODAY,
        window_end=TODAY + timedelta(days=days - 1),
        statuses=[
            VenueStatus(venue=k, ok=True, count=0, fetched_at=GENERATED)
            for k in VENUES
        ],
        screenings=rows,
    )


def _extras(rows, **kwargs):
    return {
        row.source_id: row.extra
        for row in countries.enrich(rows, **kwargs)
    }


@pytest.mark.parametrize("country", [
    "Россия",
    "  рОсСиЯ  ",
    "РОССИЙСКАЯ ФЕДЕРАЦИЯ",
    " российская   федерация ",
    "Российская-Федерация",
    "ru",
    " RUS ",
    "Российская\u00a0Федерация",
    "Россия.",
    "RU (Российская Федерация)",
    " RUS.\u00a0(Россия). ",
    "Франция / RU (Российская\u00a0Федерация).",
    "Франция, Россия",
    "Франция / RU",
    "США; RUS | Германия",
    "Франция + Россия",
    "Франция & Россия",
    "Франция\nРоссия",
    "Франция · Россия",
    ["Франция", "Россия"],
    ("США", "ru"),
    "Пушкинская карта, Россия",
])
def test_russian_aliases_and_coproductions(country):
    assert countries.country_status(country) == "Russian"


@pytest.mark.parametrize("country", [
    "SU",
    "Soviet Union",
    "СССР",
    "СССР / Франция",
    "Беларусь",
    "Уругвай",
    "Пруссия",
    "RUSSIAN",
    "Франция",
])
def test_non_russian_entries_are_not_substring_matches(country):
    assert countries.country_status(country) == "other"


@pytest.mark.parametrize("country", [None, "", "  ", [], (), " / ; ", 123, "Пушкинская карта"])
def test_missing_country_is_unknown(country):
    assert countries.country_status(country) == "unknown"


def test_fill_uses_existing_title_normalization_and_exact_year():
    rows = [
        _row("source", venue="rodina", title="Ёлки: новые!", year="2025",
             country="Россия"),
        _row("target", title="елки новые", year=2025),
    ]
    extra = _extras(rows)
    assert extra["target"]["country"] == "Россия"
    assert extra["target"]["country_source"] == "window:rodina"
    assert extra["target"]["country_status"] == "Russian"


@pytest.mark.parametrize("second", [
    "Франция; RUS",
    "Франция; RU (Российская Федерация)",
])
def test_country_set_order_separators_and_aliases_do_not_create_conflicts(second):
    rows = [
        _row("a", venue="rodina", year=2025, country="Россия / Франция"),
        _row("b", venue="domkino", year=2025, country=second),
        _row("target", year=2025),
    ]
    extra = _extras(rows)["target"]
    assert extra["country_status"] == "Russian"
    assert extra["country_source"] == "window:rodina"


@pytest.mark.parametrize("second", ["Франция", "Россия, Франция"])
def test_conflicting_country_sets_block_transfer(second):
    rows = [
        _row("a", venue="rodina", year=2025, country="Россия"),
        _row("b", venue="domkino", year=2025, country=second),
        _row("target", year=2025),
    ]
    extra = _extras(rows)
    assert extra["a"]["country"] == "Россия"
    assert extra["b"]["country"] == second
    assert extra["target"]["country_status"] == "unknown"
    assert "country" not in extra["target"]
    assert "country_source" not in extra["target"]


def test_yearless_row_accepts_one_non_conflicting_identity():
    rows = [
        _row("a", venue="rodina", year=2025, country="Франция"),
        _row("b", venue="domkino", year=2025, country="Франция"),
        _row("target"),
    ]
    extra = _extras(rows)["target"]
    assert extra["country"] == "Франция"
    assert extra["country_status"] == "other"
    assert "year" not in extra


def test_yearless_row_rejects_multiple_years_even_with_identical_countries():
    rows = [
        _row("a", venue="rodina", year=1964, country="СССР"),
        _row("b", venue="domkino", year=2025, country="СССР"),
        _row("target"),
    ]
    assert _extras(rows)["target"]["country_status"] == "unknown"


def test_countryless_second_identity_also_blocks_yearless_fill():
    rows = [
        _row("a", venue="rodina", year=1964, country="СССР"),
        _row("b", venue="domkino", year=2025),
        _row("target"),
    ]
    assert _extras(rows)["target"]["country_status"] == "unknown"


def test_dated_row_uses_its_own_year_not_another_remake():
    rows = [
        _row("old", venue="rodina", year=1964, country="СССР"),
        _row("new", venue="domkino", year=2025, country="Россия"),
        _row("target", year=1964),
        _row("different-year", year=1965),
    ]
    extra = _extras(rows)
    assert extra["target"]["country"] == "СССР"
    assert extra["target"]["country_status"] == "other"
    assert extra["different-year"]["country_status"] == "unknown"


def test_yearless_donor_requires_an_unambiguous_dated_identity():
    rows = [
        _row("source", venue="rodina", country="Россия"),
        _row("target", year=2025),
    ]
    assert _extras(rows)["target"]["country_status"] == "Russian"
    rows.append(_row("another-film", venue="domkino", year=1964))
    assert _extras(rows)["target"]["country_status"] == "unknown"


def test_conflicting_yearless_evidence_blocks_dated_transfer():
    rows = [
        _row("dated", venue="rodina", year=2025, country="Россия"),
        _row("undated", venue="domkino", country="Франция"),
        _row("target", year=2025),
    ]
    assert _extras(rows)["target"]["country_status"] == "unknown"


def test_all_yearless_rows_can_share_one_non_conflicting_candidate():
    rows = [
        _row("source", venue="rodina", country="СССР"),
        _row("target"),
    ]
    assert _extras(rows)["target"]["country"] == "СССР"


def test_venue_country_always_wins_and_is_preserved_verbatim():
    rows = [
        _row("source", venue="rodina", year=2025, country="Россия"),
        _row("target", year=2025, country="  Франция / Германия  "),
    ]
    extra = _extras(rows)["target"]
    assert extra["country"] == "  Франция / Германия  "
    assert extra["country_status"] == "other"
    assert "country_source" not in extra


@pytest.mark.parametrize("title", [
    "Фильм: режиссёрская версия",
    "Фильм (субтитры)",
    "Фильмы",
])
def test_no_qualifier_stripping_or_fuzzy_matching(title):
    rows = [
        _row("source", venue="rodina", title="Фильм", year=2025,
             country="Россия"),
        _row("target", title=title, year=2025),
    ]
    assert _extras(rows)["target"]["country_status"] == "unknown"


def test_empty_normalized_titles_never_match():
    rows = [
        _row("source", venue="rodina", title="!!!", country="Россия"),
        _row("target", title="???"),
    ]
    assert _extras(rows)["target"]["country_status"] == "unknown"


def test_enrichment_is_detached_and_does_not_chain_or_mutate_inputs():
    rows = [
        _row("source", venue="rodina", year=2025,
             country=["Россия", "Франция"]),
        _row("target", year=2025),
        _row("unknown", title="Другой фильм"),
    ]
    rows[0].extra["nested"] = {"values": ["original"]}
    before = deepcopy(rows)
    enriched = countries.enrich(rows)

    assert rows == before
    assert all(copy is not original for copy, original in zip(enriched, rows))
    assert all(copy.extra is not original.extra
               for copy, original in zip(enriched, rows))
    assert enriched[1].extra["country_source"] == "window:rodina"

    enriched[1].extra["country"].append("Германия")
    enriched[0].extra["nested"]["values"].append("changed")
    assert rows == before
    assert enriched[0].extra["country"] == ["Россия", "Франция"]


def test_additional_evidence_seam_is_pure_and_respects_venue_country():
    rows = [
        _row("missing", year=2025),
        _row("venue", title="Другой фильм", year=2025, country="СССР"),
    ]
    evidence = [
        CountryEvidence("Фильм", 2025, ["Россия"], "local-detail:1"),
        CountryEvidence("Другой фильм", 2025, "Россия", "local-detail:2"),
    ]
    before_rows, before_evidence = deepcopy(rows), deepcopy(evidence)
    extra = _extras(rows, additional=evidence)

    assert extra["missing"]["country"] == ["Россия"]
    assert extra["missing"]["country_source"] == "local-detail:1"
    assert extra["missing"]["country_status"] == "Russian"
    assert extra["venue"]["country"] == "СССР"
    assert extra["venue"]["country_status"] == "other"
    assert "country_source" not in extra["venue"]
    assert rows == before_rows and evidence == before_evidence


def test_additional_evidence_cannot_bypass_conflicts_or_year_matching():
    rows = [_row("target", year=2025)]
    conflict = [
        CountryEvidence("Фильм", 2025, "Россия", "local:a"),
        CountryEvidence("Фильм", 2025, "Франция", "local:b"),
    ]
    assert _extras(rows, additional=conflict)["target"]["country_status"] == "unknown"
    wrong_year = [CountryEvidence("Фильм", 2024, "Россия", "local:a")]
    assert _extras(rows, additional=wrong_year)["target"]["country_status"] == "unknown"


def test_chip_and_storage_coverage_are_identical_on_every_page():
    pages = render.render_pages(_snapshot([_row("target")]))
    assert pages["index.html"] == pages[f"{TODAY.isoformat()}.html"]
    input_markup = '<input type="checkbox" id="no-russia" class="ctl">'
    allday_label = '<label for="allday" class="chip">весь день</label>'
    country_label = '<label for="no-russia" class="chip"'

    for html in pages.values():
        assert html.count(input_markup) == 1
        assert html.index(input_markup) < html.index("<header>") < html.index("<main>")
        assert allday_label + "\n    " + country_label in html
        assert '>нероссийские</label>' in html
        assert country_label + ' title="' in html
        assert 'aria-label="нероссийские:' in html
        assert '#no-russia:checked ~ header label[for="no-russia"]{color:var(--fg);border-color:var(--fg)}' in html
        assert "var KEY = 'kino.toggles'" in html
        assert "document.querySelectorAll('input.ctl')" in html
        assert "EPHEMERAL = { 'no-russia': true }" in html
        assert "if (i.id in saved && !EPHEMERAL[i.id]) i.checked = !!saved[i.id];" in html
        assert "if (!EPHEMERAL[j.id]) o[j.id] = j.checked;" in html
        assert COUNTRY_HIDE in html
        assert html.count("{display:none!important}") == len(VENUES) + 1
        assert "IntersectionObserver" not in html and "scrollIntoView" not in html


def test_classification_and_cross_day_fill_have_index_per_day_parity():
    tomorrow = TODAY + timedelta(days=1)
    rows = [
        _row("source", venue="rodina", title="Общий фильм", year=2025,
             country="Россия / Франция"),
        _row("target", title="Общий фильм", year=2025, day=tomorrow),
        _row("su", title="Советский фильм", country="СССР"),
        _row("su-next", title="Советский фильм", country="SU", day=tomorrow),
        _row("unknown", title="Неизвестный"),
        _row("unknown-next", title="Неизвестный", day=tomorrow),
    ]
    snapshot = _snapshot(rows)
    before = snapshot.to_json()
    pages = render.render_pages(snapshot)

    for name in ("index.html", f"{tomorrow.isoformat()}.html"):
        html = pages[name]
        assert html.count('data-country-status="Russian">') == 1
        assert html.count('data-country-status="other">') == 1
        assert html.count('data-country-status="unknown">') == 1
        assert "Россия / Франция" in html
        assert COUNTRY_HIDE in html
        assert '[data-country-status="unknown"]{display:none' not in html
        assert '[data-country-status="other"]{display:none' not in html
    assert snapshot.to_json() == before


def test_out_of_window_country_does_not_fill_rendered_rows():
    rows = [
        _row("outside", venue="rodina", year=2025, country="Россия",
             day=TODAY - timedelta(days=1)),
        _row("inside", year=2025),
    ]
    html = render.render(_snapshot(rows))
    assert 'data-country-status="unknown">' in html
    assert 'data-country-status="Russian">' not in html


def test_night_row_uses_its_rendered_window_day_for_enrichment():
    rows = [
        _row("night", venue="rodina", year=2025, country="Россия",
             day=TODAY + timedelta(days=1), hour=1),
        _row("target", year=2025),
    ]
    html = render.render(_snapshot(rows, days=1))
    assert 'class="r night"' in html
    assert html.count('data-country-status="Russian">') == 2


def test_render_country_path_never_invokes_network_resolvers(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("render invoked a network resolver")

    monkeypatch.setattr(posters, "resolve", forbidden)
    monkeypatch.setattr(posters, "fetch", forbidden)
    monkeypatch.setattr(posters, "download_files", forbidden)
    rows = [
        _row("source", venue="rodina", year=2025, country="Россия"),
        _row("target", year=2025),
    ]
    assert render.render(_snapshot(rows)).count('data-country-status="Russian">') == 2


def test_empty_copy_does_not_claim_absence_of_screenings():
    daytime = render.render(_snapshot([_row("day", hour=13)]))
    assert 'class="none none-ev">Проверьте фильтры или включите «весь день».</p>' in daytime
    assert "Вечером сеансов нет" not in daytime
    empty = render.render(_snapshot([]))
    assert 'class="none">Список пуст — возможно, расписание ещё не опубликовано.</p>' in empty
    assert "Сеансов нет ни в одном кинотеатре" not in empty


def test_deliver_keeps_country_enrichment_out_of_snapshot_digest_and_telegram(tmp_path):
    from cinedigest import deliver

    rows = [
        _row("source", venue="rodina", year=2025, country="Россия"),
        _row("target", year=2025),
    ]
    snapshot = _snapshot(rows)
    before = snapshot.to_json()
    telegram_before = deliver.telegram_text(snapshot, page_url=None)

    _, digest_path = deliver.write(snapshot, tmp_path)
    digest = digest_path.read_text(encoding="utf-8")

    assert snapshot.to_json() == before
    assert "country" not in snapshot.screenings[1].extra
    assert "country_source" not in digest and "country_status" not in digest
    assert deliver.telegram_text(snapshot, page_url=None) == telegram_before


@pytest.mark.parametrize("country", [
    ["Россия", "Франция"],
    ("Россия", "Франция"),
])
def test_country_collections_render_as_country_names(country):
    snapshot = _snapshot([_row("target", year=2025, country=country)])
    html = render.render(snapshot)
    assert "2025 · Россия, Франция" in html
