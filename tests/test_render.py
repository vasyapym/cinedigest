"""Страницы по дням, бейдж площадки, постеры и атрибуция TMDB, удаление страниц вне окна."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from cinedigest import config, deliver, posters, render
from cinedigest.model import MSK, Screening, Snapshot, VenueStatus, VENUES

TODAY = date(2026, 11, 5)
GENERATED = datetime(2026, 11, 5, 9, 2, tzinfo=MSK)
NOTICE = "This website uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB."


def _s(venue, title, day, hour, minute=0, hall=None, year=None, url=None):
    extra = {"year": year} if year else {}
    return Screening(venue=venue, source_id=f"{venue}-{title}-{day}-{hour}", title=title,
                     start=datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK),
                     hall=hall, url=url, extra=extra)


def _snapshot(days=7):
    d0, d1 = TODAY, TODAY + timedelta(days=1)
    rows = [
        _s("poravkino", "Морозко", d0, 18, hall="Малый красный зал", year=1964),
        _s("mirage", "Морозко", d0, 18, hall="1", year=1964, url="https://www.mirage.ru/ticket_new/abc/"),
        _s("rodina", "Лето в Бадене", d0, 20, 30, year=2025, url="https://rodinakino.ru/events/leto"),
        _s("avrora", "Битва моторов", d1, 19, year=2025),
    ]
    statuses = [VenueStatus(venue=k, ok=True, count=1, fetched_at=GENERATED) for k in VENUES]
    return Snapshot(generated_at=GENERATED, window_start=TODAY, window_end=TODAY + timedelta(days=days - 1),
                    statuses=statuses, screenings=rows)


def test_one_page_per_day_plus_index():
    pages = render.render_pages(_snapshot())
    assert set(pages) == {"index.html"} | {f"2026-11-{d:02d}.html" for d in range(5, 12)}
    assert pages["index.html"] == pages["2026-11-05.html"]
    assert render.render(_snapshot()) == pages["index.html"]


def test_page_shows_only_its_day_and_links_the_others():
    pages = render.render_pages(_snapshot())
    index, tomorrow = pages["index.html"], pages["2026-11-06.html"]
    assert 'id="d-2026-11-05"' in index and 'id="d-2026-11-06"' not in index
    assert 'id="d-2026-11-06"' in tomorrow and "Битва моторов" in tomorrow and "Морозко" not in tomorrow
    assert 'href="index.html" aria-current="page"' in index
    assert 'href="2026-11-06.html" aria-current="page"' in tomorrow
    assert 'href="2026-11-06.html">Завтра →' in index and 'href="index.html">← Сегодня' in tomorrow
    assert "<title>Кино вечером · СПб · пт 6 ноября</title>" in tomorrow


def test_venue_badge_precedes_title_and_carries_hall():
    html = render.render(_snapshot())
    mirage = html.index('class="v v-mirage"')
    assert html[mirage:].index("Мираж на Большом") < html[mirage:].index("Морозко")
    assert '<a class="v v-mirage" href="https://www.mirage.ru/ticket_new/abc/">Мираж на Большом</a>' in html
    assert '<span class="v v-poravkino">Художественный</span>' in html
    assert '<span class="h">зал 1</span>' in html and '<span class="h">Малый красный зал</span>' in html
    assert 'class="chip vc v-mirage"' in html
    assert ".v-mirage{--vc:var(--c-mirage)}" in html


def test_filter_css_and_data_attributes_survive():
    html = render.render(_snapshot())
    for k in VENUES:
        assert f'#v-{k}:not(:checked) ~ main .r[data-v="{k}"]{{display:none}}' in html
    assert 'data-v="mirage"' in html and 'id="allday"' in html


def test_posters_render_with_exact_attribution():
    urls = {"морозко|1964": f"{config.TMDB_IMAGE_BASE_URL}w185/m.jpg"}
    html = render.render(_snapshot(), urls)
    assert html.count('<img class="p" src="https://image.tmdb.org/t/p/w185/m.jpg" alt="" width="46" height="69" loading="lazy" decoding="async">') == 2
    assert NOTICE in html
    assert f'<a href="{config.TMDB_SITE_URL}"><img src="tmdb.svg" alt="TMDB"></a>' in html
    plain = render.render(_snapshot())
    assert NOTICE not in plain and 'class="p"' not in plain and "Лето в Бадене" in plain


def test_jump_and_observer_js_are_gone():
    html = render.render(_snapshot())
    assert "IntersectionObserver" not in html and "scrollIntoView" not in html
    assert "kino.toggles" in html and "classList.toggle('past'" in html and "generatedHuman" in html


def test_write_creates_day_pages_prunes_old_ones_and_uses_cache(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "2026-10-01.html").write_text("old", encoding="utf-8")
    (docs / "notes.html").write_text("keep", encoding="utf-8")
    posters.save_cache(docs / config.POSTERS_FILENAME,
                       {"морозко|1964": {"tmdb_id": 1, "poster_path": "/m.jpg", "resolved_at": "2026-11-05"}}, TODAY)
    (docs / config.POSTER_OVERRIDES_FILENAME).write_text(json.dumps({"Лето в Бадене|2025": {"poster_path": "/l.jpg"}}),
                                                         encoding="utf-8")
    html_path, digest_path = deliver.write(_snapshot(), tmp_path)
    assert html_path == docs / "index.html" and digest_path.is_file()
    assert not (docs / "2026-10-01.html").exists() and (docs / "notes.html").exists()
    assert all((docs / f"2026-11-{d:02d}.html").is_file() for d in range(5, 12))
    index = html_path.read_text(encoding="utf-8")
    assert "/w185/m.jpg" in index and "/w185/l.jpg" in index and NOTICE in index
    digest = digest_path.read_text(encoding="utf-8")
    assert "image.tmdb.org" not in digest and "TMDB" not in digest


def test_real_snapshot_pages_fit_the_budget():
    path = Path(__file__).resolve().parents[1] / "docs" / "screenings.json"
    if not path.is_file():
        pytest.skip("no committed snapshot")
    from cinedigest.pipeline import load_snapshot
    pages = render.render_pages(load_snapshot(path), {"x|1": "https://image.tmdb.org/t/p/w185/x.jpg"})
    for name, html in pages.items():
        assert len(html.encode("utf-8")) < config.RENDER_WARN_BYTES, name
