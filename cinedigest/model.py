# cinedigest/model.py (v1.1 — merge of docs/design-alt-b.md)
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
