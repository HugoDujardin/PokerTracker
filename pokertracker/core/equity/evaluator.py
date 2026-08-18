"""Evaluateur de mains de poker (5 a 7 cartes).

Le score retourne est un entier: plus il est grand, meilleure est la main.
Il encode la categorie (paire, brelan...) puis les departages.
"""
from __future__ import annotations

from itertools import combinations
from typing import Iterable, Sequence

from .cards import RANKS, rank_of, suit_of

HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)

CATEGORY_NAMES = {
    HIGH_CARD: "Hauteur",
    PAIR: "Paire",
    TWO_PAIR: "Double paire",
    TRIPS: "Brelan",
    STRAIGHT: "Quinte",
    FLUSH: "Couleur",
    FULL_HOUSE: "Full",
    QUADS: "Carre",
    STRAIGHT_FLUSH: "Quinte flush",
}

_STRAIGHTS: list[tuple[int, int]] = []
for high in range(12, 3, -1):                      # de A (12) a 5 (3)
    mask = 0
    for i in range(5):
        mask |= 1 << (high - i)
    _STRAIGHTS.append((mask, high))
_STRAIGHTS.append(((1 << 12) | 0b1111, 3))          # la roue A2345


def _straight_high(mask: int) -> int:
    for smask, high in _STRAIGHTS:
        if mask & smask == smask:
            return high
    return -1


def _score(category: int, tiebreak: Sequence[int]) -> int:
    score = category
    for t in list(tiebreak) + [0] * (5 - len(tiebreak)):
        score = score * 16 + t
    return score


def evaluate(cards: Sequence[str]) -> int:
    """Score de la meilleure main de 5 cartes parmi celles fournies."""
    ranks = [rank_of(c) for c in cards]
    suits = [suit_of(c) for c in cards]

    by_suit: list[list[int]] = [[], [], [], []]
    for r, s in zip(ranks, suits):
        by_suit[s].append(r)

    # couleur / quinte flush
    for suited in by_suit:
        if len(suited) >= 5:
            mask = 0
            for r in suited:
                mask |= 1 << r
            sf = _straight_high(mask)
            if sf >= 0:
                return _score(STRAIGHT_FLUSH, [sf])
            top = sorted(suited, reverse=True)[:5]
            return _score(FLUSH, top)

    counts: dict[int, int] = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    mask = 0
    for r in counts:
        mask |= 1 << r

    quads = sorted([r for r, c in counts.items() if c == 4], reverse=True)
    trips = sorted([r for r, c in counts.items() if c == 3], reverse=True)
    pairs = sorted([r for r, c in counts.items() if c == 2], reverse=True)
    singles = sorted([r for r, c in counts.items() if c == 1], reverse=True)

    if quads:
        kicker = max([r for r in counts if r != quads[0]])
        return _score(QUADS, [quads[0], kicker])
    if trips and (pairs or len(trips) > 1):
        pair = pairs[0] if pairs else trips[1]
        return _score(FULL_HOUSE, [trips[0], pair])

    st = _straight_high(mask)
    if st >= 0:
        return _score(STRAIGHT, [st])
    if trips:
        kickers = sorted([r for r in counts if r != trips[0]], reverse=True)[:2]
        return _score(TRIPS, [trips[0]] + kickers)
    if len(pairs) >= 2:
        kicker = max([r for r in counts if r not in pairs[:2]])
        return _score(TWO_PAIR, [pairs[0], pairs[1], kicker])
    if pairs:
        kickers = sorted([r for r in counts if r != pairs[0]], reverse=True)[:3]
        return _score(PAIR, [pairs[0]] + kickers)
    return _score(HIGH_CARD, sorted(ranks, reverse=True)[:5])


def category_of(score: int) -> int:
    return score >> 20


def describe(cards: Sequence[str]) -> str:
    """Libelle lisible de la meilleure main ('Brelan de Rois')."""
    score = evaluate(cards)
    cat = category_of(score)
    name = CATEGORY_NAMES[cat]
    top = (score >> 16) & 0xF
    if cat in (PAIR, TRIPS, QUADS, FULL_HOUSE, TWO_PAIR):
        return f"{name} de {RANKS[top]}"
    if cat in (STRAIGHT, STRAIGHT_FLUSH):
        return f"{name} hauteur {RANKS[top]}"
    return f"{name} {RANKS[top]}"


def best_five(cards: Sequence[str]) -> tuple[str, ...]:
    """Les 5 cartes qui composent la meilleure main."""
    best, combo = -1, tuple(cards[:5])
    for c in combinations(cards, 5):
        s = evaluate(c)
        if s > best:
            best, combo = s, c
    return combo


def compare(hands: Iterable[Sequence[str]]) -> list[int]:
    """Indices des mains gagnantes (plusieurs en cas d'egalite)."""
    scores = [evaluate(h) for h in hands]
    if not scores:
        return []
    best = max(scores)
    return [i for i, s in enumerate(scores) if s == best]
