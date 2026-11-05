"""digest.txt and the Telegram message. One row formatter, two wrappers.

(Adopted verbatim from docs/stage3-design-adopted.md §3; only the imports were
adapted to the cinedigest package.)
"""
from __future__ import annotations
from datetime import date, datetime

from cinedigest.model import Screening, VenueStatus, VENUES

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
        rest = rest[cut:].lstrip("\n")
    parts.append(rest)
    n = len(parts)
    return [f"({i}/{n})\n{p}" for i, p in enumerate(parts, 1)]
