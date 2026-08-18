"""Parser des historiques Winamax (cash game, Expresso, MTT)."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..models import Action, ActionType, GameType, Hand, Seat, Street, TableFormat, normalize_cards
from .base import HandParser, ParseError, parse_buyin, registry, to_decimal

RE_SPLIT = re.compile(r"\n\s*\n(?=Winamax Poker)", re.I)

RE_HEADER = re.compile(
    r"Winamax Poker\s+-\s+(?P<kind>CashGame|Tournament.*?)\s+-\s+"
    r"(?:buyIn:\s*(?P<buyin>.+?)\s*level:\s*(?P<level>-?\d+)\s*-\s*)?"
    r"HandId:\s*#(?P<hid>[\d\-]+)\s*-\s*(?P<game>.+?)\s*"
    r"\((?P<sb>[^/]+?)/(?P<bb>[^/)]+?)(?:/(?P<bb2>[^)]+?))?\)\s*-\s*"
    r"(?P<date>\d{4}/\d{2}/\d{2}\s+\d{1,2}:\d{2}:\d{2})",
    re.I,
)
RE_TABLE = re.compile(
    r"Table:\s*'(?P<name>[^']+)'\s*(?P<max>\d+)-max.*?Seat\s+#(?P<btn>\d+)\s+is\s+the\s+button", re.I
)
RE_SEAT = re.compile(r"^Seat\s+(?P<no>\d+):\s+(?P<name>.+?)\s+\((?P<stack>[^)]*?)\)\s*$", re.M)
RE_DEALT = re.compile(r"^Dealt to\s+(?P<name>.+?)\s+\[(?P<cards>[^\]]+)\]", re.M | re.I)
RE_BOARD = re.compile(r"^Board:?\s*\[(?P<cards>[^\]]+)\]", re.M | re.I)
RE_TOTALPOT = re.compile(r"^Total pot\s+(?P<pot>[^|]+?)\s*(?:\|\s*(?:Rake\s+(?P<rake>\S+)|No rake))?\s*$", re.M | re.I)
RE_SUMMARY_WON = re.compile(r"^Seat\s+\d+:\s+(?P<name>.+?)\s+(?:\([^)]*\)\s+)?(?:showed\s+\[(?P<cards>[^\]]+)\]\s+and\s+)?won\s+(?P<amt>\S+)", re.M | re.I)
RE_SUMMARY_SHOWED = re.compile(r"^Seat\s+\d+:\s+(?P<name>.+?)\s+(?:\([^)]*\)\s+)?showed\s+\[(?P<cards>[^\]]+)\]", re.M | re.I)

STREET_MARKERS = [
    (re.compile(r"^\*\*\*\s*PRE-?FLOP\s*\*\*\*", re.M | re.I), Street.PREFLOP),
    (re.compile(r"^\*\*\*\s*FLOP\s*\*\*\*\s*\[(?P<c>[^\]]+)\]", re.M | re.I), Street.FLOP),
    (re.compile(r"^\*\*\*\s*TURN\s*\*\*\*\s*\[[^\]]+\]\s*\[(?P<c>[^\]]+)\]", re.M | re.I), Street.TURN),
    (re.compile(r"^\*\*\*\s*RIVER\s*\*\*\*\s*\[[^\]]+\]\s*\[(?P<c>[^\]]+)\]", re.M | re.I), Street.RIVER),
    (re.compile(r"^\*\*\*\s*SHOW\s*DOWN\s*\*\*\*", re.M | re.I), Street.SHOWDOWN),
]
RE_SUMMARY = re.compile(r"^\*\*\*\s*SUMMARY\s*\*\*\*", re.M | re.I)


class WinamaxParser(HandParser):
    """Winamax n'utilise pas de ':' apres le pseudo: les actions sont donc
    reconnues en s'appuyant sur la liste des joueurs assis."""

    room = "Winamax"

    def detect(self, text: str) -> bool:
        return "Winamax Poker" in text[:4000]

    def split_hands(self, text: str) -> Iterator[str]:
        text = text.replace("\r\n", "\n")
        for block in RE_SPLIT.split(text):
            if "Winamax Poker" in block:
                yield block

    def parse_hand(self, block: str) -> Hand:
        m = RE_HEADER.search(block)
        if m is None:
            raise ParseError("en-tete Winamax introuvable")
        hand = Hand(
            hand_id=m.group("hid"),
            room=self.room,
            played_at=datetime.strptime(m.group("date"), "%Y/%m/%d %H:%M:%S"),
            game=GameType.PLO if "omaha" in m.group("game").lower() else GameType.NLHE,
            sb=to_decimal(m.group("sb")),
            bb=to_decimal(m.group("bb2") or m.group("bb")),
            currency="EUR",
            raw_text=block,
        )
        if m.group("kind").lower().startswith("tournament"):
            hand.table_format = TableFormat.SPIN if "expresso" in m.group(0).lower() else TableFormat.MTT
            hand.buyin = parse_buyin(m.group("buyin"))
            hand.currency = "CHIPS"
            tid = re.search(r"HandId:\s*#(\d+)", block)
            hand.tournament_id = tid.group(1) if tid else ""
        if m.group("bb2"):  # (ante/sb/bb)
            hand.ante = to_decimal(m.group("sb"))
            hand.sb = to_decimal(m.group("bb"))

        t = RE_TABLE.search(block)
        if t:
            hand.table_name = t.group("name")
            hand.max_seats = int(t.group("max"))
            hand.button_seat = int(t.group("btn"))

        summary_at = RE_SUMMARY.search(block)
        seats_zone = block[: summary_at.start()] if summary_at else block
        for sm in RE_SEAT.finditer(seats_zone):
            hand.seats.append(Seat(int(sm.group("no")), sm.group("name").strip(),
                                   to_decimal(sm.group("stack"))))
        if not hand.seats:
            raise ParseError("aucun siege")

        names = sorted((s.player for s in hand.seats), key=len, reverse=True)
        name_alt = "|".join(re.escape(n) for n in names)
        self._parse_actions(block, hand, name_alt)
        self._parse_cards(block, hand)

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
    def _parse_actions(self, block: str, hand: Hand, name_alt: str) -> None:
        rx_post = re.compile(
            rf"^(?P<name>{name_alt})\s+posts\s+(?P<what>small blind|big blind|ante|small \+ big blinds?|dead)\s+(?P<amt>\S+)",
            re.M | re.I)
        rx_act = re.compile(
            rf"^(?P<name>{name_alt})\s+(?P<verb>folds|checks|calls|bets|raises)"
            rf"(?:\s+(?P<amt>[\d.,]+\S*))?(?:\s+to\s+(?P<to>[\d.,]+\S*))?(?P<allin>\s+and is all-in)?\s*$",
            re.M | re.I)
        rx_collect = re.compile(rf"^(?P<name>{name_alt})\s+collected\s+(?P<amt>\S+)", re.M | re.I)
        rx_uncalled = re.compile(rf"^Uncalled bet\s+\((?P<amt>[^)]+)\)\s+returned to\s+(?P<name>{name_alt})", re.M | re.I)
        rx_show = re.compile(rf"^(?P<name>{name_alt})\s+shows\s+\[(?P<cards>[^\]]+)\]", re.M | re.I)

        marks = []
        for rx, street in STREET_MARKERS:
            mm = rx.search(block)
            if mm:
                cards = list(normalize_cards(mm.groupdict().get("c", "").split())) if "c" in mm.groupdict() else []
                marks.append((street, mm.end(), cards))
        marks.sort(key=lambda x: x[1])
        summ = RE_SUMMARY.search(block)
        end_all = summ.start() if summ else len(block)
        head_end = marks[0][1] if marks else end_all

        for pm in rx_post.finditer(block[:head_end]):
            what = pm.group("what").lower()
            amt = to_decimal(pm.group("amt"))
            atype = (ActionType.POST_ANTE if "ante" in what else
                     ActionType.POST_SB if what == "small blind" else
                     ActionType.POST_BB if what == "big blind" else ActionType.POST_DEAD)
            hand.actions.append(Action(pm.group("name"), Street.PREFLOP, atype, amt, amt))

        for i, (street, start, cards) in enumerate(marks):
            end = marks[i + 1][1] if i + 1 < len(marks) else end_all
            end = min(end, end_all)
            for c in cards:
                if c not in hand.board:
                    hand.board.append(c)
            committed: dict[str, Decimal] = {}
            if street == Street.PREFLOP:
                for a in hand.actions:
                    if a.type.is_blind and a.type != ActionType.POST_ANTE:
                        committed[a.player] = max(committed.get(a.player, Decimal(0)), a.to_amount)
            for am in rx_act.finditer(block[start:end]):
                name, verb = am.group("name"), am.group("verb").lower()
                allin = bool(am.group("allin"))
                amt, to_amt = to_decimal(am.group("amt")), to_decimal(am.group("to"))
                if verb == "folds":
                    hand.actions.append(Action(name, street, ActionType.FOLD))
                elif verb == "checks":
                    hand.actions.append(Action(name, street, ActionType.CHECK))
                elif verb in ("calls", "bets"):
                    committed[name] = committed.get(name, Decimal(0)) + amt
                    atype = ActionType.CALL if verb == "calls" else ActionType.BET
                    hand.actions.append(Action(name, street, atype, amt, committed[name], allin))
                else:
                    total = to_amt or (committed.get(name, Decimal(0)) + amt)
                    paid = total - committed.get(name, Decimal(0))
                    committed[name] = total
                    hand.actions.append(Action(name, street, ActionType.RAISE, paid, total, allin))
            for sm in rx_show.finditer(block[start:end]):
                seat = hand.seat_of(sm.group("name"))
                if seat:
                    seat.cards = normalize_cards(sm.group("cards").split())
                    seat.showed = True

        for um in rx_uncalled.finditer(block):
            hand.actions.append(Action(um.group("name"), Street.SHOWDOWN, ActionType.UNCALLED,
                                       to_decimal(um.group("amt"))))
        collected = False
        for cm in rx_collect.finditer(block):
            collected = True
            hand.actions.append(Action(cm.group("name"), Street.SHOWDOWN, ActionType.COLLECT,
                                       to_decimal(cm.group("amt"))))
        if not collected:  # Winamax n'ecrit les gains que dans le resume
            for wm in RE_SUMMARY_WON.finditer(block):
                seat = hand.seat_of(wm.group("name").strip())
                if seat:
                    hand.actions.append(Action(seat.player, Street.SHOWDOWN, ActionType.COLLECT,
                                               to_decimal(wm.group("amt"))))

    def _parse_cards(self, block: str, hand: Hand) -> None:
        d = RE_DEALT.search(block)
        if d:
            seat = hand.seat_of(d.group("name").strip())
            if seat:
                hand.hero = seat.player
                seat.is_hero = True
                seat.cards = normalize_cards(d.group("cards").split())
        for sm in RE_SUMMARY_SHOWED.finditer(block):
            seat = hand.seat_of(sm.group("name").strip())
            if seat and not seat.cards:
                seat.cards = normalize_cards(sm.group("cards").split())
                seat.showed = True


registry.register(WinamaxParser())
