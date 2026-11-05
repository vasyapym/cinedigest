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
