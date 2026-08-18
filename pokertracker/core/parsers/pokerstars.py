"""Parser des historiques PokerStars (cash game, MTT, Sit&Go, Zoom)."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..models import Action, ActionType, GameType, Hand, Seat, Street, TableFormat, normalize_cards
from .base import HandParser, ParseError, registry, to_decimal

CARD = r"[2-9TJQKA][cdhs]"

RE_SPLIT = re.compile(r"\n\s*\n(?=PokerStars)", re.I)

RE_HEADER_CASH = re.compile(
    r"PokerStars(?:\s+Zoom)?\s+(?:Hand|Game)\s+#(?P<hid>\d+):\s+"
    r"(?P<game>[^(]+?)\s+"
    r"\((?P<sb>[^/]+?)/(?P<bb>[^)]+?)\)\s+-\s+"
    r"(?P<date>\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2})",
    re.I,
)
RE_HEADER_TOURNEY = re.compile(
    r"PokerStars\s+(?:Hand|Game)\s+#(?P<hid>\d+):\s+Tournament\s+#(?P<tid>\d+),\s+"
    r"(?P<buyin>[^-]*?)\s+(?P<game>Hold'em No Limit|Omaha[^-]*?|[A-Za-z' ]+?)\s+-\s+"
    r"(?:Level\s+\S+\s+)?\((?P<sb>[\d.,]+)/(?P<bb>[\d.,]+)\)\s+-\s+"
    r"(?P<date>\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2})",
    re.I,
)
RE_TABLE = re.compile(
    r"Table\s+'(?P<name>[^']+)'\s+(?P<max>\d+)-max.*?Seat\s+#(?P<btn>\d+)\s+is\s+the\s+button", re.I
)
RE_SEAT = re.compile(
    r"^Seat\s+(?P<no>\d+):\s+(?P<name>.+?)\s+\((?P<stack>[^)]+?)\s+in\s+chips\)", re.M
)
RE_POST = re.compile(
    r"^(?P<name>.+?):\s+posts\s+(?P<what>small blind|big blind|the ante|ante|small & big blinds)\s+(?P<amt>[^\s]+)",
    re.M | re.I,
)
RE_STRADDLE = re.compile(r"^(?P<name>.+?):\s+straddle\s+(?P<amt>\S+)", re.M | re.I)
RE_ACTION = re.compile(
    r"^(?P<name>.+?):\s+(?P<verb>folds|checks|calls|bets|raises)"
    r"(?:\s+(?P<amt>[^\s]+))?(?:\s+to\s+(?P<to>[^\s]+))?(?P<allin>\s+and is all-in)?\s*$",
    re.M | re.I,
)
RE_UNCALLED = re.compile(r"^Uncalled bet\s+\((?P<amt>[^)]+)\)\s+returned to\s+(?P<name>.+?)\s*$", re.M | re.I)
RE_COLLECT = re.compile(
    r"^(?P<name>.+?)\s+collected\s+(?P<amt>\S+)\s+from(?:\s+\S+)?\s+pot", re.M | re.I
)
RE_WON_SUMMARY = re.compile(r"^(?P<name>.+?)\s+wins\s+(?P<amt>\S+)", re.M | re.I)
RE_SHOW = re.compile(r"^(?P<name>.+?):\s+shows\s+\[(?P<cards>[^\]]+)\]", re.M | re.I)
RE_MUCK = re.compile(r"^(?P<name>.+?):\s+(?:mucks hand|doesn't show hand)", re.M | re.I)
RE_DEALT = re.compile(r"^Dealt to\s+(?P<name>.+?)\s+\[(?P<cards>[^\]]+)\]", re.M | re.I)
RE_BOARD = re.compile(r"^Board\s+\[(?P<cards>[^\]]+)\]", re.M | re.I)
RE_TOTALPOT = re.compile(r"^Total pot\s+(?P<pot>\S+)(?:\s+\|\s+Rake\s+(?P<rake>\S+))?", re.M | re.I)
RE_SHOWDOWN_SEAT = re.compile(r"^Seat\s+\d+:\s+(?P<name>.+?)\s+(?:\(.*?\)\s+)?showed\s+\[(?P<cards>[^\]]+)\]", re.M | re.I)

STREET_MARKERS = [
    (re.compile(r"^\*\*\*\s+HOLE CARDS\s+\*\*\*", re.M | re.I), Street.PREFLOP),
    (re.compile(r"^\*\*\*\s+(?:FIRST\s+)?FLOP\s+\*\*\*(?:\s+\[[^\]]+\])?\s*\[(?P<c>[^\]]+)\]", re.M | re.I), Street.FLOP),
    (re.compile(r"^\*\*\*\s+(?:FIRST\s+)?TURN\s+\*\*\*\s+\[[^\]]+\]\s+\[(?P<c>[^\]]+)\]", re.M | re.I), Street.TURN),
    (re.compile(r"^\*\*\*\s+(?:FIRST\s+)?RIVER\s+\*\*\*\s+\[[^\]]+\]\s+\[(?P<c>[^\]]+)\]", re.M | re.I), Street.RIVER),
    (re.compile(r"^\*\*\*\s+SHOW ?DOWN\s+\*\*\*", re.M | re.I), Street.SHOWDOWN),
]
RE_SUMMARY = re.compile(r"^\*\*\*\s+SUMMARY\s+\*\*\*", re.M | re.I)


def detect_game(label: str) -> GameType:
    low = label.lower()
    if "omaha" in low:
        if "5 card" in low or "5-card" in low:
            return GameType.PLO5
        return GameType.PLO
    if "hold'em" in low or "holdem" in low:
        return GameType.LHE if "limit" in low and "no limit" not in low and "pot limit" not in low else GameType.NLHE
    return GameType.OTHER


class PokerStarsParser(HandParser):
    """Parser du format PokerStars, egalement utilise (a quelques details pres)
    par plusieurs autres rooms: les sous-classes n'ont qu'a redefinir les
    expressions d'en-tete."""

    room = "PokerStars"
    signature = re.compile(r"PokerStars\s+(?:Zoom\s+)?(?:Hand|Game)\s+#\d+", re.I)
    marker = "PokerStars"
    re_split = RE_SPLIT
    re_header_cash = RE_HEADER_CASH
    re_header_tourney = RE_HEADER_TOURNEY

    def detect(self, text: str) -> bool:
        return bool(self.signature.search(text[:4000]))

    def split_hands(self, text: str) -> Iterator[str]:
        text = text.replace("\r\n", "\n").replace("﻿", "")
        for block in self.re_split.split(text):
            if self.marker in block:
                yield block

    # ------------------------------------------------------------------
    def parse_hand(self, block: str) -> Hand:
        m = self.re_header_tourney.search(block)
        is_tourney = m is not None
        if m is None:
            m = self.re_header_cash.search(block)
        if m is None:
            raise ParseError(f"en-tete {self.room} introuvable")

        played_at = datetime.strptime(m.group("date"), "%Y/%m/%d %H:%M:%S")
        hand = Hand(
            hand_id=m.group("hid"),
            room=self.room,
            played_at=played_at,
            game=detect_game(m.group("game")),
            sb=to_decimal(m.group("sb")),
            bb=to_decimal(m.group("bb")),
            raw_text=block,
        )
        if is_tourney:
            hand.table_format = TableFormat.MTT
            hand.tournament_id = m.group("tid")
            hand.buyin = to_decimal(m.group("buyin"))
            hand.currency = "CHIPS"
        else:
            cur = re.search(r"\b(USD|EUR|GBP|CAD)\b", m.group(0))
            hand.currency = cur.group(1) if cur else "USD"

        t = RE_TABLE.search(block)
        if t:
            hand.table_name = t.group("name")
            hand.max_seats = int(t.group("max"))
            hand.button_seat = int(t.group("btn"))
        if re.search(r"PokerStars\s+Zoom", block, re.I):
            hand.table_name = hand.table_name or "Zoom"

        header_end = block.find("\n", m.end())
        for sm in RE_SEAT.finditer(block):
            hand.seats.append(
                Seat(seat_no=int(sm.group("no")), player=sm.group("name").strip(),
                     stack=to_decimal(sm.group("stack")))
            )
        if not hand.seats:
            raise ParseError("aucun siege")

        known = {s.player for s in hand.seats}
        self._parse_actions(block, hand, known)
        self._parse_cards(block, hand, known)

        p = RE_TOTALPOT.search(block)
        if p:
            hand.pot = to_decimal(p.group("pot"))
            hand.rake = to_decimal(p.group("rake"))
        b = RE_BOARD.search(block)
        if b:
            hand.board = list(normalize_cards(b.group("cards").split()))
        hand.finalize()
        return hand

    # ------------------------------------------------------------------
    def _street_bounds(self, block: str) -> list[tuple[Street, int, int, list[str]]]:
        marks: list[tuple[Street, int, list[str]]] = []
        for rx, street in STREET_MARKERS:
            mm = rx.search(block)
            if mm:
                cards = list(normalize_cards(mm.groupdict().get("c", "").split())) if "c" in mm.groupdict() else []
                marks.append((street, mm.end(), cards))
        summ = RE_SUMMARY.search(block)
        end_all = summ.start() if summ else len(block)
        marks.sort(key=lambda x: x[1])
        out = []
        for i, (street, start, cards) in enumerate(marks):
            end = marks[i + 1][1] if i + 1 < len(marks) else end_all
            out.append((street, start, min(end, end_all), cards))
        return out

    def _parse_actions(self, block: str, hand: Hand, known: set[str]) -> None:
        bounds = self._street_bounds(block)
        head_end = bounds[0][1] if bounds else len(block)

        # blindes et antes (avant *** HOLE CARDS ***)
        head = block[:head_end]
        for pm in RE_POST.finditer(head):
            name = pm.group("name").strip()
            if name not in known:
                continue
            what = pm.group("what").lower()
            amt = to_decimal(pm.group("amt"))
            if "ante" in what:
                atype = ActionType.POST_ANTE
            elif what == "small blind":
                atype = ActionType.POST_SB
            elif what == "big blind":
                atype = ActionType.POST_BB
            else:  # small & big blinds (joueur qui revient)
                atype = ActionType.POST_DEAD
            hand.actions.append(Action(name, Street.PREFLOP, atype, amt, amt))
        for sm in RE_STRADDLE.finditer(head):
            if sm.group("name").strip() in known:
                amt = to_decimal(sm.group("amt"))
                hand.actions.append(Action(sm.group("name").strip(), Street.PREFLOP,
                                           ActionType.POST_STRADDLE, amt, amt))

        for street, start, end, cards in bounds:
            if cards:
                hand.board.extend(c for c in cards if c not in hand.board)
            chunk = block[start:end]
            # mise courante par joueur sur la street (pour convertir "raises X to Y")
            committed: dict[str, Decimal] = {}
            if street == Street.PREFLOP:
                for a in hand.actions:
                    if a.type.is_blind:
                        committed[a.player] = max(committed.get(a.player, Decimal(0)), a.to_amount)
            for am in RE_ACTION.finditer(chunk):
                name = am.group("name").strip()
                if name not in known:
                    continue
                verb = am.group("verb").lower()
                allin = bool(am.group("allin"))
                amt = to_decimal(am.group("amt"))
                to_amt = to_decimal(am.group("to"))
                if verb == "folds":
                    hand.actions.append(Action(name, street, ActionType.FOLD))
                    continue
                if verb == "checks":
                    hand.actions.append(Action(name, street, ActionType.CHECK))
                    continue
                if verb == "calls":
                    committed[name] = committed.get(name, Decimal(0)) + amt
                    hand.actions.append(Action(name, street, ActionType.CALL, amt, committed[name], allin))
                    continue
                if verb == "bets":
                    committed[name] = committed.get(name, Decimal(0)) + amt
                    hand.actions.append(Action(name, street, ActionType.BET, amt, committed[name], allin))
                    continue
                # raises X to Y : X est l'increment, Y la mise totale
                total = to_amt or (committed.get(name, Decimal(0)) + amt)
                paid = total - committed.get(name, Decimal(0))
                committed[name] = total
                hand.actions.append(Action(name, street, ActionType.RAISE, paid, total, allin))

        for um in RE_UNCALLED.finditer(block):
            name = um.group("name").strip()
            if name in known:
                hand.actions.append(Action(name, Street.SHOWDOWN, ActionType.UNCALLED, to_decimal(um.group("amt"))))
        for cm in RE_COLLECT.finditer(block):
            name = cm.group("name").strip()
            if name in known:
                hand.actions.append(Action(name, Street.SHOWDOWN, ActionType.COLLECT, to_decimal(cm.group("amt"))))

    def _parse_cards(self, block: str, hand: Hand, known: set[str]) -> None:
        d = RE_DEALT.search(block)
        if d and d.group("name").strip() in known:
            hero = d.group("name").strip()
            hand.hero = hero
            seat = hand.seat_of(hero)
            if seat:
                seat.is_hero = True
                seat.cards = normalize_cards(d.group("cards").split())
        for sm in RE_SHOW.finditer(block):
            name = sm.group("name").strip()
            seat = hand.seat_of(name)
            if seat:
                seat.cards = normalize_cards(sm.group("cards").split())
                seat.showed = True
                hand.actions.append(Action(name, Street.SHOWDOWN, ActionType.SHOW))
        for sm in RE_SHOWDOWN_SEAT.finditer(block):
            seat = hand.seat_of(sm.group("name").strip())
            if seat and not seat.cards:
                seat.cards = normalize_cards(sm.group("cards").split())
                seat.showed = True
        for mm in RE_MUCK.finditer(block):
            name = mm.group("name").strip()
            if name in known:
                hand.actions.append(Action(name, Street.SHOWDOWN, ActionType.MUCK))


registry.register(PokerStarsParser())
