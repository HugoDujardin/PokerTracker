"""Parser des historiques PartyPoker (format 'Hand History for Game')."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..models import (Action, ActionType, GameType, Hand, Seat, Street, TableFormat,
                      detect_game, normalize_cards)
from .base import HandParser, ParseError, registry, to_decimal
from .dates import parse_datetime

RE_SPLIT = re.compile(r"\n\s*\n(?=\*{3,}\s*Hand History for Game)", re.I)
RE_GAME_ID = re.compile(r"Hand History for Game\s+(?P<hid>\d+)", re.I)
RE_STAKES = re.compile(
    r"^\s*(?:(?P<sb>[$\u20ac\u00a3]?[\d.,]+)\s*/\s*)?(?P<bb>[$\u20ac\u00a3]?[\d.,]+)\s*(?P<cur>USD|EUR|GBP)?\s*"
    r"(?P<game>[A-Za-z' ]*?Hold'?em|[A-Za-z' ]*?Omaha[^-]*?)\s*-\s*"
    r"(?P<date>.+?)\s*$",
    re.M | re.I,
)
RE_TOURNEY = re.compile(r"Tournament\s+#?(?P<tid>\d+)", re.I)
RE_TABLE = re.compile(r"^Table\s+(?P<name>.+?)\s*\((?P<money>Real|Play) Money\)", re.M | re.I)
RE_BUTTON = re.compile(r"^Seat\s+(?P<btn>\d+)\s+is\s+the\s+button", re.M | re.I)
RE_MAX = re.compile(r"Total number of players\s*:\s*\d+\s*/?\s*(?P<max>\d+)?", re.I)
RE_SEAT = re.compile(r"^Seat\s+(?P<no>\d+):\s+(?P<name>.+?)\s+\(\s*(?P<stack>[^)]+?)\s*\)\s*$", re.M)
RE_DEALT = re.compile(r"^Dealt to\s+(?P<name>.+?)\s+\[\s*(?P<cards>[^\]]+?)\s*\]", re.M | re.I)

STREET_MARKERS = [
    (re.compile(r"^\*\*\s*Dealing down cards\s*\*\*", re.M | re.I), Street.PREFLOP, None),
    (re.compile(r"^\*\*\s*Dealing Flop\s*\*\*\s*\[\s*(?P<c>[^\]]+?)\s*\]", re.M | re.I), Street.FLOP, "c"),
    (re.compile(r"^\*\*\s*Dealing Turn\s*\*\*\s*\[\s*(?P<c>[^\]]+?)\s*\]", re.M | re.I), Street.TURN, "c"),
    (re.compile(r"^\*\*\s*Dealing River\s*\*\*\s*\[\s*(?P<c>[^\]]+?)\s*\]", re.M | re.I), Street.RIVER, "c"),
    (re.compile(r"^\*\*\s*Summary\s*\*\*", re.M | re.I), Street.SHOWDOWN, None),
]


class PartyPokerParser(HandParser):
    room = "PartyPoker"
    end_marker = re.compile(r"\*\*\s*Summary\s*\*\*", re.I)

    def detect(self, text: str) -> bool:
        return bool(re.search(r"\*{3,}\s*Hand History for Game", text[:4000], re.I))

    def split_hands(self, text: str) -> Iterator[str]:
        text = text.replace("\r\n", "\n")
        for block in RE_SPLIT.split(text):
            if "Hand History for Game" in block:
                yield block

    def parse_hand(self, block: str) -> Hand:
        gid = RE_GAME_ID.search(block)
        st = RE_STAKES.search(block)
        if not gid or not st:
            raise ParseError("en-tete PartyPoker introuvable")
        played_at = parse_datetime(st.group("date"))
        if played_at is None:
            # ne jamais retomber sur la date du jour: cela fausserait tous les
            # filtres par periode (ils porteraient sur la date d'import)
            raise ParseError(f"date illisible: {st.group('date')!r}")

        bb = to_decimal(st.group("bb"))
        sb = to_decimal(st.group("sb")) if st.group("sb") else bb / 2
        hand = Hand(
            hand_id=gid.group("hid"),
            room=self.room,
            played_at=played_at,
            game=detect_game(st.group("game")),
            sb=sb,
            bb=bb,
            currency=st.group("cur") or "USD",
            raw_text=block,
        )
        tm = RE_TOURNEY.search(block)
        if tm:
            hand.table_format = TableFormat.MTT
            hand.tournament_id = tm.group("tid")
        t = RE_TABLE.search(block)
        if t:
            hand.table_name = t.group("name").strip()
            hand.real_money = t.group("money").lower() == "real"
        b = RE_BUTTON.search(block)
        if b:
            hand.button_seat = int(b.group("btn"))
        mx = RE_MAX.search(block)
        if mx and mx.group("max"):
            hand.max_seats = int(mx.group("max"))

        for sm in RE_SEAT.finditer(block):
            hand.seats.append(Seat(int(sm.group("no")), sm.group("name").strip(),
                                   to_decimal(sm.group("stack"))))
        if not hand.seats:
            raise ParseError("aucun siege")
        hand.max_seats = max(hand.max_seats, len(hand.seats))

        names = sorted((s.player for s in hand.seats), key=len, reverse=True)
        alt = "|".join(re.escape(n) for n in names)
        self._parse_actions(block, hand, alt)

        d = RE_DEALT.search(block)
        if d:
            seat = hand.seat_of(d.group("name").strip())
            if seat:
                hand.hero = seat.player
                seat.is_hero = True
                seat.cards = normalize_cards(re.split(r"[ ,]+", d.group("cards").strip()))
        hand.finalize()
        return hand

    def _parse_actions(self, block: str, hand: Hand, alt: str) -> None:
        rx_post = re.compile(rf"^(?P<name>{alt})\s+posts\s+(?P<what>small blind|big blind|ante|dead blind)\s*\[(?P<amt>[^\]]+)\]", re.M | re.I)
        rx_act = re.compile(
            rf"^(?P<name>{alt})\s+(?P<verb>folds|checks|calls|bets|raises|is all-In|is all-in)"
            rf"(?:\s*\[(?P<amt>[^\]]+)\])?\.?\s*$", re.M | re.I)
        rx_show = re.compile(rf"^(?P<name>{alt})\s+(?:shows|doesn't show)\s*\[\s*(?P<cards>[^\]]+?)\s*\]", re.M | re.I)
        rx_win = re.compile(rf"^(?P<name>{alt})\s+wins\s+(?P<amt>[\d.,]+)", re.M | re.I)

        marks = []
        for rx, street, grp in STREET_MARKERS:
            mm = rx.search(block)
            if mm:
                cards = list(normalize_cards(re.split(r"[ ,]+", mm.group(grp).strip()))) if grp else []
                marks.append((street, mm.end(), cards, mm.start()))
        marks.sort(key=lambda x: x[1])
        end_all = next((m[3] for m in marks if m[0] == Street.SHOWDOWN), len(block))
        head_end = marks[0][1] if marks else end_all

        for pm in rx_post.finditer(block[:head_end]):
            what = pm.group("what").lower()
            amt = to_decimal(pm.group("amt"))
            atype = (ActionType.POST_ANTE if "ante" in what else
                     ActionType.POST_SB if what == "small blind" else
                     ActionType.POST_BB if what == "big blind" else ActionType.POST_DEAD)
            hand.actions.append(Action(pm.group("name"), Street.PREFLOP, atype, amt, amt))

        for i, (street, start, cards, _s) in enumerate(marks):
            if street == Street.SHOWDOWN:
                continue
            end = marks[i + 1][1] if i + 1 < len(marks) else end_all
            for c in cards:
                if c not in hand.board:
                    hand.board.append(c)
            committed: dict[str, Decimal] = {}
            if street == Street.PREFLOP:
                for a in hand.actions:
                    if a.type.is_blind and a.type != ActionType.POST_ANTE:
                        committed[a.player] = max(committed.get(a.player, Decimal(0)), a.to_amount)
            for am in rx_act.finditer(block[start:end]):
                name = am.group("name")
                verb = am.group("verb").lower().replace("is all-in", "allin")
                amt = to_decimal(am.group("amt"))
                if verb == "folds":
                    hand.actions.append(Action(name, street, ActionType.FOLD))
                elif verb == "checks":
                    hand.actions.append(Action(name, street, ActionType.CHECK))
                elif verb == "calls":
                    committed[name] = committed.get(name, Decimal(0)) + amt
                    hand.actions.append(Action(name, street, ActionType.CALL, amt, committed[name]))
                elif verb == "bets":
                    committed[name] = committed.get(name, Decimal(0)) + amt
                    hand.actions.append(Action(name, street, ActionType.BET, amt, committed[name]))
                else:
                    # PartyPoker donne le montant total mise par le joueur sur la street
                    prev = committed.get(name, Decimal(0))
                    total = max(amt + prev, prev)
                    paid = total - prev
                    committed[name] = total
                    highest = max([c for p, c in committed.items() if p != name] or [Decimal(0)])
                    atype = ActionType.RAISE if total > highest or verb == "raises" else ActionType.CALL
                    hand.actions.append(Action(name, street, atype, paid, total, verb == "allin"))

        for sm in rx_show.finditer(block):
            seat = hand.seat_of(sm.group("name"))
            if seat:
                seat.cards = normalize_cards(re.split(r"[ ,]+", sm.group("cards").strip()))
                seat.showed = True
        for wm in rx_win.finditer(block):
            hand.actions.append(Action(wm.group("name"), Street.SHOWDOWN, ActionType.COLLECT,
                                       to_decimal(wm.group("amt"))))


registry.register(PartyPokerParser())
