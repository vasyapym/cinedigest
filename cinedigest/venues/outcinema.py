"""Out Cinema (outcinema.ru): витрина Tilda-магазина с билетами Kinoplan."""

from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import date, datetime, timedelta

from .. import config
from ..model import MSK, VENUES, Screening
from . import text_or_none

log = logging.getLogger(__name__)

ID = "outcinema"
NAME = VENUES[ID]
DAILY = True

# Сеанс обязательно ведёт на билетник Kinoplan и имеет sku вида «5 НОЯБРЯ, 15:40».
KINOWIDGET_HOST = "kinowidget.kinoplan.ru"
SKU_RE = re.compile(r"^(\d{1,2}) ([А-ЯЁ]+), (\d{1,2}):(\d{2})$")

# Метки страниц ленты: «products» — page 1, «products-slice2» — page 2 и дальше.
PAGE1_LABEL = "products"

# Бейдж для программ «КИНОНОЧЬ»: сеанс идёт в часах ночи, в дайджесте он остаётся
# вечером предыдущего дня (это делает модель), а здесь он просто получает свой тег.
KINONIGHT_TAG = "киноночь"

# «Английский язык, русские субтитры» — короткая подпись звука и субтитров.
M_LANGUAGE_RE = re.compile(r"[А-ЯЁ][а-яё]+ язык(?:, [а-яё ]+)?")
# «США, 1954, 113 мин., 12+» → страна, год, длительность, возраст.
M_CREDITS_RE = re.compile(r"^(.+?), (\d{4}), (\d+) мин\., (\d+\+)$")

BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]*>")

# Родительный падеж месяцев в sku сеанса → номер месяца.
GENITIVE_MONTHS = {
    "ЯНВАРЯ": 1,
    "ФЕВРАЛЯ": 2,
    "МАРТА": 3,
    "АПРЕЛЯ": 4,
    "МАЯ": 5,
    "ИЮНЯ": 6,
    "ИЮЛЯ": 7,
    "АВГУСТА": 8,
    "СЕНТЯБРЯ": 9,
    "ОКТЯБРЯ": 10,
    "НОЯБРЯ": 11,
    "ДЕКАБРЯ": 12,
}


def feed_url(page: int = 1) -> str:
    """Адрес страницы ленты без летучего параметра c (метка времени)."""
    params = f"storepartuid={config.OUTCINEMA_STOREPARTUID}&recid={config.OUTCINEMA_RECID}"
    if page > 1:
        params += f"&slice={page}"
    return f"{config.OUTCINEMA_PRODUCTS_URL}?{params}"


def fetch(http, days: list[date]) -> list[tuple[str, str]]:
    """Скачать ленту Tilda; если total больше собранного — догоняем страницами slice=2,3,…"""
    raw: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in range(1, config.OUTCINEMA_MAX_PAGES + 1):
        label = PAGE1_LABEL if page == 1 else f"products-slice{page}"
        body = http.get(
            config.OUTCINEMA_PRODUCTS_URL,
            params=_page_params(page),
            headers=_headers(),
            venue=ID,
            label=label,
        )
        raw.append((label, body))
        products, total = _page_products(body)
        if products is None or total is None:
            break  # неожиданная форма ответа — пагинировать не по чему
        for product in products:
            uid = text_or_none(product.get("uid")) if isinstance(product, dict) else None
            if uid is not None:
                seen.add(uid)
        if not products:
            break  # страница пуста — дальше читать нечего
        if len(seen) >= total:
            break  # лента собрана целиком
    return raw


def parse(raw: list[tuple[str, str]], days: list[date], *, now: datetime | None = None) -> list[Screening]:
    """Превратить витрину в сеансы; товары без kinowidget-ссылки или с чужим sku пропускаются."""
    now = now or datetime.now(MSK)
    wanted = set(days)
    part_titles = _part_by_uid(raw)
    seen: set[str] = set()
    out: list[Screening] = []
    for page, (_label, body) in enumerate(raw, start=1):
        products, _total = _page_products(body)
        if products is None:
            continue
        for product in products:
            if not isinstance(product, dict):
                continue
            uid = text_or_none(product.get("uid"))
            if uid is None or uid in seen:
                continue
            seen.add(uid)
            screening = _screening(product, uid, now, part_titles, feed_url(page))
            if screening is None or screening.day not in wanted:
                continue
            out.append(screening)
    return out


def legit_empty(body: str) -> bool:
    """Правильная, но пустая витрина: словарь с пустым списком products — расписания нет вовсе."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    products = data.get("products")
    return isinstance(products, list) and not products


def warning(raw: list[tuple[str, str]]) -> str | None:
    """Оговорка, если в ленте больше товаров, чем удалось скачать постранично."""
    total: int | None = None
    collected = 0
    for _label, body in raw:
        products, page_total = _page_products(body)
        if products is not None:
            collected += len(products)
        if page_total is not None and total is None:
            total = page_total
    if total is not None and total > collected:
        return (
            f"Out Cinema: в ленте {total} товаров, скачалось {collected} — "
            "часть могла не загрузиться, стоит взглянуть на сайт"
        )
    return None


# Разбор одного продукта -------------------------------------------------


def _screening(product: dict, uid: str, now: datetime, part_titles: dict[str, str], source_url: str) -> Screening | None:
    sku = str(product.get("sku") or "").strip()
    link = _kinowidget_link(product)
    why = _skip_reason(link, sku)
    if why is not None:
        log.info("outcinema: продукт %r пропущен: %s", product.get("title"), why)
        return None
    start = _sku_start(SKU_RE.match(sku), now)
    title = text_or_none(product.get("title"))
    if start is None or title is None:
        log.info("outcinema: продукт %r пропущен: sku не превратился в дату и время", product.get("title"))
        return None
    price = _price(product.get("price"))
    lines = _descr_lines(product.get("descr"))
    return Screening(
        venue=ID,
        source_id=uid,
        title=title,
        start=start,
        hall=None,
        price_min=price,
        price_max=price,
        language=_language(lines),
        tags=_tags(product.get("mark"), product.get("partuids"), part_titles),
        url=link,
        source_url=source_url,
        extra=_extra(lines),
    )


def _skip_reason(link: str | None, sku: str) -> str | None:
    """Почему продукт — не сеанс: нет ссылки на билетник или sku непохож на «Д МЕСЯЦ, ЧЧ:ММ»."""
    if link is None:
        return "нет ссылки с kinowidget.kinoplan.ru"
    if not SKU_RE.match(sku):
        return f"sku {sku!r} не похож на «Д МЕСЯЦ, ЧЧ:ММ»"
    return None


def _kinowidget_link(product: dict) -> str | None:
    """Ссылка на билетник Kinoplan: берём buttonlink, при отсутствии — url."""
    for key in ("buttonlink", "url"):
        value = text_or_none(product.get(key))
        if value and KINOWIDGET_HOST in value:
            return value
    return None


def _sku_start(match: re.Match | None, now: datetime) -> datetime | None:
    """«5 НОЯБРЯ, 15:40» → московское datetime ближайшего года.

    Год берём текущий; если такая дата уже далеко позади (больше, чем
    OUTCINEMA_PAST_TOLERANCE_DAYS дней назад) — считаем, что показ в следующем году,
    и второй раз год не двигаем.
    """
    if match is None:
        return None
    day, month_word, hour, minute = int(match.group(1)), match.group(2), int(match.group(3)), int(match.group(4))
    month = GENITIVE_MONTHS.get(month_word)
    if month is None:
        return None
    year = now.year
    past_limit = now - timedelta(days=config.OUTCINEMA_PAST_TOLERANCE_DAYS)
    if datetime(year, month, day, hour, minute, tzinfo=MSK) < past_limit:
        year += 1
    return datetime(year, month, day, hour, minute, tzinfo=MSK)


def _price(value) -> int | None:
    """Строка «590.0000» → 590."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _tags(mark, partuids, part_titles: dict[str, str]) -> tuple[str, ...]:
    """Бейдж-серия из mark плюс «киноночь», если по partuids нашлась часть «КИНОНОЧЬ»."""
    tags: list[str] = []
    name = text_or_none(mark)
    if name:
        tags.append(name)
    for uid in _parsed_uids(partuids):
        title = part_titles.get(uid)
        if title and KINONIGHT_TAG in title.lower() and KINONIGHT_TAG not in tags:
            tags.append(KINONIGHT_TAG)
    return tuple(tags)


def _parsed_uids(partuids) -> list[str]:
    """partuids приходит строкой '[123,456]' — это JSON; что не разобралось, то игнорируем."""
    if isinstance(partuids, list):
        return [str(uid) for uid in partuids if uid is not None]
    if isinstance(partuids, str) and partuids.strip():
        try:
            parsed = json.loads(partuids)
        except ValueError:
            return []
        if isinstance(parsed, list):
            return [str(uid) for uid in parsed if uid is not None]
    return []


def _part_by_uid(raw: list[tuple[str, str]]) -> dict[str, str]:
    """Справочник uid → название части по всем страницам витрины; неразрешённые части игнорируются."""
    table: dict[str, str] = {}
    for _label, body in raw:
        try:
            data = json.loads(body)
        except (TypeError, ValueError):
            continue
        parts = data.get("parts") if isinstance(data, dict) else None
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict):
                uid = text_or_none(part.get("uid"))
                title = text_or_none(part.get("title"))
                if uid is not None and title:
                    table[uid] = title
    return table


# Разбор descr: синопсис, режиссер, «страна, год, длительность, возраст», жанр, звук.


def _descr_lines(descr) -> list[str]:
    """HTML → список строк: <br> — разделитель строк, прочие теги и &nbsp; вычищаются."""
    if not isinstance(descr, str) or not descr:
        return []
    text = BR_RE.sub("\n", descr)
    text = TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _extra(lines: list[str]) -> dict:
    extra: dict = {}
    if lines:
        extra["synopsis"] = lines[0]
    for line in lines:
        if extra.get("director") is None and line.startswith("Режиссер:"):
            extra["director"] = line[len("Режиссер:"):].strip() or None
        credits = M_CREDITS_RE.match(line)
        if credits:
            extra["country"] = credits.group(1).strip()
            extra["year"] = int(credits.group(2))
            extra["duration_min"] = int(credits.group(3))
            extra["age"] = credits.group(4)
        if extra.get("genres") is None and line.startswith("Жанр:"):
            extra["genres"] = line[len("Жанр:"):].strip() or None
    return {key: value for key, value in extra.items() if value is not None}


def _language(lines: list[str]) -> str | None:
    for line in lines:
        if "язык" in line.lower() or "субтитр" in line.lower():
            match = M_LANGUAGE_RE.search(line)
            return match.group(0).strip() if match else line
    return None


# Ответы Tilda -----------------------------------------------------------


def _page_params(page: int) -> dict:
    """Параметры запроса ленты; c — метка времени в миллисекундах."""
    params = {
        "storepartuid": config.OUTCINEMA_STOREPARTUID,
        "recid": config.OUTCINEMA_RECID,
        "c": int(time.time() * 1000),
        "getparts": "true",
        "getoptions": "true",
    }
    if page > 1:
        params["slice"] = page
    return params


def _headers() -> dict:
    return {
        "Origin": config.OUTCINEMA_SITE_URL.rstrip("/"),
        "Referer": config.OUTCINEMA_SITE_URL,
    }


def _page_products(body: str) -> tuple[list | None, int | None]:
    """(список товаров, total) из тела страницы; (None, None), когда тело не похоже на ленту."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    products = data.get("products")
    total = data.get("total")
    return (
        products if isinstance(products, list) else None,
        total if isinstance(total, int) else None,
    )
