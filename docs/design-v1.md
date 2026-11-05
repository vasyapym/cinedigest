# cinedigest — v1 design (adopted)

Принято оркестратором 2026-11-05 по ответу специалиста на Бриф 1.
Статус: принят как рабочий контракт; корректировки валидацией — см. «Adoption status».
Оригинальный ответ: чат специалиста, 2026-11-05; ниже — почти дословно.

## Adoption status (validation addendum, 2026-11-05)

Проверки сабагентом (curl с локальной машины, СПб):

- **Дом Кино**: `domkino.spb.ru` отдаёт 301 на `www.domkino.spb.ru` (без `-L` — учитывать; в коде использовать `www.host` напрямую). Дальняя дата (`/schedule/2027/01/10/`) — это **не 404**, а HTTP 200 со страницей-оболочкой (11 422 B) без единого заголовка зала → легитимная форма «пустого дня». Заголовки залов (Большой/Синий/Белый/Сиреневый/Малый) присутствуют все 5.
- **Родина**: параметр `facility` **не требуется** (варианты с/без facility — идентичный рендер, 50 show-time, 185 вхождений даты; UUID всё равно вшит серверно в payload) → URL упрощается до `?date=YYYY/MM/DD`.
- **АВрора**: интерпретация «копейки» подтверждена по всему файлу дня (40000/55000/35000/45000…; \(min:40000,max:55000) → 400/550 ₽). Прямая проверка «UI ↔ API» из статики невозможна: `kinowidget.kinoplan.ru/seats/70/{release}/{seance}` возвращает 809-байтовую SPA-оболочку (клиентский рендер, цен в HTML нет). Держим как закреплённое тестом допущение. Файл дня 2026-11-06: 15 releases, 9 сеансов, все `cinema_id=70`, время 11:00–21:50 +03:00.
- **ПоравКино**: времена — UTC (19:00Z → 22:00 МСК — вечерний сеанс; диапазоны правдоподобны); пересечений id между соседними дневными корзинами нет (0); **параметр `date` обязателен** (без него HTTP 400 `{"error":"wrong date"}`).
- **Out Cinema**: свежий фид — `total=12`, 11 сеансов (5–8 ноября) + 1 не-сеанс (АЛЬФРЕД ХИЧКОК, `ОНЛАЙН-КУРС`, url → outsight.online); правило отбора (kinowidget-url + sku «D МЕСЯЦ, HH:MM») подтверждено на новых данных; `slice=2` возвращает пустую страницу при неизменном total → пагинация существует, текущие ленты хватает без неё.
- **partuids→parts**: родительский uid (603800317431) в списке parts не резолвится (повторилось и 4, и 5 ноября); привязка к дням через резолвящиеся части совпала с датой из `sku` в 100% случаев.
- **Решения человека (2026-11-05)**: язык — Python; репозиторий — публичный (GitHub + Pages OK); дефолты D6/§5/§9 приняты; **исключение — Lenfilm (разрешено 2026-11-05 фоновым сабагентом)**: полный суточный график найден и воспроизводится curl'ом. Страница embed'ит iframe `https://kinowidget.kinoplan.ru/2387` (та же Kinoplan-Kinokassa платформа, что у Авроры;inema 2387). Проверенные вызовы: `GET /api/v2/app?with_cities=true&cinema_id=2387` → `{title:"Ленфильм, Санкт-Петербург", cinemas:[{id:2387, …}], time_zone:3, token:<>}`; заголовок `X-Platform: WIDGET` обязателен (без него HTTP 400 «Invalid headers»); `GET /api/v2/release/playbill/info?cinema_id=2387` → список дат (реальный ключ `calendar.seance_dates`; 21 дата в 2026-11, дыры 13, 16–18 и 23); `GET /api/v2/release/playbill?cinema_id=2387&date=YYYY-MM-DD` → полная программа дня, структура сеанса идентична Авроровской (id, hall.title, start_date_time `+03:00`, price в копейках, free_places_count, subtitles/voiceover). Спец-показы из HTML-таблицы приходят и в фиде (дат/времена совпали по 11 строкам); текст «кто представляет» существует только в HTML-таблице — кросс-ref опционален. Fixtures: `tests/fixtures/lenfilm/feed-1-app.json`, `feed-3-playbill-info.json`, `feed-4…feed-25-playbill-<дата>.json`. До включения фида в адаптер спец-таблица остаётся fallback-источником.

Плановый расклад этапов сборки (по §7.3, консолидировано):

- **Бриф 2** (vault `2-…`, target: mechanical) — ядро: model/http/config/pipeline + три JSON-адаптера (poravkino, avrora, outcinema) + офлайн-тесты.
- **Бриф 3** — HTML-адаптеры (domkino, rodina) + lenfilm (спецтаблица и, если фид найден, полный суточный источник) + their tests.
- **Бриф 4** — страница (template/render), CLI `render`, workflows (digest.yml, probe.yml), GitHub Pages, первый прогон и глазная сверка.

Репозиторий: `/Users/vasilij/Documents/cinedigest` (создан; fixtures уже внутри; git инициализируется при первом код-коммите).

### Merge addendum — design v1.1 (2026-11-05, «объединить лучшее»)

Вторая дизайнерская пропозиция (`docs/design-alt-b.md`) частично принята; каркас v1.0 остаётся базой (Actions+Pages primary, 09:00 МСК, stale carry-over, suspicious-zero). Впитано из alt-B:

- **Ночное правило**: сеансы 00:00–05:59 относятся к предыдущему вечеру (`digest_day = start − 6h`) — «КИНОНОЧЬ» Out Cinema попадает на «сегодняшний вечер».
- **Модель v1.1** (блок §3 заменён целиком): + `tags` (только отображаемые бейджи), + `source_url`, свойства `digest_day`/`is_evening`; `special: bool` упразднён (= тег «спецпоказ»); `dedupe()` по `(venue, source_id)` и `select()` переехали в модель — единственное место, где применяется вечерний фильтр; snapshot по-прежнему хранит ВСЕ сеансы окна.
- **VenueStatus + `warning`** — адаптер отработал с оговоркой (пример: Out Cinema `total > len(products)`).
- **Архив сырых ответов `snapshots/<run-id>/<venue>/<label>`** — пишется http-слоем каждый прогон (ретеншн 14 дней), заменяет точечные debug-дампы; на нём же основан будущий `--from-snapshots`.
- **Telegram в v1 (опционально по env)**: «сегодняшний вечер» + статусы площадок; телеграм-сообщение — первая секция `docs/digest.txt`.
- **CLI-флаги (этап 4)**: `--date YYYY-MM-DD`, `--only v1,v2`, `--no-telegram`, `--from-snapshots <run-id>`.
- **Семантика тегов по площадкам**: avrora/lenfilm — не-2D форматы → тег; poravkino — is3d → тег; outcinema — mark + «киноночь» → теги; domkino/rodina — только `language` (SUB/звук), без тегов; «спецпоказ» — только HTML-таблица-fallback Ленфильма.
- Отклонённые части alt-B: локальный планировщик как primary (остаётся fallback для недоступных Actions), `file://` как основная поверхность (страница Pages остаётся primary), 10:00 вместо 09:00 (дефолт 09:00 подтверждён человеком), Ленфильм «только спецпоказы» и «facility проверить» (оба закрыты валидацией).

### Stage-2 integration notes (2026-11-05 evening)

Implemented by warehouse subagents (parts A/B); full suite `75 passed` (40 stage-1 + 16 domkino/rodina + 8 kinokassa + 11 lenfilm), avrora tests untouched by the refactor.

- **Part A**: `venues/domkino.py` + `venues/rodina.py`; `beautifulsoup4+lxml` added. Fixture pins: domkino 2026-11-06 → 30 screenings (six rows per each of the five hall tables; `<h3>` «… зал» → tables, film-card blocks interleaved; the far-future shell is a legit empty day). Rodina 2026-11-07 → 49 unique screenings (50 anchors, one slider-gallery duplicate deduped; the facility-less variant parses identically). Rodina «Сеансы не найдены» is also embedded as i18n text on busy pages — the legitimacy check ignores script/style/noscript. «350/200» → 350.
- **Part B**: shared `venues/kinokassa.parse_playbill(data, days, *, cinema_id, venue, url, source_url, label)`; avrora delegates (268→91 lines) with its public surface unchanged. Lenfilm: token bootstrapped from `/app` (real key `calendar.seance_dates` caps day queries); when the venue's dates and the window do not intersect, `fetch` appends a literal marker pair — label `empty-window`, body `{"lenfilm_window_empty": true}` — and its `legit_empty` blesses exactly that marker (a broken schedule never masquerades as an empty day; a real broken `calendar` keeps the venue down).
- **Kinoplan quirk recorded**: subtitle info may ride in `formats` as a "SUB" pseudo-format with `subtitles/voiceover` null → "SUB" lands in `tags` (non-2D-format rule), `language` stays null; the renderer folds both into one SUB chip.
- **Stage-3 candidates**: rodina hall labels («Большой зал», «Малый 2 зал») exist in markup but are intentionally unused — plugin into `hall` if the page layout wants halls; unify outcinema `extra.genres` (string) with the list shape used elsewhere at render.
- **Second stage-2 opinion Mined (chat specialist; arrived after integration, written blind to the repo — its §0 touchpoints assumed a `Snapshot(label,url,body)` type, `http.get` returning bytes bodies, `Screening.price`, `MSK` in config and different fixture filenames; implementation rejected wholesale). Mined for the record:** (1) rodina overshoot guard — when the climbed event block holds more than one heading, take the anchor's nearest PRECEDING heading instead of the block's first; candidate hardening for stage 3 (only with a fixture-based test). (2) rodina hall extraction from adjacent «… зал» text — supports the existing stage-3 candidate above. (3) dom kino language normalization («субтитр» → "SUB", plain dubbing → None) — rejected for v1: the adopted contract keeps the «Звук» wording verbatim; any normalization belongs at render. (4) lenfilm window-level legit-empty ("info parsed AND zero playbills requested") — an alternative to our explicit `empty-window` marker; not adopted: the frozen pipeline checks `legit_empty` per body, and the marker keeps fetched-but-empty days clearly suspicious.

### Stage-3 design ADOPTED (2026-11-05; full template + text renderer live in `docs/stage3-design-adopted.md`)

All 10 design decisions and the Jinja2/`render_text.py` skeletons were accepted, with these engine-reality reconciliations and adjudications (facts — the specialist's Q-verdicts):

- Q1: `select(..., evening_only=False)` already applies the night rule (grouping is by `digest_day`) — the template's dual-context trick (all rows + an `evening` set) is valid as-is. Q2: stale ⇒ `ok=False` with the carried count; the ✗/⚠ glyph logic matches `_carry_over` realities. Q3: `fetched_at` reaches render as an aware MSK object (ISO only inside JSON files). Q4: Telegram's trailing page URL is opt-in (`CINEDIGEST_PAGE_URL` env / param), omitted until Pages exists. Q5: no «субтитры only» chip in v1. Q6: **rodina halls ARE added at stage 3** (engine-side, one-line parse from adjacent «… зал» text + fixture pin updates; the page already renders `hall` if present). Q7: `is_pushkin` stays unshown. Q8: Telegram stays plain text (no `parse_mode`). Q9: chips keep full venue names (the nav row scrolls).
- Pivots accepted: CSS-only toggles (JS only persists + dims + scrolls); honest link mapping (title link ⇔ film/ticket URL: domkino/rodina/outcinema; venue schedule URL renders on the venue name for poravkino/avrora/lenfilm); top-of-page problem banner + «page built yesterday» device-date banner; Telegram composed separately from digest.txt (shared row formatter; compact statuses; no per-row URLs; blank-line-preferred `(i/n)` split); `free_places` only ≤ 50; `synopsis` in `<details>`; SUB pseudo-format folded into «субтитры»; explicit «ночь на чт» badge.
- Mechanics deltas (implementing session notes): imports `engine` → `cinedigest.*`; render context normalizes `extra.genres` (str → split commas) because outcinema stores a string (known stage-2 note — unify at render, adapter untouched); module layout `render.py` (page + context + size log, warn ≥ 400 KB), `render_text.py` (digest/telegram/split), `deliver.py` (files + Telegram post), `cli.py` (`run` with `--days/--date/--out/--only/--no-telegram/--print`, `render`, `fetch --(save)`), config adds `RENDER_WARN_BYTES`, `TELEGRAM_*`/`CINEDIGEST_PAGE_URL`/`CINEDIGEST_REPO_URL` env names; workflows from the adopted design (`digest.yml` 09:00 MSK cron + commit + artifact + exit-code policy, `probe.yml` extended with the lenfilm `/app`-выведенным токен-проверкой); rodina hall extraction adjusts the 3 pinned rows if the fixture supports it (count stays 49; if the markup proves unreliable — revert to None and report).

### Stage-3 mechanics OUTCOME (2026-11-05 late)

Delivered by the warehouse subagent + one orchestrator patch; suite `123 passed` (75 stage-1 + 16 domkino/rodina + 8 kinokassa + 11 lenfilm + 46 stage-3 + 2 http-posture).

- Built: `render.py`, `render_text.py`, `deliver.py`, `cli.py`/`__main__.py`, `templates/index.html.j2`, `.github/workflows/{digest,probe}.yml`, `README.md`; `render_text.py` matches the adopted skeleton; the page template is byte-identical to the adopted §2 except sanctioned comment trimming.
- **Live smoke (real network, 3-day window)**: rodina 51, avrora 31, poravkino 56, lenfilm 15 (token bootstrapped), outcinema 7, and **domkino failed with `SSLError: DH_KEY_TOO_SMALL`** — the venue's TLS offers weak DH keys; OpenSSL 3.x (python 3.13, and presumably the Actions runners) rejects the handshake at the default security level, while the earlier probing system curl (macOS LibreSSL) tolerated it. Orchestrator patch: a `_WeakDHAdapter` (SSLContext `set_ciphers("DEFAULT@SECLEVEL=1")`) mounted ONLY for the domkino hosts in `cinedigest/http.py` — the other five venues keep the strict default posture. Verified live: domkino fetch + parse now yields 30 rows for 2026-11-06 (matching the frozen fixture), and the far-future empty shell is `legit_empty=True` both live and in the fixture.
- Live artifacts: page `index.html` 84 414 B (≤ budget; render warns ≥ 400 KB), `digest.txt` 9 325 B, snapshots written, `render` subcommand rebuilds byte-stable output from the saved snapshot, Telegram step correctly skipped when env is unset.
- Known notes from the mechanic: the CLI swaps `pipeline.window` for `--date/--days` (window parameter was not in the frozen engine — try/finally, tested); the workflow uses `run --out .` (the engine nests `docs/` under the out-dir, `--out docs` would double-nest); `--print` prints the full Telegram body; probe.yml holds one line per host (domkino www, rodina無 facility, poravkino/avrora/outcinema/lenfilm `/app` probe with `X-Platform: widget`, expecting a 200 + a `token` substring); live rodina halls: 15/49 rows carry a hall («Большой зал» 5, «Малый 1 зал» 6, «Малый 2 зал» 4), slider duplicates rely on a `(start, title)` re-key inside the adapter since synthetic_id now includes hall.
- **Bug fixed after the first human read (2026-11-05 night)**: the «весь день» toggle was ineffective — the `.day{display:none}` rule lost the CSS cascade to the later same-specificity `.r{display:grid}` rule, so daytime rows were always visible and unchecking changed only the «днём ещё N» counter line. Fix: selectors raised to `.list .r.day{display:none}` / `#allday:checked ~ main .list .r.day{display:grid}` (+ a canary test guarding the selector text). Note for archive readers: the template in `docs/stage3-design-adopted.md` §2 keeps the ORIGINAL buggy selectors — do not copy CSS from there; the live source of truth is `cinedigest/templates/index.html.j2`.

---

# SPb evening-cinema digest — v1 design

## 0. The v1 in one paragraph

A small Python program, `cinedigest`, runs once a day. It fetches the next 7 days of screenings from the six venues, normalises them into one record type, and writes two files: `docs/screenings.json` (data) and `docs/index.html` (one self-contained, mobile-first page: day chips at the top, each day a single time-sorted list merged across venues, screenings from 18:00 shown by default). The run is scheduled on GitHub Actions at 09:00 MSK if a two-minute geo-probe shows the runners can reach all six hosts; otherwise the identical command runs from cron on the person's own machine and pushes. The outputs are committed to the repository and GitHub Pages serves the page at a fixed URL the person bookmarks on their phone. No server, no database, no login. The only state is the previous run's `screenings.json`, which is used to carry a venue's data over (clearly marked stale) when that venue fails. Everything is inspectable: fetching and parsing are separate functions, one file per venue, tests run against saved real responses, and `python -m cinedigest run` reproduces the whole pipeline on a laptop.

## 1. Decisions, each with its reason

**D1. Shape: a static page rebuilt by a scheduled run** (not a plain script, not a hosted app). The routine being replaced is «pick a day, look at the evening across six sites»; that needs a multi-day view that is ready before the person asks, so a script they must run by hand doesn't remove the routine, and a hosted app adds a server, uptime and auth for zero extra value when the data is public and read-only.

**D2. Runtime: runner-agnostic code; GitHub Actions as primary, local cron as fallback, decided by a probe on day 1.** Actions gives a reliable daily run independent of whether a laptop is awake, and the repo already hosts the page; but non-Russian IPs may be blocked by some of the six hosts, and that is untested — so the design makes the probe (§7.2) the first task and names the decision rule rather than guessing. Fallback is the same command under `cron` on the person's machine + `git push`; only the scheduler changes.

**D3 (v1.1). Consumption: a bookmarked GitHub Pages URL as the main surface + an optional Telegram push in v1.** The page holds 7 days with filters (a Telegram message cannot — 4096-char limit, no day switching); the push covers "today's evening" + per-venue status, closes the «забыл заглянуть» gap, and is skipped gracefully when `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are unset.

**D4. Stack: Python 3.12, `requests`, `beautifulsoup4` (+`lxml`)› `jinja2`, `pytest`; stdlib `zoneinfo`, `dataclasses`, `logging`, `argparse`. No async, no framework, no build step.** This is the smallest set of widely documented tools for «fetch → parse → render»; a learner can read every layer, and ~30 requests per run do not need concurrency.

**D5 (v1.1). State: only two persisted things) `snapshots/<run-id>/<venue>/<label>` raw bodies written by the http layer every run (kept 14 days — that is the parse-against-exact-bytes safety net and the replay source), and the previous `screenings.json` read for one purpose — stale carry-over.** The repo history is the long-term archive of the rendered data; a database adds schema/migration concepts before any feature needs them. Shot
  — (v1.0 wording kept as context: computation is stateless; everything is re-derivable from a fresh fetch.)

**D6. Window = today … today+6 (MSK); evening threshold = 18:00; both are config constants and CLI flags.** Seven days covers «which day this week» planning and matches the ~one-week horizon of the Out Cinema feed; the full day is fetched and kept in the data, and the 18:00 cut is applied at render time with a «весь день» toggle, so the threshold can change without refetching.

**D7. Every venue adapter is two functions: `fetch(http, days) -> raw` (network only) and `parse(raw, days) -> list[Screening]` (pure).** Parsers are the part that breaks; pure parsers can be tested offline against saved responses and debugged by re-running on the failing file. This split is the single most important thing to keep as the system grows.

**D8. Failure policy: a venue failure never blocks the page.** Per venue: exceptions are caught, a status is recorded, and the previous snapshot's items (if ≤3 days old) are carried over with `stale=true`. The page always publishes; the process then exits non-zero if anything failed, so GitHub's built-in failure e-mail is the alert — and (v1.1) the Telegram message carries the ✗/⚠ statuses to the phone when configured. Silent emptiness is the failure mode that destroys trust in a digest; publishing with an honest error banner, plus a free alert channel, is the cheapest robust behaviour.

**D9. «Suspicious zero» check.** A venue that normally has daily screenings and parses to zero items across the whole window, without the venue's known «no sessions» marker on any page, is treated as a failure (its HTML changed), not as an empty week. Markup changes usually produce zero results, not exceptions — this check catches the most common scraper breakage.

**D10. Politeness: one `requests.Session`, generic Chrome UA (the tested configuration), `Accept-Language: ru`, 0.7 s pause between requests to the same host, timeouts 5 s connect / 20 s read, 3 retries with 1/2/4 s backoff on connection errors and 5xx, sequential venues.** ~30 requests a day is less than one human visit; retries cover transient hiccups at 09:00 without hammering anyone.

**D11. Lenfilm v1 = полный ежедневный репертуар через KinoPlan-фид (найден 2026-11-05, см. Adoption status); спец-таблица остаётся кросс-чеком/fallback и единственным источником заметки «кто представляет».** Yandex Afisha не нужен.

**D12. Rodina: keep the `facility` UUID as tested; one explicit test without it during setup.** Tested configuration first; the parameter costs nothing. *(Закрыто валидацией 2026-11-05: параметр не требуется; URL без facility.)*

**D13. Avrora token: read it from the shell HTML at run time (`window.kinositeSettings={token:"…"}`), fall back to the known constant.** The token is published in their page, so it's not a secret, but it may rotate; one extra request makes rotation a non-event.

**D14. Page language: Russian UI labels; English code, identifiers and docs.** All content is Russian; mixed-language chrome around Russian titles reads worse.

**D15. Repo is public, Pages public.** The content is public cinema schedules; nothing personal is stored. *( Подтверждено человеком 2026-11-05: публичный репозиторий OK.)*

## 2. Data flow

```
scheduler — GitHub Actions cron "0 6 * * *" (= 09:00 MSK, no DST in Russia) + manual trigger
        │  or: local cron "0 9 * * *" (fallback, same command, then git push)
        ▼
python -m cinedigest run --days 7 --out docs
1. window = [today(MSK) .. today+6]        # "today" always computed in Europe/Moscow
2. previous = load docs/screenings.json if it exists  ← the only state read
3. for venue in [domkino, rodina, avrora, poravkino, lenfilm, outcinema]:
       raw = venue.fetch(http, window)     # network; each response kept in memory
       items = venue.parse(raw, window)         # pure; raises on structural surprises
       apply "suspicious zero" rule (D9)
       on failure/suspicion:
         raw bodies are already in snapshots/<run-id>/ (v1.1),
         carry over previous items (stale)
4. snapshot = {generated_at, window, statuses[6], screenings[]}   (dedup by venue+source_id)
5. write docs/screenings.json + docs/status.json
6. render docs/index.html (page) + docs/digest.txt (plain text; its first section is the Telegram body)
7. deliver: Telegram push of today's evening (skipped when env vars unset)
8. exit 0 (all ok) | 2 (degraded: some venue failed/stale) | 1 (crash: nothing written)
        ▼
git add docs && commit if changed && push → GitHub Pages serves /docs
        ▼
person opens the bookmark; page lands on the first day that still has evening screenings;
taps a day chip; toggles venues / «весь день»; follows the ticket/film link.
non-zero exit → workflow marked failed → GitHub e-mails the person; debug/ uploaded as artifact.
```

## 3. Data model (complete module)

```python
# cinedigest/model.py  (v1.1 — merge of docs/design-alt-b.md)
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

VENUES = {
    "domkino": "Дом кино",
    "rodina": "Родина",
    "avrora": "Аврора",
    "poravkino": "Художественный",
    "lenfilm": "Ленфильм",
    "outcinema": "Out Cinema",
}

EVENING_FROM = time(18, 0)
NIGHT_UNTIL = time(6, 0)

def synthetic_id(venue: str, start: datetime, title: str, hall: str | None) -> str:
    """Stable id for venues whose pages expose no screening id."""
    key = f"{venue}|{start.isoformat()}|{title}|{hall or ''}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

@dataclass(frozen=True)
class Screening:
    venue: str                     # key of VENUES
    source_id: str                 # seance id / performance id / product uid / synthetic_id()
    title: str
    start: datetime                # timezone-aware, Europe/Moscow
    hall: str | None = None
    price_min: int | None = None   # rubles
    price_max: int | None = None   # rubles; equals price_min when a single price is known
    language: str | None = None    # source wording: "SUB", "Английский язык, русские субтитры", ...
    tags: tuple[str, ...] = ()     # display badges: "3D", "спецпоказ", "киноночь", "ХИЧКОК", ...
    url: str | None = None         # film page or ticket link
    source_url: str = ""           # page/endpoint this record was parsed from
    extra: dict = field(default_factory=dict)
    # extra keys used by the template when present:
    # year, country, director, duration_min, age, genres, synopsis,
    # free_places, online_sale, release_id

    @property
    def day(self) -> date:
        return self.start.astimezone(MSK).date()

    @property
    def digest_day(self) -> date:
        """Night screenings (00:00–05:59) belong to the previous evening."""
        return (self.start.astimezone(MSK) - timedelta(hours=6)).date()

    @property
    def is_evening(self) -> bool:
        t = self.start.astimezone(MSK).time()
        return t >= EVENING_FROM or t < NIGHT_UNTIL

    def to_json(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.astimezone(MSK).isoformat()
        return d

    @staticmethod
    def from_json(d: dict) -> "Screening":
        d = dict(d)
        d["start"] = datetime.fromisoformat(d["start"]).astimezone(MSK)
        d["tags"] = tuple(d.get("tags") or ())
        return Screening(**d)

def dedupe(screenings: list[Screening]) -> list[Screening]:
    """First occurrence wins; key = (venue, source_id); chronological order."""
    seen: set[tuple[str, str]] = set()
    out: list[Screening] = []
    for s in sorted(screenings, key=lambda s: (s.start, s.venue, s.title)):
        key = (s.venue, s.source_id)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out

def select(screenings: list[Screening],
           days: list[date],
           evening_only: bool = True) -> dict[date, list[Screening]]:
    """Evening screenings grouped by digest day for the requested days.

    The whole window stays in the snapshot; this is the single place where the
    evening cut and the night rule are applied (render decides evening_only)."""
    grouped: dict[date, list[Screening]] = {day: [] for day in days}
    for s in dedupe(screenings):
        if s.digest_day in grouped and (not evening_only or s.is_evening):
            grouped[s.digest_day].append(s)
    return grouped

@dataclass
class VenueStatus:
    venue: str
    ok: bool
    count: int
    fetched_at: datetime | None    # time of the data shown; None when nothing is shown
    stale: bool = False            # items carried over from the previous snapshot
    suspicious: bool = False       # zero items without the venue's «no sessions» marker
    error: str | None = None
    warning: str | None = None     # adapter succeeded with a caveat; shown as ⚠
    requests: int = 0
    seconds: float = 0.0

@dataclass
class Snapshot:
    generated_at: datetime
    window_start: date
    window_end: date               # inclusive
    statuses: list[VenueStatus]
    screenings: list[Screening]

    def to_json(self) -> dict:
        return {
            "generated_at": self.generated_at.astimezone(MSK).isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "statuses": [
                {**asdict(s), "fetched_at": s.fetched_at.astimezone(MSK).isoformat() if s.fetched_at else None}
                for s in self.statuses
            ],
            "screenings": [s.to_json() for s in sorted(self.screenings, key=lambda s: (s.start, s.venue))],
        }

    @staticmethod
    def from_json(d: dict) -> "Snapshot":
        statuses = []
        for s in d["statuses"]:
            s = dict(s)
            s["fetched_at"] = datetime.fromisoformat(s["fetched_at"]).astimezone(MSK) if s["fetched_at"] else None
            statuses.append(VenueStatus(**s))
        return Snapshot(
            generated_at=datetime.fromisoformat(d["generated_at"]).astimezone(MSK),
            window_start=date.fromisoformat(d["window_start"]),
            window_end=date.fromisoformat(d["window_end"]),
            statuses=statuses,
            screenings=[Screening.from_json(x) for x in d["screenings"]],
        )
```

Adapter contract (one module per venue in `cinedigest/venues/`): module-level `ID`, `NAME`, `DAILY = True|False` (False only for the Lenfilm special-table fallback; the Lenfilm kinokassa adapter behaves like a daily venue), `fetch(http, days) -> list[tuple[str, str]]` returning `(label, body)` pairs archived into `snapshots/<run-id>/`, `parse(raw, days) -> list[Screening]`, `legit_empty(body) -> bool` (the venue's own «no sessions» marker). The orchestrator in `pipeline.py` knows nothing venue-specific. Adapters fill `tags` with display badges only (non-2D format titles, «киноночь», Out Cinema series marks, «спецпоказ» for the HTML-table fallback); `language` carries the SUB/voiceover wording; the `special` boolean of v1.0 became the «спецпоказ» tag.

## 4. Per-venue adapter specs

**Dom Kino** — one GET per day: `https://domkino.spb.ru/schedule/{Y}/{MM}/{DD}/`. *(Уточнение валидацией: использовать `www.domkino.spb.ru` (безwww — 301).)* Parse: for each hall heading (text ∈ {Большой, Синий, Белый, Сиреневый, Малый}) take the following `<table>`; rows with 5 cells → `Сеанс` (`HH:MM`), `Фильм` (anchor text = title; `href` `/films/<slug>/` → absolute `url`), `Жанр` → `extra.genres`, `Звук` → `language` (raw string), `Цена` (`\d+` → `price_min=price_max`). `hall` = heading. `source_id = synthetic_id`. HTTP 404 = empty day, not an error *(уточнено: далёкая дата отдаёт 200-оболочку без заголовков залов — это и есть пустой день; оболочка не подозрительна)*.

**Rodina** — one GET per day: `https://rodinakino.ru/?date={Y}/{MM}/{DD}` *(facility не требуется — валидация 2026-11-05)*. Parse: find every anchor whose `href` matches `^#(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})$` — the full date is in the anchor, so use it (not the request date). For each anchor, climb to the enclosing event container and take its title and event link; badges adjacent to the anchor (e.g. `SUB`) → `language`. The exact container/title selectors are fixed from the saved fixture during implementation and pinned by a test. `legit_empty`: body contains «Сеансы не найдены». `source_id = synthetic_id`. Price usually absent → None.

**Avrora** — GET `https://avrora.spb.ru/` once, regex `kinositeSettings=\{token:"([A-Za-z0-9]+)"` and `kinokassaApiUrl="([^"]+)"` (fallbacks: `Q4uVHhNkaQiQ1SvI098z5KEtwHT5AQII`, `https://kinokassa.kinoplan24.ru`); then one GET per day: `{api}/api/v2/release/playbill?city_id=2&date=YYYY-MM-DD` with headers `X-Application-Token: <token>`, `X-Platform: widget` (checked live 2026-11-05: the API has NO range mode — `date=…/…` answers 400, `date_from/date_to` are silently ignored and return only the current business day; no-`date` returns the current day as well; one call per day stays). **Parse:** for each `releases[]`, for each `seances[]` with `cinema_id == 70`: `start = fromisoformat(start_date_time)` (offset present) → MSK; `hall = hall.title`; `price_min/max = price.min/100, price.max/100` (kopeck interpretation; test pin 40000→400); `language` from seance `subtitles`/`voiceover` when non-null, else from release-level `subtitles`/`voiceovers`; `source_id = seance.id`; `title = release.title`; `extra`: `year`, `duration_min = duration`, `age = age_rating`, `genres`/`country` resolved through the top-level `genres`/`countries` lookup lists (id-keyed; confirm on the fixture), non-2D `formats[].title` values become tags (e.g. "3D"), `free_places = free_places_count`, `online_sale = is_allowed_online_sale`. `url`: the kinowidget seat URL pattern rendered client-side (809-байтовая оболочка; цены в статике нет) — v1 links to `https://avrora.spb.ru/` until a working purchase URL is confirmed. Zero seances on a single day is normal; non-200 or missing `releases` key = failure.

**Poravkino (Художественный)** — one GET per day: `https://poravkino.ru/api/schedule?date=YYYY-MM-DD` *(`date` обязателен; без него 400 «wrong date»)* (JSON list of movies). Parse: for each movie, for each `performances[]` with `is_active`: `start = fromisoformat(time)` (trailing `Z` = UTC) → MSK; **bucket by the MSK date after conversion** and dedupe by `source_id = performance.id` across the 7 responses (a late screening may sit in a different UTC day than its MSK day; observed 0 id overlaps between neighbor-day buckets). `hall = hall_name`; `price_min = price_max = price`; `title = name`, `extra.original_title = name_secondary`, `extra`: `year, country, director, duration_min, age, genres, rating, is3d → tag "3D", is_pushkin`. `url`: the SPA's movie route is unknown — `https://poravkino.ru/` until the route pattern is read from the bundle. `legit_empty`: HTTP 200 with `[]`. First-run check: compare one converted time with the site UI (the API↔UI eye check is still pending — descriptively not a parser-test pin).

**Lenfilm** — the daily repertoire is served by the same Kinoplan-Kinokassa API family as Avrora's, for cinema 2387 (the page embeds an iframe `https://kinowidget.kinoplan.ru/2387`; fixtures saved). Bootstrap: `GET /api/v2/app?with_cities=true&cinema_id=2387` (this bootstrap call happens before a token is known; header `X-Platform: widget`; the "Invalid headers" HTTP-400 fallback sends `X-Platform: WIDGET`, the tested value for this account); the response reveals the application token and `time_zone=3`. Schedule delivery: `GET /api/v2/release/playbill/info?cinema_id=2387` returns the date list under the real key `calendar.seance_dates` (Nov 2026: 21 dates; gaps observed on 13, 16–18 and 23; the covered window runs 05–30) — use it to cap the number of day queries (request only dates that exist; «days» outside the list are legit empty days); then `GET /api/v2/release/playbill?cinema_id=2387&date=YYYY-MM-DD` per date. Recording is identical to Avrora's playbill rules (`cinema_id == 2387` kept; seance shape: id, hall.title, start_date_time with explicit +03:00, price in kopecks, free_places_count, subtitles/voiceover; title from release). Kinoplan quirk (confirmed on the feed): subtitle info may ride in `formats` as a pseudo-format titled "SUB" while `subtitles`/`voiceover` stay null — then "SUB" appears in `tags` (the non-2D-format rule literally covers it) and `language` stays null; the renderer folds both into a single SUB chip. Test pins live in `tests/fixtures/lenfilm/` (feed-1-app.json shows token/cinemas; feed-3-playbill-info.json shows `seance_dates`; feed-4…feed-25 are full-day bodies sampled 2026-11-05). `url` for screenings in v1: `https://www.lenfilm.ru/service/Kinoteatr-Lenfilm/` (per-seance purchase links unverified). The special-showings HTML table (`page.html`, 11 rows) remains a fallback source (if the feed ever breaks) and the only place with the «кто представляет» presenter note; the «уточняйте по телефону» caveat belongs on those rows — decide at the display rider. Zero-marks: a window day without a `seance_dates` entry is a legit empty day, NOT suspicious.

**Out Cinema** — one GET (plus pagination): `https://store.tildaapi.com/api/getproductslist/?storepartuid=292580911081&recid=496330277&c=<unix-ms>&getparts=true&getoptions=true` with headers `Origin: https://outcinema.ru`, `Referer: https://outcinema.ru/`. If `total > len(products)`, request again with `slice=2,3,…` until `total` items are collected or a page comes back empty (confirm on first run). Parse: a product is a screening iff `url` or `buttonlink` contains `kinowidget.kinoplan.ru` **and** `sku` matches `^(\d{1,2}) ([А-ЯЁ]+), (\d{1,2}):(\d{2})$`; everything else (e.g. `АЛЬФРЕД ХИЧКОК` with mark `ОНЛАЙН-КУРС`) is logged at INFO as skipped. Month word → number via the genitive table (ЯНВАРЯ … ДЕКАБРЯ); year by the same rollover rule; cross-check against `parts` titles `DD.MM (ДД)` reached through `partuids` (ids that don't resolve are ignored; a mismatch logs a WARNING and the `sku` date wins). `title` as given (uppercase kept), `price_min = price_max = int(float(price))`, `url = buttonlink`, `source_id = uid`; `tags` gain the `mark` badge (e.g. "ХИЧКОК", "НУАР") and the «киноночь» badge when a resolved part title contains «КИНОНОЧЬ». `descr`: split on `<span`/`<br/>`, strip tags, then `Режиссер: (.+)` → `director`; `^(.+?), (\d{4}), (\d+) мин\., (\d+\+)$` → `country, year, duration_min, age`; `Жанр: (.+)` → `genres`; a line containing «язык» or «субтитр» → `language`; the first plain paragraph → `synopsis`. Products in the `КИНОНОЧЬ` / `OUT(SIGHT)` parts go through the same rule; if their `sku` has another shape they are skipped with a WARNING, which the person will see in the run log. Stale carry-over (all venues): if a venue failed or is suspicious, and the previous snapshot has that venue with `ok` and `fetched_at` ≤ 72 h old, its screenings inside the current window are reused with `VenueStatus(stale=True, fetched_at=previous.fetched_at, error=<this run's error>)`.

## 5. The page (`docs/index.html`)

- Header: «Вечерние сеансы · Санкт-Петербург», «обновлено 4 ноя, 09:02 МСК».
- Day chips row: `Ср 4 · Чт 5 · Пт 6 · Сб 7 · Вс 8 · Пн 9 · Вт 10`; each links to `#d-2026-11-05`. On load, JS scrolls to the first day that still has an evening screening later than the device's current time.
- Per-day section: one list sorted by start time, merged across venues. Row: `19:00 · [Дом кино] · Белый зал · **Сабрина** · 1954, США, 113 мин, 12+ · англ. язык, рус. субтитры · 350 ₽ · билеты/о фильме →`. Fields absent in the source are simply omitted. Specials carry a «спецпоказ» tag; Lenfilm rows carry the phone caveat.
- Controls: checkbox «весь день» (rows before 18:00 are in the HTML with class `daytime`, hidden by default); six venue chips that toggle visibility (choice kept in `localStorage` — UI preference only, no data); rows already past are dimmed (`past`) using the device clock.
- Footer: per-venue status table — ✓ ok (n сеансов) / ⚠ данные от 3 ноя 09:01, сайт не ответил (stale) / ✗ ошибка: HTTP 500 — plus links to the repo and to `screenings.json`.
- Inline CSS, system font, single column, `prefers-color-scheme` dark variant; total JS ≈ 40 lines (scroll-to-day, toggles, dimming). No framework, no build. `docs/screenings.json` is the same data for anyone else — a future Telegram sender, a calendar export, the tests — without touching the scrapers.

## 6. Repository layout, CLI, tests

```
cinedigest/
  __init__.py
  model.py
  http.py
  config.py
  pipeline.py
  render.py
  deliver.py            # Telegram push (optional) + digest.txt writer
  cli.py
  venues/
    __init__.py
    domkino.py
    rodina.py
    avrora.py
    poravkino.py
    lenfilm.py
    outcinema.py
  templates/index.html.j2
tests/
  fixtures/<venue>/<file>
  test_<venue>.py × 6
  test_pipeline.py
  test_render.py
docs/
  index.html
  screenings.json
  status.json          # published by GitHub Pages
  digest.txt           # plain text, same data (first section = Telegram body)
snapshots/             # raw bodies per run (git-ignored; retained 14 days)
.github/workflows/digest.yml
.github/workflows/probe.yml
requirements.txt
README.md
```

`config.py` holds every number from the verification in one place: window days, threshold, Rodina facility UUID *(не требуется — валидация)*(, Avrora token fallback and API base, Out Cinema storepart/recid ×2, hall names, UA string, delays.

CLI (each stage inspectable on its own — this is where the «understand the system» value lives):

- `python -m cinedigest fetch --venue rodina --date 2026-11-05 --save tests/fixtures/rodina/2026-11-05.html` — network only, saves raw.
- `python -m cinedigest parse --venue rodina tests/fixtures/rodina/2026-11-05.html` — prints parsed records as a table.
- `python -m cinedigest render docs/screenings.json` — re-renders the page without fetching (fast template iteration).
- `python -m cinedigest run --days 7 --out docs [--print]` — everything; `--print` also prints tomorrow's evening to the terminal.

Tests (pytest, offline, on fixtures): per venue, the count for the fixture day and one known screening (current example: Out Cinema «ЗАВОРОЖЕННЫЙ» «5 НОЯБРЯ, 15:40», 590 ₽, серия ХИЧКОК; non-screening «АЛЬФРЕД ХИЧКОК» skipped); Poravkino fixture pins (43886/43779/43887, UTC→MSK); Avrora 40000 → 400; Rodina «Сеансы не найдены» → empty, not suspicious; December rollover for Out Cinema dates; pipeline stale carry-over and suspicious-zero rules on fake adapters; the template renders an empty snapshot.

## 7. Workflows (complete)

### 7.1 `.github/workflows/digest.yml`

```yaml
name: digest
on:
  schedule:
    - cron: "0 6 * * *"        # 09:00 Europe/Moscow; Russia has no DST
  workflow_dispatch:
permissions:
  contents: write
concurrency:
  group: digest
  cancel-in-progress: false
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Build digest
        id: build
        run: python -m cinedigest run --days 7 --out docs
        continue-on-error: true
      - name: Commit outputs
        run: |
          git config user.name "digest-bot"
          git config user.email "digest-bot@users.noreply.github.com"
          git add docs
          if git diff --cached --quiet; then echo "no changes"
          else git commit -m "digest: $(date -u +%Y-%m-%dT%H:%MZ)"
               git push
          fi
      - name: Upload raw responses of failed venues
        if: steps.build.outcome != 'success'
        uses: actions/upload-artifact@v4
        with:
          name: debug-${{ github.run_id }}
          path: snapshots/
          if-no-files-found: ignore
      - name: Mark run failed if any venue failed
        if: steps.build.outcome != 'success'
        run: exit 1
```

GitHub Pages: repository Settings → Pages → «Deploy from a branch», branch `main`, folder `/docs`. The commit is made by the workflow itself; Pages redeploys on each push automatically.

### 7.2 `.github/workflows/probe.yml` — the geo test that decides D2

```yaml
name: probe
on: workflow_dispatch
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - name: Status, time and body size for the six hosts from a GitHub runner
        run: |
          UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
          D=$(date -u -d "+1 day" +%F); DS=$(date -u -d "+1 day" +%Y/%m/%d)
          p() { name="$1"; shift; printf '%-10s ' "$name"; curl -sS -o /dev/null -w '%{http_code} %{time_total}s %{size_download} bytes\n' --max-time 20 -A "$UA" "$@" || echo "curl failed"; }
          p domkino  "https://www.domkino.spb.ru/schedule/$DS/" 
          p rodina   "https://rodinakino.ru/?date=$DS"
          p avrora   "https://kinokassa.kinoplan24.ru/api/v2/release/playbill?city_id=2&date=$D" -H "X-Application-Token: Q4uVHhNkaQiQ1SvI098z5KEtwHT5AQII" -H "X-Platform: widget"
          p poravkino "https://poravkino.ru/api/schedule?date=$D"
          p lenfilm  "https://www.lenfilm.ru/service/Kinoteatr-Lenfilm/"
          p outcinema "https://store.tildaapi.com/api/getproductslist/?storepartuid=292580911081&recid=496330277&c=1&getparts=true&getoptions=true" -H "Origin: https://outcinema.ru"
```

Decision rule: six `200`s with plausible body sizes (a 200 with a few hundred bytes is a block page) → schedule in Actions. Any host blocked → run `python -m cinedigest run --days 7 --out docs && git add docs && git commit -qm "digest" && git push` from cron on the person's machine at 09:00; keep `digest.yml` with only `workflow_dispatch` so Actions can still be used for the reachable venues later. A mixed design (local fetch for blocked venues only) is deliberately not in v1.

### 7.3 Build order for the agentic sessions

1. Run the probe. 2. Capture one real fixture per venue (`fetch --save`), including an empty day for Dom Kino and Rodina and a Rodina request without `facility`. 3. Model, http, Out Cinema and Poravkino adapters (JSON, fastest to get right), tests. 4. Avrora, Dom Kino, Rodina, Lenfilm. 5. Pipeline with stale/suspicious rules. 6. Template and render. 7. Workflow + Pages; first scheduled run; compare one day against each site by eye (Poravkino time offset, Avrora prices).

*(Аджеймент 2026-11-05: шаги 1–2 частично выполнены оркестратор-сабагентами до кода (fixtures захвачены напрямую); этапы 3–5 объединены в Бриф 2.)*

## 8. Deferred (explicitly not in v1)

- Telegram push (daily «tomorrow evening» message and failure alerts) — the JSON output is already the input for it.
- «New since yesterday» / «cancelled» badges (needs a diff of consecutive snapshots; the data is there).
- Lenfilm daily repertoire via Yandex Afisha; Dom Kino «Скоро»; longer horizons (Rodina/Dom Kino publish 1–2 months). *(Lenfilm полный фид теперь — если разведка найдёт источник.)*
- Film enrichment: posters, ratings, original titles cross-matched between venues («the same film at Avrora and Dom Kino»), Dom Kino film pages for year/country (extra requests).
- Personal filters (seen list, «originals with subtitles only», excluded halls), `.ics` calendar export, seat availability (`free_places_count` exists at Avrora).
- A second daily run, change detection within a day, monitoring beyond GitHub's failure e-mail, any hosted app/database/auth.

## 9. Assumptions

- Python is acceptable as the language they are learning (подтверждено 2026-11-05).
- They have a GitHub account and a public repo + public Pages URL is fine (подтверждено 2026-11-05).
- Reading happens on a phone as well as a laptop; a daily refresh at 09:00 MSK is fresh enough (same-day changes are rare).
- Our interpretations hold until the first-run eye check: Avrora prices in kopecks, Poravkino times in UTC, Out Cinema screenings always carry a kinowidget URL and a «D МЕСЯЦА, HH:MM» sku.
- ~30 requests/day per venue group is acceptable to the sites; no ToS forbids it (none was read).
- The 18:00 threshold applies to start time, every day of the week.
- Lenfilm specials only is acceptable for v1. *(пересмотрено — см. Adoption status)*

## 10. Questions back to you, ranked by design impact

*(Ответы оркестратора/человека 2026-11-05: 1 — probe отложен до появления workflow (запуск на runner'е); 2 — публичный Pages OK, телефон — основное устройство чтения; 3 — Python; 4 — дефолты приняты; 5 — 7 дней; 6 — Lenfilm: хочет полный репертуар, если источник достижим; 7 — метаданные в объёме, который данные отдают сами, без лишних запросов; 8 — выполнено сабагентом (fixture-факты выше); 9 — исключений нет; 10 — 09:00 MSK достаточно.)*
