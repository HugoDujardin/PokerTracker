"""Genere un historique de mains de demonstration au format PokerStars.

Pratique pour essayer le logiciel (ou tester ses performances) sans avoir a
jouer: chaque joueur simule est pilote par un style different, de facon a
produire des statistiques contrastees dans le HUD.

    python tools/generate_demo_hands.py --hands 2000 --out demo/HandHistory.txt
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = [r + s for r in RANKS for s in SUITS]

#: (vpip, pfr, agressivite postflop)
STYLES = {
    "Nitrogen": (0.14, 0.12, 0.30),
    "RegulierFR": (0.24, 0.20, 0.55),
    "CallingSta": (0.48, 0.08, 0.20),
    "Maniac_88": (0.62, 0.44, 0.75),
    "TAG_Pro": (0.22, 0.19, 0.62),
    "Hero": (0.26, 0.21, 0.58),
}


def money(x: float) -> str:
    return f"${x:.2f}"


def generate(nb_hands: int, seed: int = 7) -> str:
    rng = random.Random(seed)
    names = list(STYLES)
    stacks = {n: 100.0 for n in names}
    # les mains se terminent a l'instant present: on tire d'abord les
    # intervalles pour connaitre la duree totale de la session simulee
    gaps = [rng.randint(45, 110) for _ in range(nb_hands)]
    when = datetime.now() - timedelta(seconds=sum(gaps))
    sb, bb = 0.25, 0.50
    out: list[str] = []

    for index in range(nb_hands):
        hand_id = 900000000000 + index
        button = index % 6 + 1
        when += timedelta(seconds=gaps[index])
        deck = DECK[:]
        rng.shuffle(deck)
        holes = {n: (deck.pop(), deck.pop()) for n in names}
        board = [deck.pop() for _ in range(5)]
        seats = {i + 1: n for i, n in enumerate(names)}
        order = [seats[(button + i) % 6 + 1] for i in range(6)]     # SB, BB, UTG...
        small, big = order[0], order[1]
        for n in names:
            stacks[n] = max(20.0, min(400.0, stacks[n]))

        lines = [
            f"PokerStars Hand #{hand_id}:  Hold'em No Limit ({money(sb)}/{money(bb)} USD) - "
            f"{when:%Y/%m/%d %H:%M:%S} ET",
            f"Table 'Demo Table' 6-max Seat #{button} is the button",
        ]
        for seat, name in seats.items():
            lines.append(f"Seat {seat}: {name} ({money(stacks[name])} in chips)")
        lines.append(f"{small}: posts small blind {money(sb)}")
        lines.append(f"{big}: posts big blind {money(bb)}")
        lines.append("*** HOLE CARDS ***")
        lines.append(f"Hero: dealt cards")
        lines[-1] = f"Dealt to Hero [{holes['Hero'][0]} {holes['Hero'][1]}]"

        invested = {small: sb, big: bb}
        in_hand: list[str] = []
        raises = 0
        current = bb
        for name in order[2:] + [small, big]:
            vpip, pfr, _ = STYLES[name]
            roll = rng.random()
            if raises >= 2:
                vpip *= 0.35
            if roll > vpip:
                if name == big and raises == 0:
                    in_hand.append(name)
                    continue
                lines.append(f"{name}: folds")
                continue
            if rng.random() < pfr / max(vpip, 0.01) and raises < 3:
                target = round(current * (2.6 if raises == 0 else 2.9), 2)
                paid = round(target - invested.get(name, 0.0), 2)
                lines.append(f"{name}: raises {money(paid)} to {money(target)}")
                invested[name] = target
                current = target
                raises += 1
            else:
                paid = round(current - invested.get(name, 0.0), 2)
                if paid <= 0:
                    lines.append(f"{name}: checks")
                else:
                    lines.append(f"{name}: calls {money(paid)}")
                    invested[name] = current
            in_hand.append(name)

        # second tour preflop: le premier relanceur repond au 3bet
        raisers = [l.split(":")[0] for l in lines if ": raises" in l]
        if len(raisers) >= 2 and raisers[0] in in_hand:
            name = raisers[0]
            besoin = round(current - invested.get(name, 0.0), 2)
            roll = rng.random()
            vpip, pfr, _ = STYLES[name]
            if roll < 0.5 - vpip / 2:
                lines.append(f"{name}: folds")
                in_hand = [p for p in in_hand if p != name]
            elif roll < 0.92:
                lines.append(f"{name}: calls {money(besoin)}")
                invested[name] = current
            else:
                cible = round(current * 2.4, 2)
                lines.append(f"{name}: raises {money(cible - invested.get(name, 0.0))} "
                             f"to {money(cible)}")
                invested[name] = cible
                current = cible

        pot = round(sum(invested.values()), 2)
        aggressor = None
        for line in reversed(lines):
            if ": raises" in line:
                aggressor = line.split(":")[0]
                break

        streets = [("FLOP", board[:3], 3), ("TURN", board[:4], 4), ("RIVER", board[:5], 5)]
        for label, cards, size in streets:
            if len(in_hand) < 2:
                break
            if label == "FLOP":
                lines.append(f"*** FLOP *** [{' '.join(cards)}]")
            elif label == "TURN":
                lines.append(f"*** TURN *** [{' '.join(cards[:3])}] [{cards[3]}]")
            else:
                lines.append(f"*** RIVER *** [{' '.join(cards[:4])}] [{cards[4]}]")
            bet_size = round(pot * rng.choice([0.33, 0.5, 0.66, 0.75]), 2)
            bettor = aggressor if aggressor in in_hand else in_hand[0]
            actors = [p for p in in_hand]
            if rng.random() < STYLES[bettor][2]:
                lines.append(f"{bettor}: bets {money(bet_size)}")
                pot = round(pot + bet_size, 2)
                stacks[bettor] -= bet_size
                for name in actors:
                    if name == bettor:
                        continue
                    _, _, aggro = STYLES[name]
                    roll = rng.random()
                    if roll < 0.45 - aggro * 0.2:
                        lines.append(f"{name}: folds")
                        in_hand = [p for p in in_hand if p != name]
                    elif roll < 0.93:
                        lines.append(f"{name}: calls {money(bet_size)}")
                        pot = round(pot + bet_size, 2)
                        stacks[name] -= bet_size
                    else:
                        raise_to = round(bet_size * 3, 2)
                        lines.append(f"{name}: raises {money(raise_to - bet_size)} to {money(raise_to)}")
                        pot = round(pot + raise_to, 2)
                        stacks[name] -= raise_to
                        aggressor = name
            else:
                for name in actors:
                    lines.append(f"{name}: checks")

        if len(in_hand) >= 2:
            lines.append("*** SHOW DOWN ***")
            for name in in_hand:
                lines.append(f"{name}: shows [{holes[name][0]} {holes[name][1]}] (main)")
        winner = rng.choice(in_hand) if in_hand else big
        rake = round(min(pot * 0.05, 1.5), 2)
        collected = round(pot - rake, 2)
        lines.append(f"{winner} collected {money(collected)} from pot")
        stacks[winner] += collected
        lines.append("*** SUMMARY ***")
        lines.append(f"Total pot {money(pot)} | Rake {money(rake)}")
        lines.append(f"Board [{' '.join(board)}]")
        out.append("\n".join(lines))

    return "\n\n".join(out) + "\n\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hands", type=int, default=1000, help="nombre de mains a generer")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="demo/HandHistory_demo.txt")
    args = parser.parse_args()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate(args.hands, args.seed), encoding="utf-8")
    print(f"{args.hands} mains ecrites dans {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
