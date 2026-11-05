"""Рендер страницы: контекст, жанры, группировка с ночным правилом, лог размера, шаблон."""
from __future__ import annotations

import logging
from datetime import date, datetime

from cinedigest import config, render
from cinedigest.model import MSK, Screening, Snapshot, VenueStatus

TODAY = date(2026, 11, 5)
GEN_AT = datetime(2026, 11, 5, 9, 1, tzinfo=MSK)


def _screening(venue: str, day: date, hour: int, minute: int = 0, title: str = "Фильм",
               **kwargs) -> Screening:
    fields = dict(
        venue=venue,
        source_id=kwargs.pop("source_id", f"{venue}|{day}|{hour}:{minute:02d}|{title}"),
        title=title,
        start=datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK),
    )
    fields.update(kwargs)
    return Screening(**fields)


def _snapshot(screenings: list[Screening], statuses: list[VenueStatus] | None = None,
              *, window_end: date = date(2026, 11, 7)) -> Snapshot:
    if statuses is None:
        statuses = [VenueStatus(venue=v, ok=True, count=0, fetched_at=None) for v in
                    ("domkino", "rodina", "avrora", "poravkino", "lenfilm", "outcinema")]
    return Snapshot(
        generated_at=GEN_AT,
        window_start=TODAY,
        window_end=window_end,
        statuses=statuses,
        screenings=screenings,
    )


def test_context_groups_by_digest_day_and_links_evening():
    evening_show = _screening("domkino", TODAY, 19)
    day_show = _screening("domkino", TODAY, 14)
    # Ночной показ 00:30 следующего календарного дня принадлежит «сегодня» (digest_day),
    # но внутри дня стоит по своему фактическому времени — после 19:00.
    night_show = _screening("outcinema", date(2026, 11, 6), 0, 30, title="Киноночь")
    context = render.render_context(_snapshot([evening_show, day_show, night_show]))

    assert [d for d, _rows in context["days"]] == [TODAY, date(2026, 11, 6), date(2026, 11, 7)]
    first_day = context["days"][0][1]
    assert [(s.title, s.start.strftime("%H:%M")) for s in first_day] == [
        ("Фильм", "14:00"), ("Фильм", "19:00"), ("Киноночь", "00:30"),
    ]
    # Реализм: `evening` — список, не set: Screening с dict-полем extra нехешируем,
    # членство работает по равенству, текст шаблона (`s in evening`) не меняется.
    assert isinstance(context["evening"], list)
    evening_ids = {s.source_id for s in context["evening"]}
    assert evening_show.source_id in evening_ids
    assert night_show.source_id in evening_ids
    assert day_show.source_id not in evening_ids
    assert context["today"] == TODAY
    assert context["json_name"] == "screenings.json"
    assert context["repo_url"] is None


def test_genres_string_is_normalized_to_list():
    outcinema = _screening("outcinema", TODAY, 20, extra={"genres": "боевик, мелодрама, музыка"})
    domkino = _screening("domkino", TODAY, 19, extra={"genres": ["драма"]})
    html = render.render(_snapshot([outcinema, domkino]))
    assert "боевик, мелодрама, музыка" in html
    assert "драма" in html


def test_genres_cap_of_three_applies_after_normalization():
    raw = Screening(
        venue="outcinema",
        source_id="g1",
        title="Лента",
        start=datetime(2026, 11, 5, 20, 0, tzinfo=MSK),
        extra={"genres": "боевик, мелодрама, музыка, нуар"},
    )
    html = render.render(_snapshot([raw]))
    assert "боевик, мелодрама, музыка" in html
    assert "нуар" not in html


def test_empty_and_eveningless_days_render_their_placeholders():
    day_show = _screening("domkino", TODAY, 14)
    html = render.render(_snapshot([day_show]))
    assert "Вечером сеансов нет — есть 1 дневной, включите «весь день»" in html
    assert "Сеансов нет ни в одном кинотеатре" in html  # пустые дни после первого


def test_template_acceptance_full_render():
    evening_show = _screening(
        "domkino", TODAY, 19, title="Сабрина",
        hall="Белый зал", price_min=350, price_max=350,
        extra={"year": 1954, "duration_min": 113, "age": "12+"},
    )
    day_show = _screening("rodina", TODAY, 14, title="Дневной сеанс")
    night_show = _screening("outcinema", date(2026, 11, 6), 0, 30, title="Киноночь")
    statuses = [
        VenueStatus(venue="domkino", ok=True, count=1, fetched_at=None, requests=3, seconds=1.2),
        VenueStatus(venue="rodina", ok=False, count=0, fetched_at=None, error="HTTP 503"),
    ]
    html = render.render(_snapshot([evening_show, day_show, night_show], statuses))

    assert "Кино вечером" in html
    assert "СПб · 6 кинотеатров" in html
    assert "screenings.json" in html
    assert "Сабрина" in html
    assert "Белый зал" in html
    assert "350 ₽" in html
    assert 'class="r day"' in html                      # дневной ряд размечен («весь день» его покажет)
    assert "ночь на " in html                           # ночной бейдж
    assert "недоступен, его сеансов в списке нет" in html  # баннер проблем
    assert "ошибка: HTTP 503" in html                   # статусы в подвале
    assert "3 запр., 1.2 с" in html                     # request/секундная строка для смотрящего в код
    assert 'href="#d-2026-11-06"' in html               # якорь пустого дня


def test_repo_url_env_reaches_the_footer(monkeypatch):
    snapshot = _snapshot([])
    monkeypatch.setenv(config.REPO_URL_ENV, "https://github.com/u/r")
    assert "https://github.com/u/r" in render.render(snapshot)
    monkeypatch.delenv(config.REPO_URL_ENV, raising=False)
    assert "github.com/u/r" not in render.render(snapshot)


def test_size_is_logged_and_warns_at_threshold(caplog, monkeypatch):
    monkeypatch.setattr(config, "RENDER_WARN_BYTES", 10)
    with caplog.at_level(logging.INFO, logger="cinedigest.render"):
        html = render.render(_snapshot([]))
    size = len(html.encode("utf-8"))
    assert f"index.html: {size} bytes" in caplog.text
    assert "page weight budget exceeded" in caplog.text


def test_size_log_info_without_warning_under_threshold(caplog):
    with caplog.at_level(logging.INFO, logger="cinedigest.render"):
        render.render(_snapshot([]))
    assert "page weight budget exceeded" not in caplog.text
    assert "index.html:" in caplog.text
