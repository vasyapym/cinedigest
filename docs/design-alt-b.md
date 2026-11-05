<!--
Design alternative B — second specialist reply to Brief 1 (design), received 2026-11-05.
Status: NOT adopted. The adopted design lives in docs/design-v1.md. Kept for the merge decision
and as an alternative counted. Paste start marker preserved for relay history.
-->

=== PASTE START === (original reply kept verbatim below)

# SPb evening-cinema digest — v1 proposal

## 0. In one paragraph

v1 is a **single Python command-line script** with one small adapter per venue. Once a day (10:00 MSK, local cron/Task Scheduler) it fetches the next 7 days from all six sources, normalizes everything into one `Screening` record type, keeps screenings starting at 18:00 or later (plus "киноночь" after-midnight shows, attributed to the previous evening), and writes **one static HTML page** (`out/index.html`, 7 day-sections, all venues merged chronologically) plus a **short Telegram message with today's evening list**. The only state is a folder of raw response snapshots used for debugging and tests; no database, no hosting. The same script moves unchanged to GitHub Actions + Pages in v2 if a one-off geo-probe (included below) shows the six hosts answer from a non-Russian runner.

## 1. Decisions and rationale

### 1.1 Shape: script first, static output, local scheduler

- **Plain script, run on the person's own machine.** Reason: a Russian residential IP is the only *verified* network position; it removes the untested geo-restriction risk entirely, and every step is inspectable (fits the "understand the system" working style).
- **Static HTML + Telegram text, no web app.** Reason: the need is "read a merged list for a chosen day"; a static page covers it with zero runtime, and Telegram gives push + phone access without any hosting.
- **Not CI-first for v1.** Reason: GitHub runners' access to these hosts is untested (several Russian hosts block foreign IPs), Actions cron is imprecise, and remote debugging is a poor first learning loop. CI is v2, gated by a test, with no code changes required (see §6).

### 1.2 Stack

- **Python 3.11+**; dependencies: `requests`, `beautifulsoup4`, `lxml`, `jinja2`, `pytest`. Reason: `zoneinfo` and `datetime.fromisoformat` (with `Z` and `+03:00`) are in the stdlib; this is the smallest, most readable scraping toolkit. (Language is Question #2 — the design is language-neutral.)

### 1.3 Pipeline

```
cron / Task Scheduler, 10:00 MSK ──► python digest.py (also on demand: --date 2026-11-08)
      │
      ┌──────────────┬──────────────┬───┴──────────┬──────────────┬──────────────┐
      │ domkino      │ rodina       │ avrora       │ poravkino    │ lenfilm      │ outcinema
      │ HTML ×7      │ HTML ×7      │ JSON ×7 (+1) │ JSON ×7      │ HTML ×1      │ JSON ×1
      └──────────────┴──────────────┴──────────────┴──────────────┴──────────────┘
                                   ▼
              snapshots/<run-id>/<host>/<url>.{html,json}   raw bodies, replayable
                                   ▼
                    adapters: parse_*(raw) -> list[Screening]
                          tz-aware MSK, rubles, tags, link
                                   ▼
                   select(): start ≥ 18:00 or < 06:00 → digest_day;
                             keep today..today+6; dedupe; sort
                                   ▼
        ┌─────────────────┴───────────────────────┐
  out/index.html (7 days)              Telegram: today's evening + per-venue status
  (bookmarked file:// page)                        out/digest.txt
```

- **Fetch and parse are separate functions in every adapter** (`fetch(days, session) -> VenueResult`, `parse_*(raw, ...) -> list[Screening]`). Reason: parsers are developed and tested against saved fixtures without hitting the sites; this is the main learning loop.
- **~31 HTTP requests per run**, 0.5 s pause between requests to the same host, browser-like UA, 20 s timeout, 2 retries on connection errors/5xx. Reason: one run a day is negligible load; a generic UA is the only configuration verified to work.

### 1.4 Data model

One record type for all venues (code in §5). Fields: `venue`, `start` (aware, Europe/Moscow), `title`, `hall`, `price_min/price_max` (rubles), `tags` (SUB, 3D, спецпоказ, program label, language line…), `url` (tickets/film page when the source gives one), `source_url`. Reason: everything downstream (filter, render, deliver) depends only on this type, so adding a venue never touches rendering.

### 1.5 Horizon and filter semantics

- **Horizon: today + 6 days** (`HORIZON_DAYS = 7`). Reason: the person plans "a chosen day", not just tonight; Out Cinema's feed covers about a week, the others cover more.
- **Evening = start time ≥ 18:00 inclusive, configurable.** Reason: matches the stated habit; one constant to change.
- **Night rule: shows starting 00:00–05:59 belong to the previous evening** (`digest_day = (start − 6h).date()`). Reason: Out Cinema runs «КИНОНОЧЬ» programs; a 00:30 show is tonight's decision, not tomorrow's.
- **No cross-venue film grouping in v1**: chronological list per day with a venue chip. Reason: the question being answered is "what can I go to tonight", which is time-ordered.
- **Dedupe key** `(venue, start, hall, title.casefold())`. Reason: cheap guard against feeds listing the same show in two categories.

### 1.6 Per-venue adapters

| Venue | Fetch (per run) | Parse → `Screening` | Known risks / to verify (§7) |
|---|---|---|---|
| **Дом кино** | `GET /schedule/YYYY/MM/DD/` ×7 | For each hall heading (Большой, Синий, Белый, Сиреневый, Малый) take the following table; rows `Сеанс\|Фильм\|Жанр\|Звук\|Цена`: `HH:MM` + URL date → `start`; film anchor text → `title`, href → `url` (absolutized `/films/<slug>/`); genre → tag; sound → tag if it mentions субтитры; `350 руб.` → `price_min = price_max = 350` | Heading→table association; shape of an empty/far-future day (404 vs empty page) |
| **Родина** | `GET /?date=YYYY/MM/DD&facility=<uuid>` ×7 | Anchors whose href/text match `#YYYY/MM/DD HH:MM` → `start`; nearest enclosing event block → `title` (first heading), markers like `SUB` → tags; `url` = day page + anchor; «Сеансы не найдены» → explicitly empty day | DOM structure unknown yet; whether `facility` is required |
| **Аврора** | shell `GET /` ×1 (token discovery) + `playbill?city_id=2&date=` ×7 | Code in §5: `start_date_time` → MSK; `hall.title`; `price.min/max` kopecks → rubles; `subtitles`→`SUB`, `voiceover`, non-2D formats, age rating → tags; skip seances with `cinema_id ≠ 70` | Price unit; ticket deep-link pattern (`kinowidget.kinoplan.ru/seats/<cinema>/<release>/<seance>`?); whether one call can return a date range |
| **Художественный** (poravkino) | `GET /api/schedule?date=` ×7 | `name` → title; each `performances[]` with `is_active`: `time` (`…Z`, UTC) → MSK; `hall_name` → hall; `price` → rubles; `is3d` → `3D`; `age` → tag; `url` = site root until a film route is confirmed | **UTC assumption is high-impact** (if `Z` is fake, every show shifts +3 h and the evening filter admits 15:00 shows) |
| **Ленфильм** | `GET /service/Kinoteatr-Lenfilm/` ×1 | Table rows `дата, время \| название \| кто представляет \| страна/жанр`: `D.M HH:MM` + inferred year → `start`; title; presenter and country/genre → tags; always add tags `спецпоказ`, `уточнить по тел.`; `url` = the page | Year inference around New Year; page replaced monthly; **only special screenings** (daily repertoire deferred, Question #5) |
| **Out Cinema** | Tilda feed ×1 (`getproductslist`, `Origin: https://outcinema.ru`) | Code in §5: `sku` «4 НОЯБРЯ, 10:45» → `start` (nearest-year rule); products without such sku or linking to `outsight.online` are skipped (courses); `mark` and the language line from `descr` → tags; `КИНОНОЧЬ` part → tag; `buttonlink` → `url`; `price` string → rubles | `total > len(products)` → warning shown in digest (pagination via `slice` untested); forward window ≈ 1 week |

- **Avrora token is re-read from the shell HTML every run, with the last known value as fallback.** Reason: it is a public widget token embedded in the page and can rotate on redeploy; hardcoding would break silently.
- **Rodina keeps the `facility` UUID as a config constant.** Reason: it is the only verified URL; dropping it is a one-line test, not a design question.

### 1.7 Error policy

- Each adapter runs inside `try/except`; a failure becomes `VenueResult.error` and **never aborts the run**. Reason: a personal tool must degrade to "5 venues + one ✗ line", not to nothing.
- The page footer and the Telegram message list per-venue status: `✓ Дом кино · 23 сеанса · ✗ Родина: HTTPError 503 · ⚠ Out Cinema: фид сообщает 20, получено 15`. Reason: the person must know *which* site to open manually.
- Zero screenings from a venue for all 7 days is reported as ⚠, not as success. Reason: the most common scraping failure is a silently changed page that parses to nothing.
- Exit code 0 unless *all* venues failed (then 2). Reason: keeps cron quiet for one flaky site; total failure still surfaces.

### 1.8 State

- **Computation is stateless**; the only persisted things are `snapshots/` (raw bodies per run, prunable after 14 days) and `out/`. Reason: everything is re-derivable from a fresh fetch; a database adds schema/migration concepts before any feature needs them; "what's new since yesterday" can later be a diff of snapshots.
- `--from-snapshots <run-id>` re-renders without network. Reason: fix a parser against the exact bytes that broke it.

### 1.9 Scheduling

- One run daily at **10:00 MSK** (`0 10 * * *` → `cd ~/cinema-digest && .venv/bin/python digest.py >> logs/cron.log 2>&1`; on macOS a launchd agent, on Windows Task Scheduler with "run as soon as possible after a missed start"; on Linux cron or a systemd timer with `Persistent=true`). Reason: a morning digest covers tonight's decision and the week ahead; missed-run catch-up handles a machine that was asleep.
- On-demand: `python digest.py` (week), `--date 2026-11-08` (one day), `--only avrora,rodina`, `--no-telegram`.

### 1.10 Output and reading experience

- **`out/index.html`** (bookmarked `file://` path): sticky day navigation («Сегодня · Завтра · Пт 7.11 · …»), one `<section id="2026-11-05">` per day with a table `Время | Фильм | Кинотеатр · зал | Цена | Пометки`, rows sorted by time, a fixed color chip per venue, night shows rendered as «00:30 (ночь)», footer with per-venue status and generation time. No JavaScript, inline CSS, mobile-width friendly. Reason: a 7-day merged table is the direct replacement for "open six sites".
- **Telegram** (optional; skipped if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are unset): `POST https://api.telegram.org/bot<TOKEN>/sendMessage` with `parse_mode=HTML`, `disable_web_page_preview=true`, split at 4000 chars on line boundaries. Format:
```
🎬 Вечер чт 5 ноя

18:00 Дом кино · Большой — «Название» · 350 ₽
18:30 Аврора · Большой — «Название» · 400–550 ₽ · SUB
19:00 Ленфильм — «Название» · спецпоказ · уточнить по тел.
00:30 Out Cinema — «Название» · 590 ₽ · киноночь · ЗОЛОТОЙ ГОЛЛИВУД

—
✓ Дом кино  ✓ Аврора  ✓ Художественный  ✓ Ленфильм
⚠ Out Cinema (пагинация)   ✗ Родина: HTTPError 503
```
Reason: push + phone access with one HTTPS call and no hosting; it also carries failures to the person's attention.
- **`out/digest.txt`**: the same text for all 7 days. Reason: greppable, diffable, and the Telegram body is just its first section.

### 1.11 Repo layout

```
cinema-digest/
  digest.py            CLI: args → days → run adapters → select → render → deliver → exit code
  config.py            HORIZON_DAYS=7, EVENING_FROM="18:00", NIGHT_UNTIL="06:00",
                       ENABLED_VENUES, dirs, RODINA_FACILITY, Telegram env var names
  models.py            Screening, VenueResult, select(), dedupe() (§5, complete)
  http.py              SnapshotSession(requests.Session): UA, per-host pause, retries,
                       writes every body to snapshots/<run-id>/…, replay mode for --from-snapshots
  venues/__init__.py   VENUES = {"domkino": domkino, "rodina": rodina, ...}
  venues/{domkino,rodina,avrora,poravkino,lenfilm,outcinema}.py   (avrora, outcinema in §5)
  render.py            Jinja2 → index.html; plain-text renderer
  deliver.py           write out/, Telegram send
  templates/digest.html.j2
  tests/fixtures/<venue>/<date>.{html,json}   copied from snapshots
  tests/test_<venue>.py  parse fixture → expected count + one known screening
  .github/workflows/geo-probe.yml   v2 gate (§6)
  README.md            pipeline explanation + "how to add a venue" recipe
```

- Reason for the fixtures/tests layout: "a parser is done when its test passes" gives the learner a concrete definition of done per venue, and tests keep passing offline when sites are down.

## 2. Day-one verification checklist (for the agentic sessions, before parsers are finalized)

A. **Poravkino time semantics** — compare `api/schedule?date=2026-11-05` with the UI for one day; confirm `09:30Z` displays as 12:30. Highest impact on correctness.
A2. **Avrora price unit** — confirm `40000` ↔ «400 руб.» in the UI.
A3. **Avrora ticket link** — test `https://kinowidget.kinoplan.ru/seats/70/<release.id>/<seance.id>` (Out Cinema uses `…/seats/8588/<release>/<seance>` with the same id shapes); if it opens the seat map, use it as `url`.
A4. **Avrora date range** — try `playbill` without `date` or with a range parameter to cut 7 requests to 1.
B. **Rodina** — fetch one day without `facility`; record the DOM path from a `#YYYY/MM/DD HH:MM` anchor to its title and `SUB` marker.
C. **Dom Kino** — confirm how hall headings relate to tables; fetch a date 3 weeks ahead to see the empty-day shape.
D. **Out Cinema** — compare `total` with `len(products)`; if larger, test `&slice=2`; confirm the non-resolving `partuid`.
E. **Lenfilm** — record table markup; check a December fetch for year inference.
F. **Geo-probe from GitHub Actions** (§6) — decides v2.

## 3. Deferred (explicitly not in v1)

- GitHub Actions + GitHub Pages hosting (v2, gated by the geo-probe; same code).
- Lenfilm daily repertoire via `afisha.yandex.ru` (JS-heavy, likely anti-bot, unverified).
- Film metadata enrichment (posters, descriptions, runtime for Dom Kino/Rodina — needs extra fetches); v1 only uses metadata that arrives for free.
- "New since yesterday" diffs, favorites, subtitle-only or genre filters, cross-venue grouping of the same film, ICS calendar export, seat availability (`free_places_count`, `places`), price alerts.
- A second daily run (e.g. 17:00) for same-day changes; smarter retry/backoff; Out Cinema pagination (only a warning in v1).
- Any database, any web app, any user accounts.

## 4. Assumptions

- A computer with Python 3.11+ is on (or wakes) around 10:00 MSK most days, or the person is fine running the command by hand when it isn't.
- The person uses Telegram and can create a bot via BotFather (5 minutes); otherwise the Telegram step is simply left unconfigured.
- Interpretations from the brief hold until the checklist says otherwise: Avrora prices in kopecks; Poravkino `time` is UTC; Out Cinema `sku` dates are the screening dates; `partuids` day attribution matches `sku`.
- One daily run of ~31 requests with a browser UA is acceptable personal use; no ToS was read.
- Rodina and Dom Kino render all needed data server-side without cookies (as verified on 2026-11-04).
- `city_id=2` / `cinema_id=70` remain stable for Avrora; the token may change and is rediscovered each run.

## 5. Code (complete files)

### `models.py`

```python
"""Common data model. Filter, render and deliver depend only on this file."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

EVENING_FROM = time(18, 0)
NIGHT_UNTIL = time(6, 0)

VENUE_NAMES = {
    "domkino": "Дом кино",
    "rodina": "Родина",
    "avrora": "Аврора",
    "poravkino": "Художественный",
    "lenfilm": "Ленфильм",
    "outcinema": "Out Cinema",
}

@dataclass(frozen=True)
class Screening:
    venue: str                       # key of VENUE_NAMES
    start: datetime                  # tz-aware, Europe/Moscow
    title: str
    hall: str | None = None
    price_min: int | None = None     # rubles
    price_max: int | None = None
    tags: tuple[str, ...] = ()       # "SUB", "3D", "спецпоказ", "ЗОЛОТОЙ ГОЛЛИВУД", ...
    url: str | None = None           # tickets or film page when the source gives one
    source_url: str = ""             # page/endpoint this record was parsed from

    @property
    def digest_day(self) -> date:
        """Night screenings (before 06:00) belong to the previous evening."""
        return (self.start - timedelta(hours=6)).date()

    @property
    def is_evening(self) -> bool:
        t = self.start.time()
        return t >= EVENING_FROM or t < NIGHT_UNTIL

@dataclass
class VenueResult:
    venue: str
    screenings: list[Screening] = field(default_factory=list)
    error: str | None = None         # adapter raised; shown as ✗ in the digest
    warning: str | None = None       # adapter succeeded with a caveat; shown as ⚠
    fetched_at: datetime | None = None

def dedupe(screenings: list[Screening]) -> list[Screening]:
    seen: set[tuple] = set()
    out: list[Screening] = []
    for s in sorted(screenings, key=lambda s: (s.start, s.venue, s.title)):
        key = (s.venue, s.start, s.hall, s.title.casefold())
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out

def select(screenings: list[Screening], days: list[date]) -> dict[date, list[Screening]]:
    """Evening screenings grouped by digest day, only for the requested days, chronological."""
    grouped: dict[date, list[Screening]] = {d: [] for d in days}
    for s in dedupe(screenings):
        if s.is_evening and s.digest_day in grouped:
            grouped[s.digest_day].append(s)
    return grouped
```

### `venues/avrora.py`

```python
"""Аврора — Kinoplan 'kinokassa' JSON API behind the KinoSite SPA shell."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import requests

from models import MSK, Screening, VenueResult

VENUE = "avrora"
SITE = "https://avrora.spb.ru/"
CITY_ID = 2
CINEMA_ID = 70

# Last values seen in the shell HTML (2026-11-04). Used only if discovery fails.
FALLBACK_API = "https://kinokassa.kinoplan24.ru"
FALLBACK_TOKEN = "Q4uVHhNkaQiQ1SvI098z5KEtwHT5AQII"


def discover_settings(session: requests.Session) -> tuple[str, str]:
    """The token is a public widget token embedded in the page; re-read it every run
    because it can change on redeploy."""
    try:
        html = session.get(SITE, timeout=20).text
    except requests.RequestException:
        return FALLBACK_API, FALLBACK_TOKEN
    api = re.search(r'window\.kinokassaApiUrl\s*=\s*"([^"]+)"', html)
    token = re.search(r'window\.kinositeSettings\s*=\s*\{[^}]*?token\s*:\s*"([^"]+)"', html)
    return (
        api.group(1).rstrip("/") if api else FALLBACK_API,
        token.group(1) if token else FALLBACK_TOKEN,
    )


def fetch(days: list[date], session: requests.Session) -> VenueResult:
    api, token = discover_settings(session)
    headers = {"X-Application-Token": token, "X-Platform": "widget"}
    screenings: list[Screening] = []
    for day in days:
        url = f"{api}/api/v2/release/playbill?city_id={CITY_ID}&date={day.isoformat()}"
        resp = session.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        screenings.extend(parse_playbill(resp.json(), url))
    return VenueResult(VENUE, screenings=screenings, fetched_at=datetime.now(MSK))


def parse_playbill(data: dict[str, Any], source_url: str) -> list[Screening]:
    out: list[Screening] = []
    for release in data.get("releases") or []:
        title = " ".join(str(release.get("title") or "").split())
        for seance in release.get("seances") or []:
            if seance.get("cinema_id") != CINEMA_ID:
                continue
            start = datetime.fromisoformat(seance["start_date_time"]).astimezone(MSK)
            price = seance.get("price") or {}
            tags: list[str] = []
            if seance.get("subtitles"):
                tags.append("SUB")
            if seance.get("voiceover"):
                tags.append("озвучка: " + _label(seance["voiceover"]))
            for fmt in seance.get("formats") or []:
                if fmt.get("title") and fmt["title"] != "2D":
                    tags.append(str(fmt["title"]))
            if release.get("age_rating"):
                tags.append(str(release["age_rating"]))
            out.append(
                Screening(
                    venue=VENUE,
                    start=start,
                    title=title,
                    hall=(seance.get("hall") or {}).get("title"),
                    price_min=_rubles(price.get("min")),
                    price_max=_rubles(price.get("max")),
                    tags=tuple(tags),
                    url=SITE,  # ticket deep-link pattern not yet verified (checklist A3)
                    source_url=source_url,
                )
            )
    return out


def _rubles(kopecks: int | None) -> int | None:
    # Interpretation to verify (checklist A2): 40000 in the API ↔ "400 руб." in the UI.
    return None if kopecks is None else round(kopecks / 100)


def _label(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("title") or value.get("name") or value)
    return str(value)
```

### `venues/outcinema.py`

```python
"""Out Cinema — Tilda Store catalog; one product == one screening."""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import requests

from models import MSK, Screening, VenueResult

VENUE = "outcinema"
SITE = "https://outcinema.ru"
FEED = (
    "https://store.tildaapi.com/api/getproductslist/"
    "?storepartuid=292580911081&recid=496330277&c=123&getparts=true&getoptions=true"
)

MONTHS = {
    "ЯНВАРЯ": 1, "ФЕВРАЛЯ": 2, "МАРТА": 3, "АПРЕЛЯ": 4, "МАЯ": 5, "ИЮНЯ": 6,
    "ИЮЛЯ": 7, "АВГУСТА": 8, "СЕНТЯБРЯ": 9, "ОКТЯБРЯ": 10, "НОЯБРЯ": 11, "ДЕКАБРЯ": 12,
}
SKU_RE = re.compile(r"^\s*(\d{1,2})\s+([А-ЯЁ]+)\s*,\s*(\d{1,2}):(\d{2})\s*$")
TAG_RE = re.compile(r"<[^>]+>")


def fetch(days: list[date], session: requests.Session) -> VenueResult:
    resp = session.get(FEED, headers={"Origin": SITE}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    today = datetime.now(MSK).date()
    result = VenueResult(
        VENUE,
        screenings=parse_products(data, today=today, source_url=FEED),
        fetched_at=datetime.now(MSK),
    )
    total = int(data.get("total") or 0)
    got = len(data.get("products") or [])
    if total > got:
        result.warning = f"фид сообщает {total} позиций, получено {got} — нужна пагинация (slice)"
    return result


def parse_sku(sku: str, today: date) -> datetime | None:
    """'4 НОЯБРЯ, 10:45' -> aware datetime. The feed never states a year, so take the
    first year (this or next) that does not put the date more than 30 days in the past."""
    m = SKU_RE.match(sku.upper())
    if not m:
        return None
    day, month = int(m.group(1)), MONTHS.get(m.group(2))
    hour, minute = int(m.group(3)), int(m.group(4))
    if month is None:
        return None
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today - timedelta(days=30):
            return datetime(year, month, day, hour, minute, tzinfo=MSK)
    return None


def parse_products(data: dict[str, Any], today: date, source_url: str) -> list[Screening]:
    parts = {str(p.get("uid")): str(p.get("title") or "") for p in data.get("parts") or []}
    out: list[Screening] = []
    for product in data.get("products") or []:
        start = parse_sku(str(product.get("sku") or ""), today)
        if start is None:
            continue  # courses and merch in the same storepart have no "D МЕСЯЦА, HH:MM" sku
        link = product.get("buttonlink") or product.get("url") or None
        if link and "outsight.online" in link:
            continue
        descr_text = html.unescape(TAG_RE.sub("\n", str(product.get("descr") or "")))
        descr_lines = [ln.strip() for ln in descr_text.splitlines() if ln.strip()]
        language = next(
            (ln for ln in descr_lines if "субтитр" in ln.lower() or "язык" in ln.lower()),
            None,
        )
        try:
            part_titles = [parts.get(str(uid), "") for uid in json.loads(product.get("partuids") or "[]")]
        except (json.JSONDecodeError, TypeError):
            part_titles = []
        tags = [str(t) for t in (product.get("mark"), language) if t]
        if any("КИНОНОЧЬ" in t.upper() for t in part_titles):
            tags.append("киноночь")
        price = _rubles(product.get("price"))
        out.append(
            Screening(
                venue=VENUE,
                start=start,
                title=" ".join(str(product.get("title") or "").split()),
                hall=None,
                price_min=price,
                price_max=price,
                tags=tuple(tags),
                url=link,
                source_url=source_url,
            )
        )
    return out


def _rubles(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
```

The remaining four adapters follow the same `fetch(days, session) -> VenueResult` / `parse_*(raw, …)` shape with the rules in §1.6; their parsers must be written against the markup recorded in checklist items B, C, E and the Poravkino JSON (whose keys are fully known from the brief). 

---

## 6. v2 gate: `.github/workflows/geo-probe.yml` (run once by hand)

```yaml
name: geo-probe
on: workflow_dispatch: {}
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - name: Probe the six hosts from a GitHub runner
        run: |
          UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
          DAY="$(date -u +%F)"
          for u in \
            "https://domkino.spb.ru/schedule/" \
            "https://rodinakino.ru/?date=$(date -u +%Y/%m/%d)&facility=3bffd4fc-3d05-480d-aa7c-1d0ebdc578a4" \
            "https://avrora.spb.ru/" \
            "https://poravkino.ru/api/schedule?date=$DAY" \
            "https://www.lenfilm.ru/service/Kinoteatr-Lenfilm/" \
            "https://store.tildaapi.com/api/getproductslist/?storepartuid=292580911081&recid=496330277&c=123&getparts=true&getoptions=true"
          do
            code="$(curl -sS -o /dev/null -w '%{http_code}' -A "$UA" -H 'Origin: https://outcinema.ru' --max-time 20 "$u" || echo FAIL)"
            echo "$code $u"
          done
          code="$(curl -sS -o /dev/null -w '%{http_code}' -A "$UA" \
            -H 'X-Application-Token: Q4uVHhNkaQiQ1SvI098z5KEtwHT5AQII' -H 'X-Platform: widget' --max-time 20 \
            "https://kinokassa.kinoplan24.ru/api/v2/release/playbill?city_id=2&date=$DAY" || echo FAIL)"
          echo "$code kinokassa.kinoplan24.ru playbill"
```

If every line prints `200`, v2 is: the same `digest.py` on a `schedule:` cron, `out/index.html` published to GitHub Pages, Telegram secrets in repository secrets. Nothing in the adapters changes — that is the payoff of the script-first choice.

## 7. Questions back to you, ranked by design impact

1. **Where can it run?** Is there a computer that is on (or wakes) around 10:00 MSK most days, and which OS? A "no" flips v1 to GitHub Actions (after the geo-probe) or a small Russian VPS; the code is unaffected, the scheduling/secrets/hosting sections are.
2. **Which language is the person learning?** Python is assumed; a different answer rewrites all code but none of the design.
3. **Is Telegram an acceptable delivery channel** (creating a bot via BotFather, storing a token)? If not: file-only, or email via SMTP — changes `deliver.py` only.
4. **Decision rhythm:** same-day morning decisions, or planning the week on a specific day? Decides run time (10:00 vs the evening before), whether a second run matters, and whether the Telegram message should cover today only or today + tomorrow.
5. **Lenfilm scope:** is "official special screenings only" acceptable for v1, or is the daily repertoire (Yandex Afisha, riskier scraping) needed from the start?
6. **Evening definition:** is 18:00 inclusive right, do after-midnight shows count as "tonight", and should weekends use an earlier cutoff?
7. **Noise tolerance:** Аврора and Художественный also run mainstream first-run releases; is everything wanted, or should v1 already hide some categories (age rating, genre, dubbed releases)?
8. **Per-screening fields that matter most:** ticket deep links, language/subtitles, price, runtime? This decides whether extra per-film fetches (Dom Kino film pages) are worth adding in v1.1.
9. **Phone access to the full week page** — needed now (pulls hosting forward) or is the Telegram text enough until v2?
