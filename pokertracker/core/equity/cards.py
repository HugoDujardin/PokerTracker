"""Representation des cartes."""
from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
SUIT_SYMBOLS = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}
SUIT_COLORS = {"c": "#3f9d4a", "d": "#3d7ddb", "h": "#d0483f", "s": "#e8e8ea"}

FULL_DECK = [r + s for r in RANKS for s in SUITS]


def rank_of(card: str) -> int:
    return RANKS.index(card[0].upper())


def suit_of(card: str) -> int:
    return SUITS.index(card[1].lower())


def card_index(card: str) -> int:
    """Index 0..51 d'une carte."""
    return rank_of(card) * 4 + suit_of(card)


def index_card(index: int) -> str:
    return RANKS[index // 4] + SUITS[index % 4]


def parse_cards(text: str) -> list[str]:
    """Accepte 'AhKd', 'Ah Kd', 'ah,kd' -> ['Ah', 'Kd']."""
    txt = text.replace(",", " ").replace("[", " ").replace("]", " ")
    if " " in txt.strip():
        parts = txt.split()
    else:
        parts = [txt[i:i + 2] for i in range(0, len(txt.strip()), 2)]
    out = []
    for p in parts:
        p = p.strip()
        if len(p) == 2 and p[0].upper() in RANKS and p[1].lower() in SUITS:
            out.append(p[0].upper() + p[1].lower())
    return out


def card_label(card: str) -> str:
    return card[0].upper() + SUIT_SYMBOLS.get(card[1].lower(), card[1])


def hand_code(cards: list[str] | tuple[str, ...]) -> str:
    """Notation abregee d'une main preflop: ['Ah','Kd'] -> 'AKo'."""
    if len(cards) != 2:
        return ""
    r1, r2 = rank_of(cards[0]), rank_of(cards[1])
    hi, lo = (cards[0], cards[1]) if r1 >= r2 else (cards[1], cards[0])
    if r1 == r2:
        return hi[0].upper() * 2
    suited = "s" if cards[0][1].lower() == cards[1][1].lower() else "o"
    return f"{hi[0].upper()}{lo[0].upper()}{suited}"
