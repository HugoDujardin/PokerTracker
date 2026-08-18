"""Placement des panneaux HUD sur la fenetre de table.

Les positions sont exprimees en coordonnees relatives (0..1) de la fenetre
de table, ce qui rend le HUD independant de la taille de la fenetre et du
facteur d'echelle de Windows 11.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

Point = Tuple[float, float]

#: dispositions par defaut, siege du heros en bas au centre
LAYOUTS: Dict[int, List[Point]] = {
    2: [(0.42, 0.72), (0.42, 0.16)],
    3: [(0.42, 0.72), (0.10, 0.30), (0.74, 0.30)],
    4: [(0.42, 0.72), (0.07, 0.44), (0.42, 0.14), (0.77, 0.44)],
    5: [(0.42, 0.74), (0.06, 0.50), (0.20, 0.16), (0.66, 0.16), (0.80, 0.50)],
    6: [(0.42, 0.74), (0.06, 0.54), (0.06, 0.22), (0.42, 0.12), (0.78, 0.22), (0.78, 0.54)],
    7: [(0.42, 0.76), (0.08, 0.58), (0.05, 0.28), (0.30, 0.11), (0.60, 0.11), (0.80, 0.28),
        (0.80, 0.58)],
    8: [(0.42, 0.78), (0.14, 0.68), (0.04, 0.42), (0.12, 0.16), (0.42, 0.09), (0.72, 0.16),
        (0.80, 0.42), (0.72, 0.68)],
    9: [(0.42, 0.78), (0.12, 0.70), (0.03, 0.48), (0.06, 0.24), (0.30, 0.09), (0.58, 0.09),
        (0.80, 0.24), (0.84, 0.48), (0.74, 0.70)],
    10: [(0.42, 0.80), (0.16, 0.74), (0.04, 0.54), (0.03, 0.30), (0.22, 0.10), (0.52, 0.08),
         (0.78, 0.14), (0.86, 0.36), (0.84, 0.60), (0.66, 0.76)],
}


def layout_for(nb_seats: int) -> List[Point]:
    if nb_seats in LAYOUTS:
        return LAYOUTS[nb_seats]
    return LAYOUTS[max(k for k in LAYOUTS if k <= max(2, nb_seats))]


def seat_positions(seat_numbers: Sequence[int], hero_seat: int, max_seats: int,
                   overrides: Sequence[Point] = ()) -> Dict[int, Point]:
    """Associe chaque numero de siege a une position relative.

    Le siege du heros est place en bas: les autres joueurs se repartissent
    dans le sens des aiguilles d'une montre, comme sur la table reelle.
    """
    seats = sorted(set(seat_numbers))
    if not seats:
        return {}
    n = max(max_seats, len(seats))
    points = list(overrides) if overrides else layout_for(n)
    if len(points) < n:
        points = layout_for(len(points)) if len(points) >= 2 else layout_for(n)
    base = hero_seat if hero_seat in seats else seats[0]
    # index visuel = decalage du siege par rapport a celui du heros
    all_seats = list(range(1, n + 1))
    if base not in all_seats:
        all_seats = seats
    start = all_seats.index(base)
    mapping: Dict[int, Point] = {}
    for offset, seat in enumerate(all_seats[start:] + all_seats[:start]):
        if seat in seats:
            mapping[seat] = points[offset % len(points)]
    return mapping


def to_screen(rect: Tuple[int, int, int, int], point: Point,
              panel_size: Tuple[int, int] = (0, 0), scale: float = 1.0) -> Tuple[int, int]:
    """Convertit une position relative en coordonnees ecran."""
    x, y, w, h = rect
    px = x + int(point[0] * w * scale) if scale != 1.0 else x + int(point[0] * w)
    py = y + int(point[1] * h)
    pw, ph = panel_size
    px = max(x - pw // 2, min(px, x + w - pw // 3))
    py = max(y - ph // 2, min(py, y + h - ph // 3))
    return px, py
