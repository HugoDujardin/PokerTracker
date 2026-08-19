"""Gains ajustes a l'equite (« all-in EV »).

Quand tout l'argent est investi avant la riviere, le resultat affiche
depend du tirage des cartes restantes. Les gains ajustes remplacent ce
resultat par l'esperance mathematique du coup: la part du pot qui revient
au joueur compte tenu de son equite au moment ou l'action s'est arretee.

La difference entre gains reels et gains ajustes mesure la chance sur la
periode; c'est la seconde courbe affichee sur le graphique.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional

from ..equity.equity import equity, equity_exact
from ..models import Action, ActionType, Hand, Street

#: nombre de simulations pour les all-in preflop (board inconnu)
MONTE_CARLO_ITERATIONS = 1500


def _last_decision_street(hand: Hand) -> Street:
    """Street de la derniere action volontaire de la main."""
    street = Street.PREFLOP
    for action in hand.actions:
        if action.type in (ActionType.FOLD, ActionType.CHECK, ActionType.CALL,
                           ActionType.BET, ActionType.RAISE):
            street = action.street
    return street


def is_allin_showdown(hand: Hand) -> bool:
    """La main s'est-elle terminee par un all-in avant la riviere ?"""
    if not any(a.allin for a in hand.actions):
        return False
    showdown = [s for s in hand.seats if len(s.cards) == 2 and s.showed]
    if len(showdown) < 2:
        return False
    street = _last_decision_street(hand)
    return len(hand.board_of(street)) < 5


def compute_ev(hand: Hand) -> Optional[Dict[str, float]]:
    """Gains ajustes de chaque joueur, ou None si la main ne s'y prete pas.

    Une main sans all-in (ou dont la riviere etait deja connue) garde son
    resultat reel: son gain ajuste est egal a son gain effectif.
    """
    if not is_allin_showdown(hand):
        return None
    contenders = [s for s in hand.seats if len(s.cards) == 2 and s.showed]
    if len(contenders) < 2:
        return None

    street = _last_decision_street(hand)
    board = hand.board_of(street)
    holdings = [list(s.cards) for s in contenders]
    missing = 5 - len(board)
    if missing <= 2:
        equities = equity_exact(holdings, board)
    else:
        equities = equity(holdings, board=board,
                          iterations=MONTE_CARLO_ITERATIONS, seed=hand.hand_id.__hash__() & 0xFFFF
                          ).equities

    collected = float(sum((a.amount for a in hand.actions if a.type is ActionType.COLLECT),
                          Decimal(0)))
    uncalled: Dict[str, float] = {}
    for a in hand.actions:
        if a.type is ActionType.UNCALLED:
            uncalled[a.player] = uncalled.get(a.player, 0.0) + float(a.amount)

    ev: Dict[str, float] = {}
    for seat in hand.seats:
        ev[seat.player] = float(seat.net)                 # par defaut: resultat reel
    for seat, eq in zip(contenders, equities):
        ev[seat.player] = (eq * collected + uncalled.get(seat.player, 0.0)
                           - float(seat.invested))
    return ev


def ev_rows(hand: Hand) -> Dict[str, Dict[str, float]]:
    """Compteurs d'EV a stocker pour chaque joueur de la main."""
    bb = float(hand.big_blind() or 1)
    adjusted = compute_ev(hand)
    rows: Dict[str, Dict[str, float]] = {}
    for seat in hand.seats:
        net = float(seat.net)
        value = net if adjusted is None else adjusted.get(seat.player, net)
        rows[seat.player] = {
            "ev_net": value,
            "ev_bb": value / bb if bb else 0.0,
            "allin_ev_hands": 1 if adjusted is not None else 0,
        }
    return rows
