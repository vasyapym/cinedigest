"""Out Cinema: разбор витрины Tilda, пагинация, границы года и оговорки."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from cinedigest import config
from cinedigest.model import MSK
from cinedigest.venues import outcinema

FIXTURES = Path(__file__).parent / "fixtures" / "outcinema"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=MSK)  # фиксированное «сейчас» на момент снятия витрины
DAYS = [date(2026, 11, 5) + timedelta(days=offset) for offset in range(4)]  # 5–8 ноября

BLOCKBUSTER = "https://kinowidget.kinoplan.ru/seats/8588/10021900/6ae60dc93e0000870007e6fe"

# Пины сняты с сохранённой витрины products.json (id, тайтл, время из sku, цена, серия-бейдж).
EXPECTED = [
    ("732955066741", "ЗАВОРОЖЕННЫЙ", (11, 5, 15, 40), 590, "ХИЧКОК"),
    ("933658672221", "ГЛУБОКИЙ СОН", (11, 5, 18, 0), 630, "НУАР"),
    ("567948228343", "БОГ ЕЙ СУДЬЯ", (11, 5, 20, 15), 660, "FEMME FATALE"),
    ("225419336441", "СТРАХ СЦЕНЫ", (11, 6, 15, 45), 590, "ХИЧКОК"),
    ("547170662601", "СКАЗКИ ТУМАННОЙ ЛУНЫ ПОСЛЕ ДОЖДЯ", (11, 7, 10, 40), 590, "ЯПОНСКАЯ КЛАССИКА"),
    ("533806759191", "ПОХИТИТЕЛИ ВЕЛОСИПЕДОВ", (11, 7, 14, 35), 590, "ИТАЛЬЯНСКИЙ НЕОРЕАЛИЗМ"),
    ("829920782622", "РОККО И ЕГО БРАТЬЯ", (11, 7, 19, 0), 660, "ВИСКОНТИ"),
    ("771485404372", "ВРЕМЯ РАЗВЛЕЧЕНИЙ", (11, 8, 11, 0), 590, "КЛАССИЧЕСКАЯ КОМЕДИЯ"),
    ("509835173402", "КТО БОИТСЯ ВИРДЖИНИИ ВУЛФ?", (11, 8, 13, 30), 590, "ЭЛИЗАБЕТ ТЕЙЛОР"),
    ("484604198822", "БЛЕДНЫЙ ЦВЕТОК", (11, 8, 18, 30), 660, "ЯПОНСКАЯ НОВАЯ ВОЛНА"),
    ("878685404013", "КРИК (ПРЕМЬЕРА)", (11, 8, 20, 35), 690, "АНТОНИОНИ"),
]


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_products_json_yields_exactly_eleven_pin_screenings_in_file_order():
    items = outcinema.parse([("products", _page("products.json"))], DAYS, now=NOW)

    assert len(items) == 11  # витрина тасует 12 товаров: 11 сеансов + 1 онлайн-курс
    for screening, (source_id, title, (month, day, hour, minute), price, mark) in zip(items, EXPECTED):
        assert screening.source_id == source_id
        assert screening.title == title
        assert screening.start == datetime(2026, month, day, hour, minute, tzinfo=MSK)
        assert screening.price_min == screening.price_max == price
    assert [s.tags[0] for s in items] == [e[4] for e in EXPECTED]  # серии идут бейджами в порядке файла
    assert all("АЛЬФРЕД" not in s.title for s in items)


def test_non_screening_hitchcock_is_skipped_with_info_log(caplog):
    with caplog.at_level(logging.INFO, logger="cinedigest.venues.outcinema"):
        items = outcinema.parse([("products", _page("products.json"))], DAYS, now=NOW)

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "АЛЬФРЕД ХИЧКОК" in text  # курс на outsight.online — не сеанс
    assert "kinowidget" in text


def test_first_screening_details():
    screening = outcinema.parse([("products", _page("products.json"))], DAYS, now=NOW)[0]
    assert screening.venue == "outcinema"
    assert screening.url == BLOCKBUSTER  # кнопка билета
    assert screening.source_url == outcinema.feed_url(1)
    assert screening.source_url.startswith(config.OUTCINEMA_PRODUCTS_URL)
    assert screening.title == "ЗАВОРОЖЕННЫЙ"
    assert (screening.price_min, screening.price_max) == (590, 590)
    assert screening.language == "Английский язык, русские субтитры"
    # descr: синопсис, режиссер, «страна, год, длительность, возраст», жанр
    assert screening.extra["synopsis"] == "Детектив Альфреда Хичкока, обращенный к темам психоанализа и девиантного поведения"
    assert screening.extra["director"] == "Альфред Хичкок"
    assert (screening.extra["country"], screening.extra["year"]) == ("США", 1945)
    assert (screening.extra["duration_min"], screening.extra["age"]) == (111, "12+")
    assert screening.extra["genres"] == "фильм-нуар, мелодрама, триллер, детектив"


class FakeHttp:
    """Мини-замена http.Http: отдаёт заготовленные тела по меткам и запоминает запросы."""

    def __init__(self, bodies: dict[tuple[str, str], str]):
        self.bodies = bodies
        self.calls: list[tuple[str, str, str, dict | None, dict | None]] = []
        self.request_count = 0

    def get(self, url, params=None, headers=None, venue="", label=""):
        self.calls.append((venue, label, url, params, headers))
        self.request_count += 1
        return self.bodies[(venue, label)]


def test_fetch_reaches_next_slice_and_stop_on_empty_page():
    data = json.loads(_page("products.json"))
    hungry = json.dumps(dict(data, total=12 + 1), ensure_ascii=False)  # фальшивый total: 13 при 12 товарах
    bodies = {
        ("outcinema", "products"): hungry,
        ("outcinema", "products-slice2"): _page("products-slice2.json"),
    }
    http = FakeHttp(bodies)
    raw = outcinema.fetch(http, DAYS)

    assert [label for label, _body in raw] == ["products", "products-slice2"]  # дальше идти нечего: слайс пуст
    assert len(http.calls) == 2
    first_params, second_params = http.calls[0][3], http.calls[1][3]
    assert "slice" not in first_params
    assert second_params["slice"] == 2
    assert second_params["storepartuid"] == config.OUTCINEMA_STOREPARTUID
    assert second_params["recid"] == config.OUTCINEMA_RECID
    assert http.calls[0][4]["Origin"] == "https://outcinema.ru"
    assert http.calls[0][4]["Referer"] == config.OUTCINEMA_SITE_URL

    # слить обе страницы — те же 11 сеансов (страница 2 ничего не добавила)
    items = outcinema.parse(raw, DAYS, now=NOW)
    assert [s.source_id for s in items] == [e[0] for e in EXPECTED]


def test_fetch_stops_after_one_page_when_feed_is_complete():
    http = FakeHttp({("outcinema", "products"): _page("products.json")})
    raw = outcinema.fetch(http, DAYS)
    assert [label for label, _body in raw] == ["products"]  # total == products
    assert len(http.calls) == 1


def test_merge_dedupes_products_across_pages():
    data = json.loads(_page("products.json"))
    products = data["products"]
    page1 = dict(data, products=products[1:3])                    # два сеанса
    page2 = dict(data, products=[dict(products[1]), products[3]])  # первый — дубль со страницы 1

    raw = [
        ("products", json.dumps(page1, ensure_ascii=False)),
        ("products-slice2", json.dumps(page2, ensure_ascii=False)),
    ]
    items = outcinema.parse(raw, DAYS, now=NOW)
    ids = [s.source_id for s in items]
    assert ids == [str(products[1]["uid"]), str(products[2]["uid"]), str(products[3]["uid"])]
    assert len(ids) == len(set(ids))


def test_year_rolls_forward_for_far_future_sku():
    product = {
        "uid": 1,
        "title": "ТЕСТ РОЛЛОВЕРА",
        "sku": "10 ЯНВАРЯ, 11:00",
        "price": "590.0000",
        "partuids": "[]",
        "buttonlink": BLOCKBUSTER,
        "url": BLOCKBUSTER,
        "descr": "",
    }
    body = json.dumps({"total": 1, "products": [product]})
    items = outcinema.parse([("products", body)], [date(2027, 1, 10)], now=NOW)

    assert len(items) == 1
    assert items[0].start == datetime(2027, 1, 10, 11, 0, tzinfo=MSK)  # январь на фоне ноября → следующий год


def test_recent_promo_date_keeps_current_year():
    product = {
        "uid": 2,
        "title": "СТАРОЕ ПОВТОРЕНИЕ",
        "sku": "10 ОКТЯБРЯ, 21:00",
        "price": "500.0000",
        "partuids": "[]",
        "buttonlink": BLOCKBUSTER,
        "url": BLOCKBUSTER,
        "descr": "",
    }
    body = json.dumps({"total": 1, "products": [product]})
    items = outcinema.parse([("products", body)], [date(2026, 10, 10)], now=NOW)

    assert len(items) == 1
    assert items[0].start == datetime(2026, 10, 10, 21, 0, tzinfo=MSK)  # прошло меньше 60 дней — год не двигаем


def test_kinonight_part_adds_tag():
    data = json.loads(_page("products.json"))
    night_show = {
        "uid": 1010,
        "title": "КИНОНОЧЬ: НУАР-ПРОГРАММА",
        "sku": "14 НОЯБРЯ, 00:30",
        "price": "590.0000",
        "mark": "СПЕЦПОКАЗ",
        "partuids": "[872220997851, 123]",  # 872220997851 = «КИНОНОЧЬ» в parts витрины, 123 не разрешится
        "buttonlink": BLOCKBUSTER,
        "url": BLOCKBUSTER,
        "descr": "Ночь короткого метра",
    }
    body = json.dumps(dict(data, products=[night_show]), ensure_ascii=False)
    items = outcinema.parse([("products", body)], [date(2026, 11, 14)], now=NOW)

    assert len(items) == 1
    assert items[0].tags == ("СПЕЦПОКАЗ", "киноночь")  # серия + разрешённая часть
    assert items[0].day == date(2026, 11, 14)  # в данных сеанс остаётся 14-м числом


def test_legit_empty_shapes():
    assert outcinema.legit_empty('{"products": [], "total": 0}') is True
    assert outcinema.legit_empty('{"total": 12}') is False  # нет списка products
    assert outcinema.legit_empty("[]") is False
    assert outcinema.legit_empty("FFFFFF") is False


def test_warning_when_total_exceeds_collected():
    data = json.loads(_page("products.json"))
    assert outcinema.warning([("products", json.dumps(data, ensure_ascii=False))]) is None

    doctored = dict(data, products=data["products"][:11])  # total=12, скачалось 11
    message = outcinema.warning([("products", json.dumps(doctored, ensure_ascii=False))])
    assert isinstance(message, str) and message

    sliced = dict(data, products=[])  # пустой доп. слайс не портит итог
    assert outcinema.warning([
        ("products", json.dumps(doctored, ensure_ascii=False)),
        ("products-slice2", json.dumps(sliced, ensure_ascii=False)),
    ]) == message
