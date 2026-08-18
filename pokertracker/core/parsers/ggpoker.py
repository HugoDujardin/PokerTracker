"""Parser des historiques GGPoker / GGNetwork (format tres proche de PokerStars)."""
from __future__ import annotations

import re

from .base import registry
from .pokerstars import PokerStarsParser

RE_SPLIT = re.compile(r"\n\s*\n(?=Poker Hand #)", re.I)

RE_HEADER_CASH = re.compile(
    r"Poker Hand #(?P<hid>[A-Z]{0,3}\d+):\s+(?P<game>[^(]+?)\s+"
    r"\((?P<sb>[^/]+?)/(?P<bb>[^)]+?)\)\s+-\s+"
    r"(?P<date>\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2})",
    re.I,
)
RE_HEADER_TOURNEY = re.compile(
    r"Poker Hand #(?P<hid>[A-Z]{0,3}\d+):\s+Tournament\s+#(?P<tid>\d+),\s+"
    r"(?P<buyin>.*?)\s*(?P<game>Hold'em No Limit|Omaha[^-]*?)\s+-\s+"
    r"(?:Level\s*\S*\s*)?\((?P<sb>[\d.,]+)/(?P<bb>[\d.,]+)\)\s+-\s+"
    r"(?P<date>\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2})",
    re.I,
)


class GGPokerParser(PokerStarsParser):
    room = "GGPoker"
    signature = re.compile(r"Poker Hand #[A-Z]{0,3}\d+:", re.I)
    marker = "Poker Hand #"
    re_split = RE_SPLIT
    re_header_cash = RE_HEADER_CASH
    re_header_tourney = RE_HEADER_TOURNEY


registry.register(GGPokerParser())
