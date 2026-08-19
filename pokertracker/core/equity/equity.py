"""Calcul d'equite par simulation de Monte-Carlo.

Utilise par le replayer (equite a chaque street) et par l'analyse de ranges.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .cards import FULL_DECK
from .evaluator import evaluate
from .ranges import parse_range, range_combos


@dataclass
class EquityResult:
    equities: List[float]          # equite de chaque joueur (0..1)
    wins: List[float]
    ties: List[float]
    iterations: int

    def as_percent(self) -> List[float]:
        return [100.0 * e for e in self.equities]


def _draw_holdings(players: Sequence[object], dead: set, rng: random.Random) -> Optional[List[List[str]]]:
    """Tire une main pour chaque joueur (main fixe ou piochee dans sa range)."""
    used = set(dead)
    out: List[List[str]] = []
    for p in players:
        if isinstance(p, (list, tuple)) and p and isinstance(p[0], str) and len(p) == 2 \
                and all(len(c) == 2 for c in p):
            combo = list(p)
            if any(c in used for c in combo):
                return None
        else:
            choices = p  # liste de combos possibles
            combo = None
            for _ in range(24):
                cand = rng.choice(choices)
                if cand[0] not in used and cand[1] not in used:
                    combo = list(cand)
                    break
            if combo is None:
                return None
        used.update(combo)
        out.append(combo)
    return out


def equity(hands: Sequence[Sequence[str] | str], board: Sequence[str] = (),
           iterations: int = 5000, seed: Optional[int] = None) -> EquityResult:
    """Equite de chaque joueur.

    `hands` accepte une main precise (['Ah','Kd']) ou une range en notation
    texte ('QQ+, AKs') pour un adversaire inconnu.
    """
    rng = random.Random(seed)
    board = [c for c in board]
    dead = set(board)
    players: List[object] = []
    for h in hands:
        if isinstance(h, str):
            weights = parse_range(h)
            combos = range_combos(weights, dead=board)
            if not combos:
                combos = [(c1, c2) for c1 in FULL_DECK for c2 in FULL_DECK if c1 < c2][:100]
            players.append(combos)
        else:
            cards = [c[0].upper() + c[1].lower() for c in h]
            players.append(cards)
            dead.update(cards)

    n = len(players)
    wins = [0.0] * n
    ties = [0.0] * n
    done = 0
    need = 5 - len(board)

    for _ in range(max(1, iterations)):
        holdings = _draw_holdings(players, set(board), rng)
        if holdings is None:
            continue
        used = set(board)
        for h in holdings:
            used.update(h)
        deck = [c for c in FULL_DECK if c not in used]
        runout = rng.sample(deck, need) if need > 0 else []
        full_board = board + runout
        scores = [evaluate(list(h) + full_board) for h in holdings]
        best = max(scores)
        winners = [i for i, s in enumerate(scores) if s == best]
        if len(winners) == 1:
            wins[winners[0]] += 1
        else:
            for i in winners:
                ties[i] += 1.0 / len(winners)
        done += 1

    if done == 0:
        return EquityResult([0.0] * n, wins, ties, 0)
    eq = [(wins[i] + ties[i]) / done for i in range(n)]
    return EquityResult(eq, [w / done for w in wins], [t / done for t in ties], done)


def equity_exact(hands: Sequence[Sequence[str]], board: Sequence[str]) -> List[float]:
    """Equite exacte par enumeration de toutes les cartes restantes.

    Utilisable quand il manque au plus deux cartes au board (all-in au flop
    ou au turn): 990 ou 44 tirages, c'est instantane et sans aleatoire.
    """
    from itertools import combinations

    board = list(board)
    used = set(board)
    for h in hands:
        used.update(h)
    deck = [c for c in FULL_DECK if c not in used]
    need = 5 - len(board)
    if need <= 0:
        runouts: List[Sequence[str]] = [()]
    else:
        runouts = list(combinations(deck, need))
    wins = [0.0] * len(hands)
    for runout in runouts:
        full = board + list(runout)
        scores = [evaluate(list(h) + full) for h in hands]
        best = max(scores)
        winners = [i for i, sc in enumerate(scores) if sc == best]
        for i in winners:
            wins[i] += 1.0 / len(winners)
    total = len(runouts) or 1
    return [w / total for w in wins]


def equity_vs_random(hand: Sequence[str], iterations: int = 2000,
                     opponents: int = 1, seed: Optional[int] = None) -> float:
    return equity([list(hand)] + ["100%"] * opponents, iterations=iterations, seed=seed).equities[0]


def pot_odds(to_call: float, pot: float) -> float:
    """Equite minimale necessaire pour payer (en %)."""
    total = pot + to_call
    return 100.0 * to_call / total if total else 0.0
