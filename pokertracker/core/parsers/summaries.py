"""Lecture des resumes de tournoi.

Les historiques de mains ne contiennent pas les gains: c'est le fichier de
resume ecrit en fin de tournoi (« Tournament Summary » chez PokerStars,
« Tournament summary » chez Winamax) qui donne la place, le prix touche et
les primes. Ces fichiers alimentent le suivi financier et le bankroll.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterator, List, Optional

from .base import parse_buyin, to_decimal
from .dates import parse_datetime


@dataclass
class TournamentResult:
    room: str
    tournament_id: str
    name: str = ""
    buyin: Decimal = Decimal(0)        # part prizepool
    fee: Decimal = Decimal(0)          # commission de la room
    bounty_buyin: Decimal = Decimal(0)  # part prime (knockout)
    currency: str = "EUR"
    started_at: Optional[datetime] = None
    entrants: int = 0
    finish_place: int = 0
    prize: Decimal = Decimal(0)
    bounty_won: Decimal = Decimal(0)
    fmt: str = "mtt"
    raw_text: str = ""

    @property
    def cost(self) -> Decimal:
        return self.buyin + self.fee + self.bounty_buyin

    @property
    def won(self) -> Decimal:
        return self.prize + self.bounty_won

    @property
    def profit(self) -> Decimal:
        return self.won - self.cost

    @property
    def itm(self) -> bool:
        return self.prize > 0


ORDINAL = r"(?P<place>\d+)\s*(?:st|nd|rd|th|er|ere|eme|e)?"


class SummaryParser:
    room = "unknown"

    def detect(self, text: str) -> bool:
        raise NotImplementedError

    def split(self, text: str) -> Iterator[str]:
        raise NotImplementedError

    def parse(self, block: str) -> Optional[TournamentResult]:
        raise NotImplementedError

    def parse_text(self, text: str) -> Iterator[TournamentResult]:
        for block in self.split(text):
            if not block.strip():
                continue
            try:
                result = self.parse(block)
            except Exception:
                continue
            if result is not None:
                yield result


class PokerStarsSummary(SummaryParser):
    room = "PokerStars"

    RE_ID = re.compile(r"Tournament\s+#(\d+)", re.I)
    RE_NAME = re.compile(r"Tournament\s+#\d+,\s*(?P<name>.+?)\s*$", re.I | re.M)
    RE_BUYIN = re.compile(r"Buy-?In:\s*(?P<parts>[^\n]+)", re.I)
    RE_PLAYERS = re.compile(r"(?P<n>\d+)\s+players", re.I)
    RE_START = re.compile(r"Tournament started\s+(?P<date>[^\n]+)", re.I)
    RE_PLACE = re.compile(rf"You finished in\s+{ORDINAL}\s+place", re.I)
    #: lignes annoncant un gain (jamais la ligne « Total Prize Pool »)
    RE_AWARD_LINE = re.compile(r"^.*\b(?:credited|received|awarded|award)\b.*$", re.I | re.M)
    RE_MONEY = re.compile(r"([$€£]\s?[\d.,]+)")
    RE_BOUNTY = re.compile(r"([$€£]\s?[\d.,]+)[^\n]{0,40}?bount", re.I)
    RE_CURRENCY = re.compile(r"\b(USD|EUR|GBP|CAD)\b")

    def detect(self, text: str) -> bool:
        head = text[:4000]
        return bool(re.search(r"PokerStars\s+Tournament\s+#\d+", head, re.I)) and \
            "Hand #" not in head

    def split(self, text: str) -> Iterator[str]:
        text = text.replace("\r\n", "\n")
        for block in re.split(r"\n(?=PokerStars Tournament #)", text):
            if "Tournament #" in block:
                yield block

    def parse(self, block: str) -> Optional[TournamentResult]:
        tid = self.RE_ID.search(block)
        if not tid:
            return None
        result = TournamentResult(room=self.room, tournament_id=tid.group(1), raw_text=block)
        name = self.RE_NAME.search(block)
        if name:
            result.name = name.group("name").strip()
        buyin = self.RE_BUYIN.search(block)
        if buyin:
            parts = [p for p in re.split(r"[/+]", buyin.group("parts")) if re.search(r"\d", p)]
            values = [to_decimal(p) for p in parts]
            currency = self.RE_CURRENCY.search(buyin.group("parts"))
            if currency:
                result.currency = currency.group(1)
            elif "€" in buyin.group("parts"):
                result.currency = "EUR"
            else:
                result.currency = "USD"
            if len(values) == 3:            # knockout: prizepool / prime / commission
                result.buyin, result.bounty_buyin, result.fee = values
            elif len(values) == 2:
                result.buyin, result.fee = values
            elif values:
                result.buyin = values[0]
        players = self.RE_PLAYERS.search(block)
        if players:
            result.entrants = int(players.group("n"))
        start = self.RE_START.search(block)
        if start:
            result.started_at = parse_datetime(start.group("date"))
        place = self.RE_PLACE.search(block)
        if place:
            result.finish_place = int(place.group("place"))
        bounty = self.RE_BOUNTY.search(block)
        if bounty:
            result.bounty_won = to_decimal(bounty.group(1))
        for line in self.RE_AWARD_LINE.finditer(block):
            text = line.group(0)
            if re.search(r"prize pool|bount", text, re.I):
                continue          # cagnotte totale ou prime: ce n'est pas le gain
            money = self.RE_MONEY.search(text)
            if money:
                result.prize = to_decimal(money.group(1))
                break
        if "Sit & Go" in block or "STT" in block:
            result.fmt = "sng"
        return result


class WinamaxSummary(SummaryParser):
    room = "Winamax"

    RE_HEAD = re.compile(r"Winamax Poker - Tournament summary\s*:\s*(?P<name>[^\n]+)", re.I)
    RE_ID = re.compile(r"\((?P<id>\d+)\)")
    RE_BUYIN = re.compile(r"Buy-?In\s*:\s*(?P<parts>[^\n]+)", re.I)
    RE_PLAYERS = re.compile(r"Registered players\s*:\s*(?P<n>\d+)", re.I)
    RE_START = re.compile(r"Tournament started\s*:?\s*(?P<date>[^\n]+)", re.I)
    RE_PLACE = re.compile(rf"You finished in\s+{ORDINAL}\s+place", re.I)
    RE_WON = re.compile(r"You won\s+(?P<amount>[\d.,]+\s*€?)", re.I)
    RE_BOUNTY = re.compile(r"(?:bounty|prime)[^\d\n]{0,12}([\d.,]+)", re.I)

    def detect(self, text: str) -> bool:
        return "Tournament summary" in text[:4000] and "Winamax" in text[:4000]

    def split(self, text: str) -> Iterator[str]:
        text = text.replace("\r\n", "\n")
        for block in re.split(r"\n(?=Winamax Poker - Tournament summary)", text):
            if "Tournament summary" in block:
                yield block

    def parse(self, block: str) -> Optional[TournamentResult]:
        head = self.RE_HEAD.search(block)
        if not head:
            return None
        name = head.group("name").strip()
        tid = self.RE_ID.search(name)
        result = TournamentResult(room=self.room, tournament_id=tid.group("id") if tid else name,
                                  name=name, currency="EUR", raw_text=block)
        buyin = self.RE_BUYIN.search(block)
        if buyin:
            parts = [p for p in re.split(r"\+", buyin.group("parts")) if re.search(r"\d", p)]
            values = [to_decimal(p) for p in parts]
            if len(values) == 3:
                result.buyin, result.bounty_buyin, result.fee = values
            elif len(values) == 2:
                result.buyin, result.fee = values
            elif values:
                result.buyin = values[0]
        players = self.RE_PLAYERS.search(block)
        if players:
            result.entrants = int(players.group("n"))
        start = self.RE_START.search(block)
        if start:
            result.started_at = parse_datetime(start.group("date"))
        place = self.RE_PLACE.search(block)
        if place:
            result.finish_place = int(place.group("place"))
        won = self.RE_WON.search(block)
        if won:
            result.prize = to_decimal(won.group("amount"))
        bounty = self.RE_BOUNTY.search(block)
        if bounty:
            result.bounty_won = to_decimal(bounty.group(1))
        low = name.lower()
        if "expresso" in low or "spin" in low:
            result.fmt = "spin"
        elif "sit" in low:
            result.fmt = "sng"
        return result


SUMMARY_PARSERS: List[SummaryParser] = [PokerStarsSummary(), WinamaxSummary()]


def detect_summary(text: str) -> Optional[SummaryParser]:
    for parser in SUMMARY_PARSERS:
        try:
            if parser.detect(text):
                return parser
        except Exception:
            continue
    return None


def parse_summaries(text: str) -> List[TournamentResult]:
    parser = detect_summary(text)
    return list(parser.parse_text(text)) if parser else []
