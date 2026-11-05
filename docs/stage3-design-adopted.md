# Stage 3 — the reading experience (design ADOPTED, 2026-11-05)

<!--
Adoption header (orchestrator): this file reproduces the creative specialist's Brief 4 reply verbatim.
It is the binding design for stage-3 mechanics. Adjudications recorded in docs/design-v1.md
("Stage-3 design adoption"); all 10 pivots ACCEPTED except where noted there. For the implementing
session: the only engine modules to adapt are import paths (`engine` → `cinedigest.*`) and the
`genres` normalization in the render context builder (outcinema stores a string; the adopted plan
normalizes at render). Q-verdicts (facts): Q1 yes (digest_day owns the night rule regardless of
evening_only) · Q2 stale ⇒ ok=False with carried count · Q3 aware MSK datetime objects reach the
template · Q4 page_url is optional/env · Q5 no extra chip in v1 · Q6 YES — rodina halls are added
this stage (engine) · Q7 not shown v1 · Q8 plain text, no parse_mode · Q9 keep full venue name.
-->

=== PASTE START ===

# Stage 3 — the reading experience (page, digest.txt, Telegram)

## 1. Design decisions

**Reading model.** The page answers one question per glance — «что идёт вечером, во сколько, где, на каком языке, почём» — so every row is two lines on a phone: `время · название — кинотеатр` / meta. Everything else (synopsis, daytime rows, failed venues' details) is one tap away but never in the way.

1. **One merged chronological list per day** (frame kept). Venue-first grouping is what the six sites already give; the whole point of the digest is to see the evening as a timeline. Venue chips give the per-venue view when planning on a laptop.
2. **Row = `19:00` · *Сабрина* — Дом кино / `1954 · США · 113 мин · 12+ · реж. … · драма, комедия · субтитры · Белый зал · 350 ₽ [3D]`**. Absent fields vanish; the meta line is built as a list and joined with «·», so no dangling separators.
3. **Links are honest about where they lead.** The title is linked only when the URL is film/ticket-specific (Дом кино, Родина → «о фильме»; Out Cinema → the seat page). For Художественный/Аврора/Ленфильм the URL is the venue schedule, so it is attached to the venue name, not the title — a tapped title must never land on a homepage.
4. **Language is normalized to two words the reader actually scans for:** `SUB` (incl. Ленфильм's pseudo-format tag) → «субтитры»; everything else is shown verbatim, lower-cased first letter («дублирование», «закадровый», «английский язык, русские субтитры»). The `SUB` tag is never rendered as a badge.
5. **Night rule made visible.** A 00:30 row sits at the end of «today» (as `select()` places it), with a small «ночь на чт» under the time, so the reader never wonders which calendar day the ticket is for.
6. **Toggles work without JavaScript.** «весь день» and the six venue chips are `<label>`s for hidden checkboxes placed first in `<body>`; CSS `:checked ~ main …` rules do the hiding. JS only persists the state (localStorage) and adds dimming/scroll/active-day. The JS can be deleted and the page still fully works.
7. **Truth about freshness and failures is at the top, not only in the footer.** Absence of rows is indistinguishable from «nothing is on», so a one-line ⚠ banner lists every venue that is stale / down / suspicious / warned; details and timings stay in the footer. A JS check compares the device date with the build date and shows «страница собрана вчера» when the 09:00 run has not happened yet.
8. **Device clock, not server clock, decides «past»**: rows with `data-ts < now` are dimmed (never hidden) and re-evaluated every minute; on load the page jumps to the first day that still has an evening screening ahead (unless a `#hash` is present).
9. **Field-specific restraint:** `free_places` only when ≤ 50 («осталось 12 мест» — 09:00 data, so only the alarming case is worth showing); `online_sale == False` → «только в кассе»; `synopsis` folded in `<details>`; `original_title` next to the title in muted text; `genres` capped at three; `is_pushkin` not shown.
10. **Status footer is per-venue, one line, three glyphs**: ✓ clean · ⚠ stale/suspicious/warning · ✗ error; always with count, fetch time, and request/seconds for the person who reads code line-by-line. Zero-evening days say so explicitly and tell how many daytime rows are hidden.

**Page weight budget:** ≤ 250 KB raw HTML for 7 days (≈350 rows × ~450 B + synopses), CSS ≈ 5 KB, JS ≈ 3 KB, zero images/fonts/requests; gzipped it lands ≈ 40–60 KB — well under one second on LTE, instant over `file://`. The render stage should log the byte size and warn above 400 KB.

## 2. `templates/index.html.j2`

```jinja
{#- templates/index.html.j2 — the single-file page. Context built by the render stage:
    generated_at   datetime (Europe/Moscow)      build time of this snapshot
    today          date                          MSK date of the run
    days           list[tuple[date, list[Screening]]]
                   list(select(screenings, days, evening_only=False).items()), 7 entries,
                   rows chronological; 00:00–05:59 rows sit under the PREVIOUS day
    evening        set[Screening]  {s for rows in select(..., evening_only=True).values() for s in rows}
    statuses       list[VenueStatus]            one per venue, VENUES order
    venues         dict[str, str]               VENUES: key -> display name
    repo_url       str | None
    json_name      str                            e.g. "screenings.json" (relative link)
Jinja env: autoescape=True, trim_blocks=True, lstrip_blocks=True. No extensions:
lists are grown with «{% set _ = xs.append(x) %}» (append returns None). -#}

{% macro plural(n, one, few, many) -%}
  {%- set n = n or 0 -%}
  {%- set a = n % 10 -%}{%- set b = n % 100 -%}
  {{ n }} {% if a == 1 and b != 11 %}{{ one }}{% elif a >= 2 and a <= 4 and (b < 12 or b > 14) %}{{ few }}{% else %}{{ many }}{% endif %}
{%- endmacro %}

{% macro dlong(d) -%}
  {%- set wd = ['пн','вт','ср','чт','пт','сб','вс'] -%}
  {%- set mon = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'] -%}
  {{ wd[d.weekday()] }} {{ d.day }} {{ mon[d.month - 1] }}
{%- endmacro %}

{% macro dshort(d) -%}
  {%- set wd = ['пн','вт','ср','чт','пт','сб','вс'] -%}
  {{ wd[d.weekday()] }} {{ d.day }}
{%- endmacro %}

{% macro dlabel(d, today) -%}
  {%- set off = (d - today).days -%}
  {%- if off == 0 %}Сегодня{% elif off == 1 %}Завтра{% else %}{{ dshort(d) }}{% endif -%}
{%- endmacro %}

{% macro lang(s) -%}
  {%- set l = (s.language or '')|trim -%}
  {%- if l -%}
    {%- if l|upper == 'SUB' %}субтитры{% else %}{{ l[0]|lower ~ l[1:] }}{% endif -%}
  {%- elif 'SUB' in s.tags %}субтитры{% endif -%}
{%- endmacro %}

{% macro price(s) -%}
  {%- if s.price_min is not none and s.price_max is not none and s.price_max != s.price_min %}{{ s.price_min }}–{{ s.price_max }} ₽
  {%- elif s.price_min is not none %}{{ s.price_min }} ₽
  {%- elif s.price_max is not none %}до {{ s.price_max }} ₽{% endif -%}
{%- endmacro %}

{% macro hall(h) -%}
  {%- if (h|string|trim)|int(-1) > 0 %}зал {{ h|string|trim }}{% else %}{{ h }}{% endif -%}
{%- endmacro %}

{% macro row(s, is_evening, venues) -%}
  {%- set x = s.extra or {} -%}
  {%- set film_link = s.url and s.venue in ('domkino', 'rodina', 'outcinema') -%}
  {%- set night = s.start.hour < 6 -%}
  {%- set parts = [] -%}
  {%- if x.year %}{% set _ = parts.append(x.year|string) %}{% endif -%}
  {%- if x.country %}{% set _ = parts.append(x.country) %}{% endif -%}
  {%- if x.duration_min %}{% set _ = parts.append(x.duration_min ~ ' мин') %}{% endif -%}
  {%- if x.age %}{% set a = x.age|string|trim %}{% set _ = parts.append(a if a.endswith('+') else a ~ '+') %}{% endif -%}
  {%- if x.director %}{% set _ = parts.append('реж. ' ~ x.director) %}{% endif -%}
  {%- if x.genres %}{% set _ = parts.append((x.genres|list)[:3]|join(', ')|lower) %}{% endif -%}
  {%- set l = lang(s) %}{% if l %}{% set _ = parts.append(l) %}{% endif -%}
  {%- if s.hall %}{% set _ = parts.append(hall(s.hall)) %}{% endif -%}
  {%- set p = price(s) %}{% if p %}{% set _ = parts.append(p) %}{% endif -%}
  {%- if x.free_places is defined and x.free_places is not none and x.free_places <= 50 %}{% set _ = parts.append('осталось ' ~ plural(x.free_places, 'место', 'места', 'мест')) %}{% endif -%}
  {%- if x.online_sale is defined and x.online_sale is sameas false %}{% set _ = parts.append('только в кассе') %}{% endif -%}

  <li class="r{% if not is_evening %} day{% endif %}{% if night %} night{% endif %}"
      data-v="{{ s.venue }}" data-ts="{{ s.start.timestamp()|int }}">
    <time datetime="{{ s.start.isoformat() }}">{{ s.start.strftime('%H:%M') }}{% if night %}<small>ночь на {{ dshort(s.start.date()) }}</small>{% endif %}</time>
    <div class="b">
      <div class="t">
        {% if film_link %}<a href="{{ s.url }}">{{ s.title }}</a>{% else %}<span>{{ s.title }}</span>{% endif %}
        {% if x.original_title and x.original_title != s.title %}<span class="o">{{ x.original_title }}</span>{% endif %}
        {% if s.url and not film_link %}<a class="v" href="{{ s.url }}">{{ venues[s.venue] }}</a>{% else %}<span class="v">{{ venues[s.venue] }}</span>{% endif %}
      </div>
      {% if parts or s.tags %}<div class="m">{{ parts|join(' · ') }}{% for t in s.tags if t|upper != 'SUB' %} <span class="tag">{{ t }}</span>{% endfor %}</div>{% endif %}
      {% if x.synopsis %}<details><summary>о фильме</summary><p>{{ x.synopsis }}</p></details>{% endif %}
    </div>
  </li>
{%- endmacro %}

{%- set issues = [] -%}
{%- for st in statuses -%}
  {%- set n = venues[st.venue] -%}
  {%- if st.stale %}{% set _ = issues.append(n ~ ' — данные ' ~ (('от ' ~ st.fetched_at.strftime('%d.%m %H:%M')) if st.fetched_at else 'с прошлого запуска')) %}
  {%- elif not st.ok %}{% set _ = issues.append(n ~ ' — недоступен, его сеансов в списке нет') %}
  {%- elif st.suspicious %}{% set _ = issues.append(n ~ ' — 0 сеансов без пометки «сеансов нет», возможно сломался разбор') %}
  {%- elif st.warning %}{% set _ = issues.append(n ~ ' — ' ~ st.warning) %}
  {%- endif -%}
{%- endfor -%}
{%- set all_down = statuses and (statuses|rejectattr('ok')|list|length == statuses|length) -%}

<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Кино вечером · СПб · {{ dlong(today) }}</title>
<style>
  :root{color-scheme:light dark;--bg:#fff;--fg:#141414;--mut:#6b6b6b;--line:#e4e4e4;--chip:#efefef;--acc:#0b57d0;--ok:#1a7f37;--warn:#7a5200;--warnbg:#fff4d6;--bad:#b3261e;--badbg:#fbe9e7}
  @media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#ececec;--mut:#9b9b9b;--line:#2b2b2b;--chip:#232323;--acc:#8ab4f8;--ok:#5fd38d;--warn:#f1c76a;--warnbg:#2b2310;--bad:#ff8a80;--badbg:#3a1a17}}
  *{box-sizing:border-box}
  html{background:var(--bg)}
  body{margin:0 auto;max-width:46rem;padding:0 .9rem 4rem;font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--fg);background:var(--bg)}
  a{color:var(--acc)}
  h1{font-size:1.35rem;margin:.9rem 0 0}
  .sub,.mut{color:var(--mut);font-size:.85rem;margin:.15rem 0 .6rem}
  .warn{background:var(--warnbg);color:var(--warn);padding:.5rem .7rem;border-radius:.5rem;font-size:.9rem;margin:.4rem 0}
  .warn a{color:inherit}
  .warn.bad{background:var(--badbg);color:var(--bad)}
  .ctl{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
  .days{position:sticky;top:0;z-index:2;display:flex;gap:.3rem;overflow-x:auto;margin:0 -.9rem;padding:.45rem .9rem;background:var(--bg);border-bottom:1px solid var(--line);scrollbar-width:none}
  .days a{flex:none;padding:.3rem .7rem;border-radius:1rem;text-decoration:none;color:var(--fg);background:var(--chip);font-size:.9rem}
  .days a.z{color:var(--mut);background:none}
  .days a[aria-current]{background:var(--fg);color:var(--bg)}
  .ctls{display:flex;flex-wrap:wrap;gap:.35rem;padding:.6rem 0 .2rem}
  .chip{font-size:.8rem;padding:.2rem .6rem;border:1px solid var(--line);border-radius:1rem;color:var(--mut);cursor:pointer;user-select:none}
  {% for k in venues %}#v-{{ k }}:checked ~ header label[for="v-{{ k }}"], {% endfor %}#allday:checked ~ header label[for="allday"]{color:var(--fg);border-color:var(--fg)}
  {% for k in venues %}#v-{{ k }}:not(:checked) ~ main .r[data-v="{{ k }}"]{display:none}
  {% endfor %}
  .day{display:none}
  #allday:checked ~ main .day{display:grid}
  #allday:checked ~ main .none-ev,#allday:checked ~ main .dayonly{display:none}
  section{scroll-margin-top:3.1rem;padding-top:1.1rem}
  h2{font-size:1.1rem;margin:0}
  h2 .dt{font-weight:400;color:var(--mut)}
  .cnt{margin:.1rem 0 .4rem;font-size:.85rem;color:var(--mut)}
  .list{list-style:none;margin:0;padding:0}
  .r{display:grid;grid-template-columns:3.6rem 1fr;column-gap:.5rem;padding:.55rem 0;border-top:1px solid var(--line)}
  .r time{font-variant-numeric:tabular-nums;font-weight:600}
  .r time small{display:block;font-size:.7rem;font-weight:400;color:var(--mut);line-height:1.2}
  .t{font-weight:600}
  .t a{color:inherit}
  .t .o{font-weight:400;color:var(--mut)}
  .t .v{font-weight:400;font-size:.8rem;color:var(--mut);white-space:nowrap}
  .t .v::before{content:"— "}
  .m{font-size:.86rem;color:var(--mut);margin-top:.1rem}
  .tag{display:inline-block;font-size:.72rem;padding:0 .4rem;border:1px solid var(--line);border-radius:.3rem;vertical-align:1px}
  details{font-size:.86rem;margin-top:.15rem}
  summary{cursor:pointer;color:var(--acc)}
  details p{margin:.3rem 0 0}
  .past{opacity:.45}
  .none{color:var(--mut);font-size:.9rem;padding:.5rem 0;border-top:1px solid var(--line);margin:0}
  footer{margin-top:2.5rem;border-top:2px solid var(--line);padding-top:.8rem}
  footer h2{font-size:1rem}
  .st{list-style:none;padding:0;margin:.4rem 0 .8rem;font-size:.9rem}
  .st li{padding:.2rem 0}
  .st .ic{display:inline-block;width:1.3rem}
  .st .ok .ic{color:var(--ok)}
  .st .wn .ic{color:var(--warn)}
  .st .bd .ic{color:var(--bad)}
  @media (min-width:40rem){.r{grid-template-columns:4rem 1fr}}
</style>
</head>
<body data-today="{{ today.isoformat() }}"
      data-generated="{{ generated_at.isoformat() }}"
      data-generated-human="{{ dlong(generated_at.date()) }} в {{ generated_at.strftime('%H:%M') }}">
<input type="checkbox" id="allday" class="ctl">
{% for k in venues %}<input type="checkbox" id="v-{{ k }}" class="ctl" checked> {% endfor %}

<header>
  <h1>Кино вечером</h1>
  <p class="sub">СПб · {{ venues|length }} кинотеатров · собрано {{ dlong(generated_at.date()) }}, {{ generated_at.strftime('%H:%M') }} · вечер = с 18:00</p>
  {% if all_down %}
    <p class="warn bad">✗ Все источники недоступны. {% if statuses|selectattr('stale')|list %}Показаны данные с прошлого запуска.{% else %}Сеансов в списке нет.{% endif %} <a href="#src">Подробнее</a></p>
  {% elif issues %}
    <p class="warn">⚠ {{ issues|join('; ') }}. <a href="#src">Подробнее</a></p>
  {% endif %}
  <p id="stale" class="warn" hidden></p>

  <nav class="days" aria-label="Дни">
    {% for d, rows in days %}
      {% set evc = rows|select('in', evening)|list|length %}
      <a href="#d-{{ d.isoformat() }}"{% if evc == 0 %} class="z"{% endif %}>{{ dlabel(d, today) }}</a>
    {% endfor %}
  </nav>
  <div class="ctls">
    <label for="allday" class="chip">весь день</label>
    {% for k, name in venues.items() %}<label for="v-{{ k }}" class="chip">{{ name }}</label> {% endfor %}
  </div>
</header>

<main>
{% for d, rows in days %}
  {% set ev = rows|select('in', evening)|list %}
  {% set nday = rows|length - ev|length %}
  {% set off = (d - today).days %}
  <section id="d-{{ d.isoformat() }}" aria-labelledby="h-{{ d.isoformat() }}">
    <h2 id="h-{{ d.isoformat() }}">{% if off == 0 %}Сегодня <span class="dt">· {{ dlong(d) }}</span>{% elif off == 1 %}Завтра <span class="dt">· {{ dlong(d) }}</span>{% else %}{{ dlong(d) }}{% endif %}</h2>
    {% if ev or nday %}
      <p class="cnt">{% if ev %}{{ plural(ev|length, 'сеанс', 'сеанса', 'сеансов') }} вечером{% endif %}{% if nday %}<span class="dayonly">{% if ev %} · {% endif %}днём ещё {{ nday }}</span>{% endif %}</p>
    {% endif %}
    {% if rows %}
      <ul class="list">
        {% for s in rows %}{{ row(s, s in evening, venues) }}{% endfor %}
      </ul>
      {% if not ev %}
        <p class="none none-ev">Вечером сеансов нет{% if nday %} — есть {{ plural(nday, 'дневной', 'дневных', 'дневных') }}, включите «весь день»{% endif %}.</p>
      {% endif %}
    {% else %}
      <p class="none">Сеансов нет ни в одном кинотеатре — или расписание на этот день ещё не опубликовано.</p>
    {% endif %}
  </section>
{% endfor %}
</main>

<footer id="src">
  <h2>Источники</h2>
  <ul class="st">
    {% for st in statuses %}
      {% set n = venues[st.venue] %}
      {% if not st.ok and not st.stale %}{% set icon = '✗' %}{% set cls = 'bd' %}
      {% elif st.stale or st.suspicious or st.warning %}{% set icon = '⚠' %}{% set cls = 'wn' %}
      {% else %}{% set icon = '✓' %}{% set cls = 'ok' %}{% endif %}
      <li class="{{ cls }}"><span class="ic" aria-hidden="true">{{ icon }}</span><b>{{ n }}</b> — {{ plural(st.count, 'сеанс', 'сеанса', 'сеансов') }}
        {%- if st.fetched_at %} · {{ st.fetched_at.strftime('%d.%m %H:%M') }}{% endif %}
        {%- if st.stale %} · <em>данные с прошлого запуска</em>{% endif %}
        {%- if st.suspicious %} · <em>ноль без пометки «сеансов нет» — подозрительно</em>{% endif %}
        {%- if st.error %} · <em>ошибка: {{ st.error }}</em>{% endif %}
        {%- if st.warning %} · <em>{{ st.warning }}</em>{% endif %}
        {%- if st.requests %} <span class="mut">· {{ st.requests }} запр., {{ '%.1f'|format(st.seconds or 0) }} с</span>{% endif %}</li>
    {% endfor %}
  </ul>
  <p class="mut">Снимок данных: <a href="{{ json_name }}">{{ json_name }}</a>{% if repo_url %} · <a href="{{ repo_url }}">код</a>{% endif %}. Вечер — сеансы с 18:00; ночные (до 06:00) стоят под предыдущим днём. Прошедшие сеансы приглушены по часам устройства.</p>
</footer>

<script>
(function () {
  var body = document.body, now = Date.now() / 1000;

  // 1. remember toggles (presentation only; CSS does the actual hiding)
  var KEY = 'kino.toggles', saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
  var ctls = Array.prototype.slice.call(document.querySelectorAll('input.ctl'));
  ctls.forEach(function (i) {
    if (i.id in saved) i.checked = !!saved[i.id];
    i.addEventListener('change', function () {
      var o = {};
      ctls.forEach(function (j) { o[j.id] = j.checked; });
      try { localStorage.setItem(KEY, JSON.stringify(o)); } catch (e) {}
    });
  });

  // 2. dim rows that already started
  var rows = Array.prototype.slice.call(document.querySelectorAll('.r[data-ts]'));
  function dim() {
    var t = Date.now() / 1000;
    rows.forEach(function (r) { r.classList.toggle('past', +r.dataset.ts < t); });
  }
  dim();
  setInterval(dim, 60000);

  // 3. page older than today?
  var d = new Date(), pad = function (n) { return (n < 10 ? '0' : '') + n; };
  var local = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  if (local !== body.dataset.today) {
    var st = document.getElementById('stale');
    st.hidden = false;
    st.textContent = '⚠ Страница собрана ' + body.dataset.generatedHuman + ' — на устройстве уже следующий день, свежего запуска ещё не было.';
  }

  // 4. jump to the first day with an evening screening still ahead
  if (!location.hash) {
    var next = null;
    for (var i = 0; i < rows.length; i++)
      if (!rows[i].classList.contains('day') && +rows[i].dataset.ts > now) { next = rows[i]; break; }
    var sec = next && next.closest('section');
    if (sec && sec !== document.querySelector('main section')) sec.scrollIntoView();
  }

  // 5. highlight the day being read
  if ('IntersectionObserver' in window) {
    var links = {};
    Array.prototype.forEach.call(document.querySelectorAll('.days a'), function (a) {
      links[a.getAttribute('href').slice(1)] = a;
    });
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        for (var k in links) links[k].removeAttribute('aria-current');
        if (links[e.target.id]) links[e.target.id].setAttribute('aria-current', 'date');
      });
    }, { rootMargin: '-40% 0px -55% 0px' });
    Array.prototype.forEach.call(document.querySelectorAll('main section'), function (s) { io.observe(s); });
  }
})();
</script>
</body>
</html>
```

## 3. `digest.txt` and the Telegram message

### Layout (what the reader sees)

```text
КИНО ВЕЧЕРОМ · СПб · собрано ср 5 ноября 09:01

СЕГОДНЯ · ср 5 ноября
---------------------
19:00 · Дом кино · Сабрина (1954) · 113 мин · 12+ · субтитры · Белый зал · 350 ₽
19:30 · Аврора · Дюна (2021) · дублирование · Большой · 400–550 ₽ · [3D]
21:15 · Out Cinema · Психо (1960) · английский язык, русские субтитры · 500 ₽ · [ХИЧКОК]
00:30 · Out Cinema · Киноночь: нуар (1944) · 600 ₽ · [киноночь] · ночь на чт

ЗАВТРА · чт 6 ноября
--------------------
— вечером сеансов нет (днём: 4)

ПТ 7 НОЯБРЯ
-----------
...

ИСТОЧНИКИ
---------
✓ Дом кино — 14 сеансов · 05.11 09:01 · 3 запр., 1.2 с
⚠ Родина — 9 сеансов · 04.11 09:00 · данные с прошлого запуска · ошибка: timeout
⚠ Аврора — 0 сеансов · 05.11 09:01 · ноль без пометки «сеансов нет» — подозрительно
✗ Out Cinema — 0 сеансов · ошибка: HTTP 503
```

Telegram (plain text, no `parse_mode`, `disable_web_page_preview=True`):

```text
СЕГОДНЯ ВЕЧЕРОМ · ср 5 ноября

19:00 · Дом кино · Сабрина (1954) · 113 мин · 12+ · субтитры · Белый зал · 350 ₽
…
00:30 · Out Cinema · Киноночь: нуар (1944) · 600 ₽ · [киноночь] · ночь на чт

Завтра вечером: 23 сеанса

✓ Дом кино 14 · Художественный 11 · Ленфильм 6
⚠ Родина — 9 сеансов · 04.11 09:00 · данные с прошлого запуска · ошибка: timeout
✗ Out Cinema — 0 сеансов · ошибка: HTTP 503
собрано 09:01
https://<user>.github.io/<repo>/   ← only when page_url is configured
```

### Renderer (`render_text.py`)

```python
"""digest.txt and the Telegram message. One row formatter, two wrappers."""
from __future__ import annotations
from datetime import date, datetime

from cinedigest.model import Screening, VenueStatus, VENUES  # adapted import

TG_LIMIT = 4096

WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MON = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

def plural(n: int, one: str, few: str, many: str) -> str:
    n = n or 0
    a, b = n % 10, n % 100
    word = one if (a == 1 and b != 11) else few if (2 <= a <= 4 and not 12 <= b <= 14) else many
    return f"{n} {word}"

def day_long(d: date) -> str:
    return f"{WD[d.weekday()]} {d.day} {MON[d.month - 1]}"

def heading(d: date, today: date) -> str:
    off = (d - today).days
    if off == 0: return f"СЕГОДНЯ · {day_long(d)}"
    if off == 1: return f"ЗАВТРА · {day_long(d)}"
    return day_long(d).upper()

def lang(s: Screening) -> str:
    l = (s.language or "").strip()
    if l: return "субтитры" if l.upper() == "SUB" else l[0].lower() + l[1:]
    return "субтитры" if "SUB" in s.tags else ""

def price(s: Screening) -> str:
    lo, hi = s.price_min, s.price_max
    if lo is not None and hi is not None and hi != lo: return f"{lo}–{hi} ₽"
    if lo is not None: return f"{lo} ₽"
    if hi is not None: return f"до {hi} ₽"
    return ""

def hall(h: str) -> str:
    h = str(h).strip()
    return f"зал {h}" if h.isdigit() else h

def row(s: Screening) -> str:
    x = s.extra or {}
    head = s.title + (f" ({x['year']})" if x.get("year") else "")
    bits = [s.start.strftime("%H:%M"), VENUES[s.venue], head]
    if x.get("duration_min"): bits.append(f"{x['duration_min']} мин")
    if x.get("age"):
        a = str(x["age"]).strip(); bits.append(a if a.endswith("+") else a + "+")
    if lang(s): bits.append(lang(s))
    if s.hall: bits.append(hall(s.hall))
    if price(s): bits.append(price(s))
    fp = x.get("free_places")
    if fp is not None and fp <= 50: bits.append("осталось " + plural(fp, "место", "места", "мест"))
    bits += [f"[{t}]" for t in s.tags if t.upper() != "SUB"]
    if s.start.hour < 6: bits.append(f"ночь на {WD[s.start.weekday()]}")
    return " · ".join(bits)

def day_block(d, rows, today, evening, *, underline: bool, title: str | None = None) -> list[str]:
    ev = [s for s in rows if s in evening]
    nday = len(rows) - len(ev)
    head = title or heading(d, today)
    out = [head] + (["-" * len(head)] if underline else [])
    if ev: out += [row(s) for s in ev]
    else:   out.append("— вечером сеансов нет" + (f" (днём: {nday})" if nday else ""))
    return out

def status_line(st: VenueStatus) -> str:
    if not st.ok and not st.stale: icon = "✗"
    elif st.stale or st.suspicious or st.warning: icon = "⚠"
    else: icon = "✓"
    bits = [plural(st.count, "сеанс", "сеанса", "сеансов")]
    if st.fetched_at: bits.append(st.fetched_at.strftime("%d.%m %H:%M"))
    if st.stale: bits.append("данные с прошлого запуска")
    if st.suspicious: bits.append("ноль без пометки «сеансов нет» — подозрительно")
    if st.error: bits.append(f"ошибка: {st.error}")
    if st.warning: bits.append(st.warning)
    if st.requests: bits.append(f"{st.requests} запр., {st.seconds or 0:.1f} с")
    return f"{icon} {VENUES[st.venue]} — {' · '.join(bits)}"

def is_clean(st: VenueStatus) -> bool:
    return bool(st.ok and not (st.stale or st.suspicious or st.warning))

def statuses_compact(statuses: list[VenueStatus]) -> list[str]:
    """Telegram: clean venues collapse into one line, problems keep a full line each."""
    clean = [f"{VENUES[s.venue]} {s.count}" for s in statuses if is_clean(s)]
    out = ["✓ " + " · ".join(clean)] if clean else []
    out += [status_line(s) for s in statuses if not is_clean(s)]
    return out

def render_digest(days, evening, statuses, generated_at, today) -> str:
    out = [f"КИНО ВЕЧЕРОМ · СПб · собрано {day_long(generated_at.date())} {generated_at:%H:%M}", ""]
    for d, rows in days:
        out += day_block(d, rows, today, evening, underline=True) + [""]
    out += ["ИСТОЧНИКИ", "---------"] + [status_line(s) for s in statuses]
    return "\n".join(out) + "\n"

def render_telegram(days, evening, statuses, generated_at, today, page_url: str | None = None) -> str:
    d, rows = days[0]
    out = day_block(d, rows, today, evening, underline=False, title=f"СЕГОДНЯ ВЕЧЕРОМ · {day_long(d)}")
    if len(days) > 1:
        n = sum(1 for s in days[1][1] if s in evening)
        out += ["", "Завтра вечером: " + (plural(n, "сеанс", "сеанса", "сеансов") if n else "ничего")]
    out += [""] + statuses_compact(statuses) + [f"собрано {generated_at:%H:%M}"]
    if page_url: out.append(page_url)
    return "\n".join(out)

def split_telegram(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Split at blank lines first, then at line ends, never inside a line; parts get «(i/n)» headers."""
    if len(text) <= limit: return [text]
    room = limit - 8
    parts, rest = [], text
    while len(rest) > room:
        cut = rest.rfind("\n\n", 0, room)
        if cut < room // 2: cut = rest.rfind("\n", 0, room)
        if cut <= 0: cut = room
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\\n")
    parts.append(rest)
    n = len(parts)
    return [f"({i}/{n})\\n{p}" for i, p in enumerate(parts, 1)]
```
