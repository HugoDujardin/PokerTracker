"""Ranges preflop: notation texte, grille 13x13 et combinaisons.

La notation acceptee est celle utilisee par la plupart des outils:
    AA, KK+, AQs+, ATo-A8o, 76s, 22-99, AKs:0.5 (poids)
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

from .cards import RANKS, SUITS, hand_code

RANKS_DESC = RANKS[::-1]                     # "AKQJT98765432"
GRID: List[List[str]] = []
for i, r1 in enumerate(RANKS_DESC):
    row = []
    for j, r2 in enumerate(RANKS_DESC):
        if i == j:
            row.append(r1 + r2)
        elif i < j:
            row.append(r1 + r2 + "s")
        else:
            row.append(r2 + r1 + "o")
    GRID.append(row)

ALL_CODES = [c for row in GRID for c in row]


def combos(code: str) -> List[Tuple[str, str]]:
    """Les combinaisons de cartes correspondant a un code ('AKs' -> 4 combos)."""
    code = code.strip()
    if len(code) < 2:
        return []
    r1, r2 = code[0].upper(), code[1].upper()
    if r1 not in RANKS or r2 not in RANKS:
        return []
    kind = code[2].lower() if len(code) > 2 else ""
    out: List[Tuple[str, str]] = []
    if r1 == r2:
        for i in range(4):
            for j in range(i + 1, 4):
                out.append((r1 + SUITS[i], r2 + SUITS[j]))
        return out
    if kind == "s":
        return [(r1 + s, r2 + s) for s in SUITS]
    if kind == "o":
        return [(r1 + s1, r2 + s2) for s1 in SUITS for s2 in SUITS if s1 != s2]
    return combos(code + "s") + combos(code + "o")


def nb_combos(code: str) -> int:
    return len(combos(code))


#: Classement des 169 mains de depart, du meilleur au moins bon.
#: Ordre classique des outils d'equite (equite preflop contre une main
#: aleatoire, ajustee pour la jouabilite des connecteurs assortis). Il sert
#: a la notation "top X%" des ranges.
RANKED_CODES: List[str] = [
    "AA", "KK", "QQ", "JJ", "AKs", "AQs", "TT", "AKo", "AJs", "KQs", "99", "ATs", "AQo",
    "KJs", "88", "QJs", "KTs", "A9s", "AJo", "QTs", "KQo", "77", "JTs", "A8s", "K9s", "ATo",
    "A5s", "A7s", "KJo", "66", "T9s", "A4s", "Q9s", "J9s", "QJo", "A6s", "55", "A3s", "K8s",
    "KTo", "98s", "T8s", "K7s", "A2s", "87s", "QTo", "Q8s", "44", "A9o", "J8s", "76s", "JTo",
    "97s", "K6s", "K5s", "K4s", "K3s", "K2s", "T7s", "Q7s", "K9o", "33", "86s", "65s", "J7s",
    "54s", "Q6s", "75s", "22", "Q5s", "96s", "Q4s", "Q3s", "64s", "Q2s", "J6s", "53s", "85s",
    "T6s", "J5s", "K8o", "J4s", "J3s", "43s", "74s", "J2s", "95s", "T5s", "Q9o", "A8o", "63s",
    "T4s", "52s", "T3s", "84s", "T2s", "42s", "62s", "A7o", "94s", "32s", "93s", "K7o", "92s",
    "83s", "A5o", "73s", "82s", "A6o", "72s", "A4o", "A3o", "A2o", "K6o", "T9o", "98o", "K5o",
    "J9o", "K4o", "Q8o", "87o", "K3o", "76o", "K2o", "T8o", "J8o", "Q7o", "97o", "Q6o", "65o",
    "Q5o", "86o", "J7o", "54o", "Q4o", "75o", "Q3o", "T7o", "Q2o", "96o", "J6o", "64o", "J5o",
    "85o", "53o", "J4o", "T6o", "J3o", "43o", "74o", "J2o", "95o", "T5o", "63o", "T4o", "52o",
    "T3o", "84o", "42o", "T2o", "62o", "94o", "32o", "93o", "92o", "83o", "73o", "82o", "72o",
]


def _strength(code: str) -> int:
    """Force relative d'une main (169 = la meilleure)."""
    return len(RANKED_CODES) - RANKED_CODES.index(code) if code in RANKED_CODES else 0


TOTAL_COMBOS = sum(nb_combos(c) for c in ALL_CODES)   # 1326


def top_percent(pct: float) -> Dict[str, float]:
    """Range correspondant aux X% de mains les plus fortes."""
    target = TOTAL_COMBOS * max(0.0, min(100.0, pct)) / 100.0
    out: Dict[str, float] = {}
    used = 0.0
    for code in RANKED_CODES:
        n = nb_combos(code)
        if used + n <= target:
            out[code] = 1.0
            used += n
        elif used < target:
            out[code] = round((target - used) / n, 3)
            used = target
        else:
            break
    return out


_RANGE_TOKEN = re.compile(
    r"^(?P<c1>[2-9TJQKA]{2}[so]?)(?:(?P<plus>\+)|-(?P<c2>[2-9TJQKA]{2}[so]?))?(?::(?P<w>[\d.]+))?$",
    re.I)


def _norm(code: str) -> str:
    r1, r2 = code[0].upper(), code[1].upper()
    kind = code[2].lower() if len(code) > 2 else ""
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2 = r2, r1
    return r1 + r2 + kind


def _expand_plus(code: str) -> List[str]:
    code = _norm(code)
    r1, r2 = code[0], code[1]
    kind = code[2:] if len(code) > 2 else ""
    if r1 == r2:                       # 77+ -> 77,88,...,AA
        start = RANKS.index(r1)
        return [RANKS[i] * 2 for i in range(start, len(RANKS))]
    hi = RANKS.index(r1)
    lo = RANKS.index(r2)
    return [RANKS[hi] + RANKS[i] + kind for i in range(lo, hi)]


def _expand_span(c1: str, c2: str) -> List[str]:
    c1, c2 = _norm(c1), _norm(c2)
    if c1[0] == c1[1] and c2[0] == c2[1]:       # 22-99
        a, b = sorted([RANKS.index(c1[0]), RANKS.index(c2[0])])
        return [RANKS[i] * 2 for i in range(a, b + 1)]
    if c1[0] != c2[0]:
        return [c1, c2]
    kind = c1[2:] if len(c1) > 2 else ""
    a, b = sorted([RANKS.index(c1[1]), RANKS.index(c2[1])])
    return [c1[0] + RANKS[i] + kind for i in range(a, b + 1)]


def parse_range(text: str) -> Dict[str, float]:
    """Transforme une notation texte en {code: poids}."""
    out: Dict[str, float] = {}
    if not text:
        return out
    text = text.strip()
    pct = re.fullmatch(r"(?:top\s*)?([\d.]+)\s*%", text, re.I)
    if pct:
        return top_percent(float(pct.group(1)))
    for token in re.split(r"[,\s]+", text):
        token = token.strip()
        if not token:
            continue
        m = _RANGE_TOKEN.match(token)
        if not m:
            continue
        weight = float(m.group("w")) if m.group("w") else 1.0
        if m.group("plus"):
            codes = _expand_plus(m.group("c1"))
        elif m.group("c2"):
            codes = _expand_span(m.group("c1"), m.group("c2"))
        else:
            c = _norm(m.group("c1"))
            codes = [c] if len(c) > 2 or c[0] == c[1] else [c + "s", c + "o"]
        for c in codes:
            if c in ALL_CODES:
                out[c] = weight
    return out


def range_to_text(weights: Dict[str, float]) -> str:
    """Notation compacte d'une range (pour sauvegarde/affichage)."""
    parts = []
    for code in RANKED_CODES:
        w = weights.get(code, 0)
        if w:
            parts.append(code if w >= 1 else f"{code}:{w:g}")
    return ", ".join(parts)


def range_percent(weights: Dict[str, float]) -> float:
    total = sum(nb_combos(c) * w for c, w in weights.items())
    return 100.0 * total / TOTAL_COMBOS


def range_combos(weights: Dict[str, float], dead: Iterable[str] = ()) -> List[Tuple[str, str]]:
    """Toutes les combinaisons d'une range, sans les cartes deja visibles."""
    dead_set = {c[0].upper() + c[1].lower() for c in dead}
    out = []
    for code, w in weights.items():
        if w <= 0:
            continue
        for combo in combos(code):
            if combo[0] in dead_set or combo[1] in dead_set:
                continue
            out.append(combo)
    return out
