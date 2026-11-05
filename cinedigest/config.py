"""Every adopted constant of the cinedigest engine in one place."""
from __future__ import annotations

# The evening cut and the night boundary are defined by the model (v1.1) and re-exported here
# so that callers have a single import point for every tunable.
from .model import EVENING_FROM, NIGHT_UNTIL  # noqa: F401

# Window and staleness
WINDOW_DAYS = 7
STALE_MAX_AGE_HOURS = 72

# Politeness
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
ACCEPT_LANGUAGE = "ru"
MIN_HOST_PAUSE_SECONDS = 0.7
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 20.0
RETRIES = 3
BACKOFF_SECONDS = (1.0, 2.0, 4.0)

# Output layout, relative to the output directory handed to the pipeline
DOCS_DIRNAME = "docs"
SCREENINGS_FILENAME = "screenings.json"
STATUS_FILENAME = "status.json"
SNAPSHOTS_DIRNAME = "snapshots"
RUN_ID_FORMAT = "%Y%m%dT%H%M%S"

# poravkino — Художественный
PORAVKINO_SITE_URL = "https://poravkino.ru/"
PORAVKINO_SCHEDULE_URL = "https://poravkino.ru/api/schedule"

# avrora — Аврора (Kinoplan kinokassa API)
AVRORA_SITE_URL = "https://avrora.spb.ru/"
AVRORA_API_FALLBACK = "https://kinokassa.kinoplan24.ru"
AVRORA_TOKEN_FALLBACK = "Q4uVHhNkaQiQ1SvI098z5KEtwHT5AQII"
AVRORA_CITY_ID = 2
AVRORA_CINEMA_ID = 70

# outcinema — Out Cinema (Tilda store)
OUTCINEMA_SITE_URL = "https://outcinema.ru/"
OUTCINEMA_PRODUCTS_URL = "https://store.tildaapi.com/api/getproductslist/"
OUTCINEMA_STOREPARTUID = "292580911081"
OUTCINEMA_RECID = "496330277"
OUTCINEMA_MAX_PAGES = 10
OUTCINEMA_PAST_TOLERANCE_DAYS = 60

# stage 2 — domkino — Дом кино (domkino.spb.ru)
# Per-day schedule: {DOMKINO_SITE_URL}schedule/{Y}/{M}/{D}/ — build the path with
# day.strftime("%Y/%m/%d") (zero-padded month and day). The www. host is required:
# the apex without it answers 301.
DOMKINO_SITE_URL = "https://www.domkino.spb.ru/"

# stage 2 — rodina — Родина (rodinakino.ru, platform p24.app)
# Per-day page: {RODINA_SITE_URL}?date={Y}/{M}/{D} — slashes in the query date.
# The `facility` parameter is NOT required (validated 2026-11-05: with and without
# facility the page renders the same show-times).
RODINA_SITE_URL = "https://rodinakino.ru/"
# Per-film pages {RODINA_SITE_URL}events/<slug> (schema.org Movie microdata): fetched once per
# distinct film with a seance inside the window, best-effort, bounded.
RODINA_MAX_EVENT_PAGES = 60
# After this many failed film pages the remaining ones are skipped for the run.
RODINA_EVENT_FAILURE_LIMIT = 3

# stage 4 — mirage — Мираж на Большом (www.mirage.ru; the apex 301-redirects to www)
# City-wide per-day page: {MIRAGE_SITE_URL}spb/schedule/{DD.MM.YYYY}/ — all SPb branches on
# one page; the adapter keeps the block of one branch only (picked by id, name as fallback).
MIRAGE_SITE_URL = "https://www.mirage.ru/"
MIRAGE_BRANCH_ID = 1
MIRAGE_BRANCH_NAME = "НА БОЛЬШОМ"

# stage 2B — lenfilm — Ленфильм (kinokassa / KinoPlan playbill feed, cinema 2387)
# KINOKASSA_API_URL repeats the AVRORA_API_FALLBACK value on purpose: avrora and
# lenfilm run the same kinokassa engine, the shared parser is parameterized by
# cinema id (avrora 70, lenfilm 2387).
KINOKASSA_API_URL = "https://kinokassa.kinoplan24.ru"
# Every lenfilm screening links here; per-seance purchase URLs are not verified.
LENFILM_SITE_URL = "https://www.lenfilm.ru/service/Kinoteatr-Lenfilm/"
LENFILM_CINEMA_ID = 2387

# stage 3 — render and delivery
# index.html byte budget: log.info the size, log.warning at the threshold.
RENDER_WARN_BYTES = 400 * 1024
# Telegram push (both env names must be set; otherwise the push is skipped).
TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"
# Optional trailing URL of the rendered page in the Telegram message.
PAGE_URL_ENV = "CINEDIGEST_PAGE_URL"
# Optional «код» link in the page footer.
REPO_URL_ENV = "CINEDIGEST_REPO_URL"
