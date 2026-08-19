"""Coordination du HUD: etat des tables, calcul des stats, mise en page.

Ce module ne depend pas de Qt: il produit une description de ce qui doit
etre affiche (`TableHud`), que la couche graphique se contente de dessiner.
Il est donc testable sans interface.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..core.db import Database, Filter
from ..core.models import Hand
from ..core.stats import definitions as sd
from .profile import HudPanel, HudProfile, PlayerContext, StatCell
from .seatmap import seat_positions
from .table_tracker import TableTracker, TableWindow


@dataclass
class SeatState:
    seat_no: int
    player: str
    stack: float = 0.0
    stack_bb: float = 0.0
    position: str = ""
    next_position: str = ""
    is_hero: bool = False


@dataclass
class TableState:
    """Derniere photographie connue d'une table, reconstruite a partir des
    mains importees en temps reel."""
    room: str
    table_name: str
    max_seats: int = 6
    button_seat: int = 0
    bb: float = 1.0
    table_format: str = "cash"
    game: str = "nlhe"
    hero: str = ""
    seats: Dict[int, SeatState] = field(default_factory=dict)
    last_hand_id: str = ""
    updated_at: float = field(default_factory=time.time)

    def players(self) -> List[str]:
        return [s.player for s in self.seats.values()]

    def update_from_hand(self, hand: Hand) -> None:
        self.max_seats = hand.max_seats or self.max_seats
        self.button_seat = hand.button_seat
        self.bb = float(hand.big_blind() or 1)
        self.table_format = hand.table_format.value
        self.game = hand.game.value
        self.hero = hand.hero or self.hero
        self.last_hand_id = hand.hand_id
        self.updated_at = time.time()
        seats: Dict[int, SeatState] = {}
        for s in hand.seats:
            stack = float(s.stack) + float(s.net)      # tapis estime a la main suivante
            seats[s.seat_no] = SeatState(
                seat_no=s.seat_no, player=s.player, stack=stack,
                stack_bb=stack / self.bb if self.bb else 0.0,
                position=s.position, is_hero=s.is_hero,
            )
        self.seats = seats
        self._predict_next_positions()

    def _predict_next_positions(self) -> None:
        """Le bouton avance d'un siege occupe: on en deduit la position que
        chaque joueur occupera a la main suivante (HUD dynamique)."""
        from ..core.models import POSITIONS_BY_SIZE
        occupied = sorted(self.seats)
        if not occupied:
            return
        if self.button_seat in occupied:
            idx = occupied.index(self.button_seat)
        else:
            idx = 0
        next_button = occupied[(idx + 1) % len(occupied)]
        n = len(occupied)
        names = POSITIONS_BY_SIZE.get(n)
        if not names:
            names = ["UTG"] + [f"UTG{i}" for i in range(1, max(1, n - 3))] + ["CO", "BTN", "SB", "BB"]
            names = names[-n:]
        btn_idx = names.index("BTN")
        start = occupied.index(next_button)
        for offset in range(n):
            seat = occupied[(start + offset) % n]
            self.seats[seat].next_position = names[(btn_idx + offset) % n]


@dataclass
class HudCell:
    text: str
    color: str
    title: str
    code: str


@dataclass
class HudPlayerPanel:
    player: str
    seat_no: int
    position: str
    hands: int
    rows: List[List[HudCell]]
    panel: HudPanel
    rel_x: float = 0.0
    rel_y: float = 0.0
    is_hero: bool = False
    note: str = ""
    color: str = ""


@dataclass
class TableHud:
    window: TableWindow
    state: Optional[TableState]
    panels: List[HudPlayerPanel] = field(default_factory=list)


class HudManager:
    """Fait le lien entre les mains importees, la base et les fenetres de table."""

    def __init__(self, db: Database, profile: HudProfile, tracker: Optional[TableTracker] = None,
                 min_hands: int = 0, filter_by_game: bool = True) -> None:
        self.db = db
        self.profile = profile
        self.tracker = tracker or TableTracker()
        self.min_hands = min_hands
        #: n'affiche que les statistiques de la variante jouee a la table
        #: (sinon Hold'em et Omaha seraient melanges)
        self.filter_by_game = filter_by_game
        self.tables: Dict[str, TableState] = {}
        #: affiche la derniere table connue quand une fenetre n'est pas reconnue
        self.fallback_to_last_table = True
        self._stats_cache: Dict[Tuple[str, str, str], dict] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ mise a jour
    def on_new_hands(self, hands: Sequence[Hand]) -> None:
        with self._lock:
            for hand in hands:
                key = self.table_key(hand.room, hand.table_name)
                state = self.tables.get(key)
                if state is None:
                    state = TableState(room=hand.room, table_name=hand.table_name)
                    self.tables[key] = state
                state.update_from_hand(hand)
                for seat in hand.seats:                 # les stats du joueur ont change
                    for key in [k for k in self._stats_cache
                                if k[0] == seat.player and k[1] == hand.room]:
                        self._stats_cache.pop(key, None)

    def restore_recent_tables(self, limit: int = 12) -> int:
        """Reconstruit l'etat des dernieres tables jouees depuis la base.

        Appele au demarrage: sans cela, le HUD reste vide tant qu'aucune
        nouvelle main n'a ete importee.
        """
        from ..core.parsers import registry
        restored = 0
        for row in self.db.recent_table_hands(limit):
            raw = row["raw_text"] or ""
            if not raw:
                continue
            hands = list(registry.parse_text(raw))
            if hands:
                self.on_new_hands(hands[:1])
                restored += 1
        return restored

    @staticmethod
    def table_key(room: str, table_name: str) -> str:
        return f"{room}:{(table_name or '').strip().lower()}"

    def forget_old_tables(self, max_age: float = 3600) -> None:
        now = time.time()
        with self._lock:
            for key in [k for k, s in self.tables.items() if now - s.updated_at > max_age]:
                self.tables.pop(key, None)

    # ---------------------------------------------------------------- stats
    def stats_for(self, player: str, room: str, scope: str = "all", position: str = "",
                  game: str = "") -> dict:
        """Statistiques d'un joueur, limitees a la variante jouee si demande."""
        game = game if self.filter_by_game else ""
        key = (player, room, f"{position if scope == 'position' else 'all'}|{game}")
        cached = self._stats_cache.get(key)
        if cached is not None:
            return cached
        flt = Filter(games=[game] if game else ())
        if scope == "position" and position:
            flt.positions = [position]
        agg = self.db.aggregate_many([player], room=room, flt=flt).get(player, {})
        self._stats_cache[key] = agg
        return agg

    def invalidate(self) -> None:
        with self._lock:
            self._stats_cache.clear()

    # ------------------------------------------------------------- rendu
    def build_panels(self, state: TableState) -> List[HudPlayerPanel]:
        panels: List[HudPlayerPanel] = []
        hero_seat = next((s.seat_no for s in state.seats.values() if s.is_hero),
                         min(state.seats) if state.seats else 1)
        positions = seat_positions(list(state.seats), hero_seat, state.max_seats)
        for seat_no, seat in sorted(state.seats.items()):
            panel_ctx_position = seat.next_position or seat.position
            agg_all = self.stats_for(seat.player, state.room, game=state.game)
            hands = int(agg_all.get("hands", 0) or 0)
            if self.min_hands and hands < self.min_hands and not seat.is_hero:
                continue
            ctx = PlayerContext(
                name=seat.player, position=panel_ctx_position, nb_players=len(state.seats),
                stack_bb=seat.stack_bb, hands=hands, table_format=state.table_format,
                is_hero=seat.is_hero,
            )
            panel = self.profile.panel_for(ctx)
            if panel is None:
                continue
            agg = (self.stats_for(seat.player, state.room, "position", panel_ctx_position,
                                  game=state.game)
                   if panel.scope == "position" else agg_all)
            rows: List[List[HudCell]] = []
            for row in panel.rows:
                cells = []
                for cell in row:
                    text, color = cell.display(agg)
                    cells.append(HudCell(text=text, color=color, title=cell.title(), code=cell.code))
                rows.append(cells)
            player_row = self.db.get_player(seat.player, state.room)
            rel = positions.get(seat_no, (0.4, 0.4))
            panels.append(HudPlayerPanel(
                player=seat.player, seat_no=seat_no, position=panel_ctx_position, hands=hands,
                rows=rows, panel=panel, rel_x=rel[0], rel_y=rel[1], is_hero=seat.is_hero,
                note=(player_row["note"] if player_row else "") or "",
                color=(player_row["color"] if player_row else "") or "",
            ))
        return panels

    # --------------------------------------------------------- appariement
    def match_window(self, window: TableWindow) -> Optional[TableState]:
        """Associe une fenetre de table a l'etat reconstruit depuis les mains."""
        with self._lock:
            key = self.table_key(window.room, window.table_name)
            if key in self.tables:
                return self.tables[key]
            title = (window.table_name or window.title).strip().lower()
            best: Optional[TableState] = None
            for state in self.tables.values():
                name = (state.table_name or "").strip().lower()
                if not name:
                    continue
                if name in title or title in name:
                    if best is None or state.updated_at > best.updated_at:
                        best = state
            if best is not None:
                return best
            if window.room:
                same_room = [s for s in self.tables.values() if s.room == window.room]
                if len(same_room) == 1:
                    return same_room[0]
            if len(self.tables) == 1:
                return next(iter(self.tables.values()))
            if self.fallback_to_last_table and self.tables:
                # aucune correspondance: on affiche la derniere table connue
                # (utile pour la table de demonstration et au demarrage)
                return max(self.tables.values(), key=lambda s: s.updated_at)
            return None

    def snapshot(self) -> List[TableHud]:
        """Ce que le HUD doit afficher a l'instant present."""
        out: List[TableHud] = []
        for window in self.tracker.list_tables():
            state = self.match_window(window)
            panels = self.build_panels(state) if state else []
            out.append(TableHud(window=window, state=state, panels=panels))
        return out

    # ------------------------------------------------------------- popups
    #: statistiques detaillees par position dans le popup
    POPUP_POSITION_STATS = ("vpip", "pfr", "3bet", "steal", "fsteal", "wwsf")

    def popup_data(self, player: str, room: str,
                   game: str = "") -> List[tuple[str, List[tuple[str, str, int]]]]:
        """Contenu du popup detaille d'un joueur, par section."""
        agg = self.stats_for(player, room, game=game)
        sections = []
        for section in self.profile.popups:
            rows = []
            for code in section.stats:
                stat = sd.get(code)
                if stat is None:
                    continue
                rows.append((stat.label, stat.format(agg), stat.sample(agg)))
            sections.append((section.title, rows))
        by_position = self.positional_stats(player, room, game)
        if by_position:
            sections.append(("Par position", by_position))
        return sections

    def positional_stats(self, player: str, room: str,
                         game: str = "") -> List[tuple[str, str, int]]:
        """Lignes 'position: VPIP/PFR/3Bet...' affichees dans le popup."""
        row = self.db.get_player(player, room)
        if row is None:
            return []
        game = game if self.filter_by_game else ""
        flt = Filter(games=[game] if game else ())
        groups = self.db.aggregate([row["id"]], flt, group_by="hp.position")
        order = [p for p in ("UTG", "UTG1", "UTG2", "MP", "MP1", "HJ", "CO", "BTN", "SB", "BB")
                 if p in groups]
        out: List[tuple[str, str, int]] = []
        for position in order:
            agg = groups[position]
            values = " ".join(f"{sd.get(c).format(agg):>3}" for c in self.POPUP_POSITION_STATS)
            out.append((position, values, int(agg.get("hands", 0) or 0)))
        if out:
            entete = " ".join(f"{sd.get(c).label[:3]:>3}" for c in self.POPUP_POSITION_STATS)
            out.insert(0, ("", entete, 0))
        return out

    def positional_table(self, player: str, room: str, codes: Sequence[str]) -> Dict[str, dict]:
        """Statistiques par position (onglet 'Positions' du popup)."""
        pid = self.db.get_player(player, room)
        if pid is None:
            return {}
        return self.db.aggregate([pid["id"]], group_by="hp.position")
