"""Extraction des compteurs statistiques d'une main.

Chaque main est parcourue une seule fois et produit, pour chaque joueur
assis, un dictionnaire `compteur -> valeur`. Les statistiques affichees
(VPIP, PFR, 3Bet, C-Bet...) sont ensuite obtenues en agregeant ces
compteurs sur l'ensemble des mains puis en divisant l'action par
l'opportunite (voir `definitions.py`).

Ce decoupage "compteur brut / stat derivee" est ce qui permet de filtrer
n'importe quel sous-ensemble de mains (position, stack, nombre de joueurs,
adversaire...) sans jamais recalculer les mains une par une.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict

from ..models import Action, ActionType, Hand, Street

STREET_CODE = {Street.FLOP: "f", Street.TURN: "t", Street.RIVER: "r"}
POSTFLOP_STREETS = (Street.FLOP, Street.TURN, Street.RIVER)

#: compteurs entiers stockes en base (une colonne par compteur)
COUNTERS: list[str] = [
    "hands", "hands_won", "walks",
    # --- preflop ---
    "vpip", "vpip_opp", "pfr", "pfr_opp",
    "rfi", "rfi_opp",
    "limp", "limp_opp", "limp_call", "limp_fold", "limp_raise",
    "iso_raise", "iso_opp",
    "cold_call", "cold_call_opp",
    "three_bet", "three_bet_opp", "four_bet", "four_bet_opp", "five_bet", "five_bet_opp",
    "fold_to_3bet", "fold_to_3bet_opp", "call_3bet", "raise_vs_3bet",
    "fold_to_4bet", "fold_to_4bet_opp", "call_4bet",
    "cold_4bet", "cold_4bet_opp",
    "squeeze", "squeeze_opp",
    "steal", "steal_opp",
    "fold_to_steal", "fold_to_steal_opp", "call_vs_steal", "resteal", "resteal_opp",
    "allin_pf",
    "saw_flop", "saw_turn", "saw_river",
    # --- postflop (suffixes f/t/r) ---
    *[f"{name}_{s}" for s in "ftr" for name in (
        "bet", "raise", "call", "fold", "check",
        "cbet", "cbet_opp",
        "fold_to_cbet", "fold_to_cbet_opp", "call_cbet", "raise_cbet",
        "donk", "donk_opp",
        "fold_to_bet", "fold_to_bet_opp",
        "checkraise", "checkraise_opp",
        "probe", "probe_opp",
        "dcbet", "dcbet_opp",
    )],
    # --- showdown ---
    "wtsd", "wtsd_opp", "wsd", "wsd_opp", "wwsf", "wwsf_opp",
    "showdowns", "allin_postflop",
]

#: compteurs a virgule (gains, mises) stockes en REAL
FLOAT_COUNTERS: list[str] = ["amount_won", "amount_net", "bb_net", "invested", "rake_paid"]

ALL_COUNTERS = COUNTERS + FLOAT_COUNTERS


def _new_row() -> Dict[str, float]:
    row = {c: 0 for c in COUNTERS}
    row.update({c: 0.0 for c in FLOAT_COUNTERS})
    return row


class HandCounters:
    """Calcule les compteurs de tous les joueurs d'une main."""

    def __init__(self, hand: Hand) -> None:
        self.hand = hand
        self.rows: Dict[str, Dict[str, float]] = {s.player: _new_row() for s in hand.seats}
        self._pf_aggressor: str = ""
        self._streets_checked: set[Street] = set()

    # ------------------------------------------------------------------
    def compute(self) -> Dict[str, Dict[str, float]]:
        hand = self.hand
        bb = float(hand.big_blind() or 1)
        for seat in hand.seats:
            row = self.rows[seat.player]
            row["hands"] = 1
            row["amount_won"] = float(seat.won)
            row["amount_net"] = float(seat.net)
            row["invested"] = float(seat.invested)
            row["bb_net"] = float(seat.net) / bb
            row["hands_won"] = 1 if seat.won > 0 else 0

        folded = self._preflop()
        self._postflop(folded)
        self._showdown(folded)
        return self.rows

    # ------------------------------------------------------- preflop
    def _preflop(self) -> Dict[str, Street]:
        """Retourne, pour chaque joueur ayant couche, la street du fold."""
        hand = self.hand
        pos = {s.player: s.position for s in hand.seats}
        folded: Dict[str, Street] = {}

        actions = [a for a in hand.actions
                   if a.street == Street.PREFLOP and not a.type.is_blind
                   and a.type not in (ActionType.SHOW, ActionType.MUCK, ActionType.COLLECT,
                                      ActionType.UNCALLED)]
        blinds = {a.player for a in hand.actions if a.type in (ActionType.POST_SB, ActionType.POST_BB)}
        bb_player = next((a.player for a in hand.actions if a.type == ActionType.POST_BB), "")

        raises = 0                    # nombre de relances deja effectuees
        raisers: list[str] = []       # auteurs successifs des relances
        limpers: list[str] = []
        callers_after_raise: list[str] = []
        acted: set[str] = set()
        counted_vpip: set[str] = set()
        counted_pfr: set[str] = set()
        steal_attempt = False
        aggressor = ""

        if not actions and bb_player:
            self.rows[bb_player]["walks"] = 1

        for a in actions:
            p = a.player
            row = self.rows.get(p)
            if row is None:
                continue
            first_decision = p not in acted
            acted.add(p)

            # ---- opportunites (avant de connaitre l'action)
            if first_decision:
                row["vpip_opp"] += 1
                row["pfr_opp"] += 1
            unopened = raises == 0 and not limpers
            if unopened and first_decision and p != bb_player:
                row["rfi_opp"] += 1
                row["limp_opp"] += 1
                if pos.get(p) in ("CO", "BTN", "SB"):
                    row["steal_opp"] += 1
            if raises == 0 and limpers and first_decision:
                row["iso_opp"] += 1
            if raises == 1:
                if first_decision:
                    row["three_bet_opp"] += 1
                    if p not in blinds or pos.get(p) == "BB":
                        row["cold_call_opp"] += 1
                    if callers_after_raise:
                        row["squeeze_opp"] += 1
                    if steal_attempt and pos.get(p) in ("SB", "BB"):
                        row["fold_to_steal_opp"] += 1
                        row["resteal_opp"] += 1
            elif raises == 2:
                if p == raisers[0]:
                    row["fold_to_3bet_opp"] += 1
                    row["four_bet_opp"] += 1
                else:
                    row["cold_4bet_opp"] += 1
            elif raises == 3:
                if p == raisers[1]:
                    row["fold_to_4bet_opp"] += 1
                row["five_bet_opp"] += 1

            # ---- action
            if a.type == ActionType.FOLD:
                folded[p] = Street.PREFLOP
                if raises == 1 and steal_attempt and pos.get(p) in ("SB", "BB"):
                    row["fold_to_steal"] += 1
                if raises == 2 and p == raisers[0]:
                    row["fold_to_3bet"] += 1
                if raises == 3 and len(raisers) > 1 and p == raisers[1]:
                    row["fold_to_4bet"] += 1
                if p in limpers:
                    row["limp_fold"] += 1
                continue

            if a.type == ActionType.CALL:
                if p not in counted_vpip:
                    counted_vpip.add(p)
                    row["vpip"] = 1
                if raises == 0:
                    if p != bb_player:
                        row["limp"] += 1
                        limpers.append(p)
                elif raises == 1:
                    if first_decision and (p not in blinds or pos.get(p) == "BB"):
                        row["cold_call"] += 1
                    if steal_attempt and pos.get(p) in ("SB", "BB"):
                        row["call_vs_steal"] += 1
                    if p in limpers:
                        row["limp_call"] += 1
                    callers_after_raise.append(p)
                elif raises == 2:
                    if p == raisers[0]:
                        row["call_3bet"] += 1
                elif raises >= 3:
                    if len(raisers) > 1 and p == raisers[1]:
                        row["call_4bet"] += 1
                if a.allin:
                    row["allin_pf"] += 1
                continue

            if a.type in (ActionType.RAISE, ActionType.BET):
                if p not in counted_vpip:
                    counted_vpip.add(p)
                    row["vpip"] = 1
                if p not in counted_pfr:
                    counted_pfr.add(p)
                    row["pfr"] = 1
                if raises == 0:
                    if not limpers:
                        row["rfi"] += 1
                        if pos.get(p) in ("CO", "BTN", "SB"):
                            row["steal"] += 1
                            steal_attempt = True
                    else:
                        row["iso_raise"] += 1
                    if p in limpers:
                        row["limp_raise"] += 1
                elif raises == 1:
                    row["three_bet"] += 1
                    if callers_after_raise:
                        row["squeeze"] += 1
                    if steal_attempt and pos.get(p) in ("SB", "BB"):
                        row["resteal"] += 1
                elif raises == 2:
                    if p == raisers[0]:
                        row["four_bet"] += 1
                        row["raise_vs_3bet"] += 1
                    else:
                        row["cold_4bet"] += 1
                else:
                    row["five_bet"] += 1
                if a.allin:
                    row["allin_pf"] += 1
                raises += 1
                raisers.append(p)
                aggressor = p
                callers_after_raise.clear()
                continue

        self._pf_aggressor = aggressor
        return folded

    # ------------------------------------------------------ postflop
    def _postflop(self, folded: Dict[str, Street]) -> None:
        hand = self.hand
        aggressor = self._pf_aggressor
        last_aggr_street = Street.PREFLOP if aggressor else None
        seat_order = {s.player: s.seat_no for s in hand.seats}

        for street in POSTFLOP_STREETS:
            if not hand.reached(street):
                break
            code = STREET_CODE[street]
            in_hand = [p for p in seat_order if p not in folded]
            if len(in_hand) < 2:
                break
            for p in in_hand:
                row = self.rows.get(p)
                if row is None:
                    continue
                row[f"saw_{'flop' if street == Street.FLOP else 'turn' if street == Street.TURN else 'river'}"] = 1

            actions = [a for a in hand.actions if a.street == street
                       and a.type in (ActionType.FOLD, ActionType.CHECK, ActionType.CALL,
                                      ActionType.BET, ActionType.RAISE)]
            checked: set[str] = set()
            acted: set[str] = set()
            bettor = ""            # auteur de la premiere mise de la street
            is_cbet = False        # cette premiere mise est-elle un c-bet ?
            facing_raise = False
            street_aggressor = ""
            # le dernier agresseur est-il encore dans le coup ?
            aggr_alive = bool(aggressor) and aggressor not in folded
            aggr_acted = False
            for a in actions:
                p = a.player
                row = self.rows.get(p)
                if row is None:
                    continue
                first = p not in acted
                acted.add(p)

                if not bettor:  # personne n'a encore mise sur cette street
                    if first:
                        if p == aggressor and aggr_alive:
                            if last_aggr_street == Street.PREFLOP and street == Street.FLOP:
                                row[f"cbet_opp_{code}"] += 1
                            elif self._prev_street_checked(street):
                                row[f"dcbet_opp_{code}"] += 1
                            else:
                                row[f"cbet_opp_{code}"] += 1
                        elif aggr_alive and not aggr_acted:
                            row[f"donk_opp_{code}"] += 1
                        else:
                            row[f"probe_opp_{code}"] += 1

                    if a.type == ActionType.CHECK:
                        row[f"check_{code}"] += 1
                        checked.add(p)
                    elif a.type in (ActionType.BET, ActionType.RAISE):
                        row[f"bet_{code}"] += 1
                        bettor = p
                        street_aggressor = p
                        if p == aggressor and aggr_alive:
                            if self._prev_street_checked(street) and street != Street.FLOP:
                                row[f"dcbet_{code}"] += 1
                            else:
                                row[f"cbet_{code}"] += 1
                                is_cbet = True
                        elif aggr_alive and not aggr_acted:
                            row[f"donk_{code}"] += 1
                        else:
                            row[f"probe_{code}"] += 1
                    elif a.type == ActionType.FOLD:
                        folded[p] = street
                    if p == aggressor:
                        aggr_acted = True
                    continue

                # ---- un joueur fait face a une mise
                row[f"fold_to_bet_opp_{code}"] += 1
                if is_cbet and street_aggressor == bettor and not facing_raise:
                    row[f"fold_to_cbet_opp_{code}"] += 1
                if p in checked and not facing_raise:
                    row[f"checkraise_opp_{code}"] += 1

                if a.type == ActionType.FOLD:
                    row[f"fold_{code}"] += 1
                    row[f"fold_to_bet_{code}"] += 1
                    if is_cbet and street_aggressor == bettor and not facing_raise:
                        row[f"fold_to_cbet_{code}"] += 1
                    folded[p] = street
                elif a.type == ActionType.CALL:
                    row[f"call_{code}"] += 1
                    if is_cbet and street_aggressor == bettor and not facing_raise:
                        row[f"call_cbet_{code}"] += 1
                elif a.type == ActionType.CHECK:
                    row[f"check_{code}"] += 1
                    checked.add(p)
                elif a.type in (ActionType.BET, ActionType.RAISE):
                    row[f"raise_{code}"] += 1
                    if is_cbet and street_aggressor == bettor and not facing_raise:
                        row[f"raise_cbet_{code}"] += 1
                    if p in checked:
                        row[f"checkraise_{code}"] += 1
                    facing_raise = True
                    street_aggressor = p
                if p == aggressor:
                    aggr_acted = True
                if a.allin:
                    self.rows[p]["allin_postflop"] += 1

            if street_aggressor:
                aggressor = street_aggressor
                last_aggr_street = street
            else:
                self._streets_checked.add(street)

    def _prev_street_checked(self, street: Street) -> bool:
        checked = self._streets_checked
        prev = {Street.TURN: Street.FLOP, Street.RIVER: Street.TURN}.get(street)
        return prev in checked

    # ----------------------------------------------------- showdown
    def _showdown(self, folded: Dict[str, Street]) -> None:
        hand = self.hand
        saw_flop = [s.player for s in hand.seats if self.rows[s.player]["saw_flop"]]
        showdown = [s for s in hand.seats if s.showed] if any(s.showed for s in hand.seats) else []
        sd_players = {s.player for s in showdown}
        if not sd_players and hand.reached(Street.RIVER):
            alive = [s.player for s in hand.seats if s.player not in folded]
            if len(alive) > 1:
                sd_players = set(alive)

        for p in saw_flop:
            row = self.rows[p]
            row["wwsf_opp"] = 1
            row["wtsd_opp"] = 1
            if self._won(p):
                row["wwsf"] = 1
            if p in sd_players:
                row["wtsd"] = 1
                row["wsd_opp"] = 1
                row["showdowns"] = 1
                if self._won(p):
                    row["wsd"] = 1

    def _won(self, player: str) -> bool:
        seat = self.hand.seat_of(player)
        return bool(seat and seat.won > 0)


def compute_hand_counters(hand: Hand) -> Dict[str, Dict[str, float]]:
    return HandCounters(hand).compute()
