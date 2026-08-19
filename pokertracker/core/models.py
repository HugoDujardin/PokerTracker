"""Modele de donnees d'une main de poker.

Ces structures sont produites par les parsers (un par room) et consommees
par le moteur de statistiques, le replayer et le HUD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable, Optional


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"

    @property
    def index(self) -> int:
        return _STREET_ORDER.index(self)

    def next(self) -> "Street":
        i = _STREET_ORDER.index(self)
        return _STREET_ORDER[min(i + 1, len(_STREET_ORDER) - 1)]


_STREET_ORDER = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER, Street.SHOWDOWN]


class ActionType(str, Enum):
    POST_SB = "post_sb"
    POST_BB = "post_bb"
    POST_ANTE = "post_ante"
    POST_STRADDLE = "post_straddle"
    POST_DEAD = "post_dead"
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALLIN = "allin"
    SHOW = "show"
    MUCK = "muck"
    UNCALLED = "uncalled"
    COLLECT = "collect"

    @property
    def is_voluntary(self) -> bool:
        return self in (ActionType.CALL, ActionType.BET, ActionType.RAISE)

    @property
    def is_aggressive(self) -> bool:
        return self in (ActionType.BET, ActionType.RAISE)

    @property
    def is_blind(self) -> bool:
        return self in (
            ActionType.POST_SB,
            ActionType.POST_BB,
            ActionType.POST_ANTE,
            ActionType.POST_STRADDLE,
            ActionType.POST_DEAD,
        )


class GameType(str, Enum):
    NLHE = "nlhe"
    PLO = "plo"
    PLO5 = "plo5"
    LHE = "lhe"
    OTHER = "other"


class TableFormat(str, Enum):
    CASH = "cash"
    MTT = "mtt"
    SNG = "sng"
    SPIN = "spin"


# Positions relatives au bouton. `BB` est la grosse blinde, `BTN` le bouton.
POSITIONS_BY_SIZE = {
    2: ["BTN", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["CO", "BTN", "SB", "BB"],
    5: ["MP", "CO", "BTN", "SB", "BB"],
    6: ["UTG", "MP", "CO", "BTN", "SB", "BB"],
    7: ["UTG", "UTG1", "MP", "CO", "BTN", "SB", "BB"],
    8: ["UTG", "UTG1", "MP", "MP1", "CO", "BTN", "SB", "BB"],
    9: ["UTG", "UTG1", "UTG2", "MP", "MP1", "HJ", "CO", "BTN", "SB", "BB"][:9],
    10: ["UTG", "UTG1", "UTG2", "MP", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB"][:10],
}

#: Regroupement utilise par les rapports et les conditions du HUD dynamique.
POSITION_GROUPS = {
    "EP": {"UTG", "UTG1", "UTG2"},
    "MP": {"MP", "MP1", "MP2", "HJ"},
    "CO": {"CO"},
    "BTN": {"BTN"},
    "SB": {"SB"},
    "BB": {"BB"},
}


@dataclass(slots=True)
class Action:
    player: str
    street: Street
    type: ActionType
    amount: Decimal = Decimal(0)
    #: mise totale du joueur sur la street apres l'action (utile pour les raises)
    to_amount: Decimal = Decimal(0)
    allin: bool = False
    order: int = 0

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{self.player} {self.street.value} {self.type.value} {self.amount}>"


@dataclass(slots=True)
class Seat:
    seat_no: int
    player: str
    stack: Decimal
    is_hero: bool = False
    is_button: bool = False
    position: str = ""
    cards: tuple[str, ...] = ()
    #: gain net de la main (gains - investissement)
    net: Decimal = Decimal(0)
    won: Decimal = Decimal(0)
    invested: Decimal = Decimal(0)
    showed: bool = False


@dataclass(slots=True)
class Hand:
    hand_id: str
    room: str
    played_at: datetime
    game: GameType = GameType.NLHE
    table_format: TableFormat = TableFormat.CASH
    table_name: str = ""
    max_seats: int = 6
    sb: Decimal = Decimal(0)
    bb: Decimal = Decimal(1)
    ante: Decimal = Decimal(0)
    currency: str = "USD"
    button_seat: int = 0
    hero: str = ""
    seats: list[Seat] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    pot: Decimal = Decimal(0)
    rake: Decimal = Decimal(0)
    tournament_id: str = ""
    buyin: Decimal = Decimal(0)
    #: False pour les tables et tournois en argent fictif (exclus par defaut
    #: des statistiques, des rapports et du suivi financier)
    real_money: bool = True
    raw_text: str = ""

    # ------------------------------------------------------------------ utils
    def seat_of(self, player: str) -> Optional[Seat]:
        for s in self.seats:
            if s.player == player:
                return s
        return None

    def players(self) -> list[str]:
        return [s.player for s in self.seats]

    @property
    def nb_players(self) -> int:
        return len(self.seats)

    def street_actions(self, street: Street) -> list[Action]:
        return [a for a in self.actions if a.street == street and not a.type.is_blind]

    def board_of(self, street: Street) -> list[str]:
        sizes = {Street.PREFLOP: 0, Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5, Street.SHOWDOWN: 5}
        return self.board[: sizes[street]]

    def reached(self, street: Street) -> bool:
        return len(self.board) >= {Street.PREFLOP: 0, Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5,
                                   Street.SHOWDOWN: 5}[street]

    def big_blind(self) -> Decimal:
        return self.bb or Decimal(1)

    # ------------------------------------------------------- post-parsing fixups
    def assign_positions(self) -> None:
        """Calcule la position de chaque siege a partir du bouton."""
        if not self.seats:
            return
        seats = sorted(self.seats, key=lambda s: s.seat_no)
        btn_idx = next((i for i, s in enumerate(seats) if s.seat_no == self.button_seat), None)
        if btn_idx is None:
            btn_idx = 0
        n = len(seats)
        names = POSITIONS_BY_SIZE.get(n)
        if names is None:  # table exotique: on complete avec des UTG+n
            names = ["UTG"] + [f"UTG{i}" for i in range(1, n - 3)] + ["CO", "BTN", "SB", "BB"]
            names = names[-n:]
        btn_pos_idx = names.index("BTN")
        for offset in range(n):
            seat = seats[(btn_idx + offset) % n]
            seat.position = names[(btn_pos_idx + offset) % n]
            seat.is_button = seat.seat_no == self.button_seat

    def compute_results(self) -> None:
        """Renseigne `invested`, `won` et `net` pour chaque siege."""
        invested: dict[str, Decimal] = {s.player: Decimal(0) for s in self.seats}
        won: dict[str, Decimal] = {s.player: Decimal(0) for s in self.seats}
        for a in self.actions:
            if a.type in (ActionType.COLLECT, ActionType.UNCALLED):
                won[a.player] = won.get(a.player, Decimal(0)) + a.amount
            elif a.type in (ActionType.SHOW, ActionType.MUCK, ActionType.FOLD, ActionType.CHECK):
                continue
            else:
                invested[a.player] = invested.get(a.player, Decimal(0)) + a.amount
        for s in self.seats:
            s.invested = invested.get(s.player, Decimal(0))
            s.won = won.get(s.player, Decimal(0))
            s.net = s.won - s.invested

    def finalize(self) -> None:
        for i, a in enumerate(self.actions):
            a.order = i
        self.assign_positions()
        self.compute_results()
        if not self.pot:
            self.pot = sum((s.invested for s in self.seats), Decimal(0))


def normalize_cards(cards: Iterable[str]) -> tuple[str, ...]:
    """Uniformise la casse des cartes: 'ah' -> 'Ah'."""
    out = []
    for c in cards:
        c = c.strip()
        if len(c) == 2:
            out.append(c[0].upper() + c[1].lower())
        elif len(c) == 3 and c[0] == "1":  # '10h'
            out.append("T" + c[2].lower())
    return tuple(out)
