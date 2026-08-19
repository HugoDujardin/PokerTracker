"""Lecture des dates d'historique, independamment de la langue du client.

Certaines rooms (PartyPoker, iPoker...) ecrivent la date avec les noms de
mois et de jours dans la langue du logiciel: « lundi, janvier 15 » pour un
client francais. `strptime` depend alors de la locale du systeme et echoue
silencieusement. Les tables ci-dessous rendent la lecture deterministe.

C'est important: une date mal lue faisait auparavant retomber sur la date
du jour, et les filtres par periode se retrouvaient donc bases sur la date
d'import et non sur la date reelle de la main.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

MONTHS = {
    # anglais
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    # francais
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "décembre": 12,
    # espagnol / portugais
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setembro": 9, "octubre": 10, "outubro": 10,
    "noviembre": 11, "novembro": 11, "diciembre": 12, "dezembro": 12, "janeiro": 1,
    "fevereiro": 2, "marco": 3, "março": 3, "maio": 5, "junho": 6, "julho": 7,
    # allemand
    "januar": 1, "februar": 2, "marz": 3, "märz": 3, "juni": 6, "juli": 7, "oktober": 10,
    "dezember": 12,
    # italien
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "settembre": 9, "ottobre": 10, "novembre_it": 11, "dicembre": 12,
}

#: abreviations usuelles (Jan, Fev, Feb...)
for _name, _num in list(MONTHS.items()):
    MONTHS.setdefault(_name[:3], _num)

RE_NUMERIC = re.compile(
    r"(?P<y>\d{4})[/-](?P<m>\d{1,2})[/-](?P<d>\d{1,2})[ T]+(?P<H>\d{1,2}):(?P<M>\d{2})"
    r"(?::(?P<S>\d{2}))?")
RE_NUMERIC_DMY = re.compile(
    r"(?P<d>\d{1,2})[/-](?P<m>\d{1,2})[/-](?P<y>\d{4})[ T]+(?P<H>\d{1,2}):(?P<M>\d{2})"
    r"(?::(?P<S>\d{2}))?")
RE_TEXT = re.compile(
    r"(?:(?P<weekday>[^\W\d_]+),?\s+)?"
    r"(?:(?P<month1>[^\W\d_]+)\s+(?P<day1>\d{1,2})|(?P<day2>\d{1,2})\s+(?P<month2>[^\W\d_]+))"
    r"[,\s]+(?:(?P<year1>\d{4})[,\s]+)?"
    r"(?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?"
    r"(?:\s+(?P<tz>[A-Z]{2,5}))?(?:\s+(?P<year2>\d{4}))?",
    re.UNICODE)


def parse_datetime(text: str, default_year: Optional[int] = None) -> Optional[datetime]:
    """Lit une date d'historique quel que soit son format ou sa langue."""
    if not text:
        return None
    # mots de liaison des formats latins: "15 de enero", "15 di gennaio"
    text = re.sub(r"\b(?:de|del|di|of|den|le)\b", " ", text.strip(), flags=re.I)
    for regex in (RE_NUMERIC, RE_NUMERIC_DMY):
        m = regex.search(text)
        if m:
            return datetime(int(m.group("y")), int(m.group("m")), int(m.group("d")),
                            int(m.group("H")), int(m.group("M")), int(m.group("S") or 0))
    m = RE_TEXT.search(text)
    if m:
        name = (m.group("month1") or m.group("month2") or "").lower()
        month = MONTHS.get(name) or MONTHS.get(name[:3])
        day = m.group("day1") or m.group("day2")
        year = m.group("year1") or m.group("year2") or default_year
        if month and day and year:
            return datetime(int(year), month, int(day), int(m.group("H")), int(m.group("M")),
                            int(m.group("S") or 0))
    return None


def parse_any(candidates: Iterable[str], default_year: Optional[int] = None) -> Optional[datetime]:
    for text in candidates:
        parsed = parse_datetime(text, default_year)
        if parsed is not None:
            return parsed
    return None
