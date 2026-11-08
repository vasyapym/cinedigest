"""Pure, render-only country enrichment; no I/O and no mutation of source rows."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from copy import deepcopy
from typing import Iterable

from .model import Screening
from .posters import film_year, norm

Country = str | list[str] | tuple[str, ...]

_SEPARATORS = re.compile(r"[,;/|+&\n·]+")
_WORD_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)
_ALIASES = {
    "россия": "ru",
    "российская федерация": "ru",
    "ru": "ru",
    "rus": "ru",
    "ссср": "su",
    "su": "su",
    "soviet union": "su",
}


@dataclass(frozen=True)
class CountryEvidence:
    """Additional, already available local evidence for the Stage-B seam.

    Matching uses norm(title), exact film_year(year), and country-set agreement.
    source is a provenance label, not a URL to fetch.
    """
    title: str
    year: int | str | None
    country: Country
    source: str


def _countries(value) -> frozenset[str]:
    """Canonical country entries, not substring matches inside country names."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        return frozenset()

    entries: set[str] = set()
    for text in values:
        if not isinstance(text, str):
            continue
        for part in _SEPARATORS.split(text):
            entry = _WORD_SEPARATORS.sub(" ", part.casefold()).strip()
            parenthesized = re.fullmatch(r"([^()]+)\(([^()]+)\)[\s.]*", part.strip())
            if parenthesized:
                outer, inner = (
                    _WORD_SEPARATORS.sub(" ", label.casefold()).strip()
                    for label in parenthesized.groups()
                )
                if outer in _ALIASES and _ALIASES[outer] == _ALIASES.get(inner):
                    entry = outer
            if entry:
                entries.add(_ALIASES.get(entry, entry))
    return frozenset(entries)


def country_status(value) -> str:
    entries = _countries(value)
    if "ru" in entries:
        return "Russian"
    return "other" if entries else "unknown"


def _candidate(
    title: str,
    year: int | None,
    evidence: list[CountryEvidence],
    known_years: set[int],
) -> CountryEvidence | None:
    if not title:
        return None
    if year is None and len(known_years) > 1:
        return None

    # Undated evidence can contradict a dated candidate even when it cannot
    # safely identify which of several dated films it belongs to.
    compatible = [
        item for item in evidence
        if year is None or item.year is None or item.year == year
    ]
    signatures = {_countries(item.country) for item in compatible}
    if len(signatures) != 1:
        return None

    donors = [
        item for item in compatible
        if year is None or item.year == year or len(known_years) <= 1
    ]
    return donors[0] if donors else None


def enrich(
    screenings: Iterable[Screening],
    *,
    additional: Iterable[CountryEvidence] = (),
) -> list[Screening]:
    """Return detached HTML-specific copies with country and classification.

    `additional` is the single Stage-B injection seam. Its caller must supply
    already available data; this function never loads a cache or calls a resolver.

    Source countries are preserved verbatim. Missing countries may be copied
    from original window evidence only: derived results never become donors.
    """
    rows = list(screenings)
    by_title: dict[str, list[CountryEvidence]] = defaultdict(list)
    years: dict[str, set[int]] = defaultdict(set)

    for row in rows:
        title = norm(row.title)
        if not title:
            continue
        extra = row.extra or {}
        year = film_year(extra.get("year"))
        if year is not None:
            # Even a country-less row can establish a second film identity.
            years[title].add(year)
        country = extra.get("country")
        if _countries(country):
            by_title[title].append(CountryEvidence(
                title=title,
                year=year,
                country=country,
                source=f"window:{row.venue}",
            ))

    for item in additional:
        title = norm(item.title)
        if not title or not _countries(item.country):
            continue
        year = film_year(item.year)
        if year is not None:
            years[title].add(year)
        by_title[title].append(CountryEvidence(
            title=title,
            year=year,
            country=item.country,
            source=item.source,
        ))

    copies: list[Screening] = []
    for row in rows:
        extra = deepcopy(row.extra or {})
        if not _countries(extra.get("country")):
            title = norm(row.title)
            candidate = _candidate(
                title,
                film_year(extra.get("year")),
                by_title.get(title, []),
                years.get(title, set()),
            )
            if candidate is not None:
                extra["country"] = deepcopy(candidate.country)
                extra["country_source"] = candidate.source
        extra["country_status"] = country_status(extra.get("country"))
        copies.append(replace(row, extra=extra))
    return copies
