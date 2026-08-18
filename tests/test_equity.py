"""Tests de l'evaluateur, des ranges et du calcul d'equite."""
import pytest

from pokertracker.core.equity.cards import hand_code, parse_cards
from pokertracker.core.equity.equity import equity, pot_odds
from pokertracker.core.equity.evaluator import (FLUSH, FULL_HOUSE, PAIR, QUADS, STRAIGHT,
                                                STRAIGHT_FLUSH, TRIPS, TWO_PAIR, category_of,
                                                compare, evaluate)
from pokertracker.core.equity.ranges import (parse_range, range_combos, range_percent,
                                             range_to_text, top_percent)


@pytest.mark.parametrize("cards,categorie", [
    (["As", "Ks", "Qs", "Js", "Ts", "2c", "3d"], STRAIGHT_FLUSH),
    (["Ah", "Ad", "Ac", "As", "Kd", "2c", "3d"], QUADS),
    (["Ah", "Ad", "Ac", "Kd", "Ks", "2c", "3d"], FULL_HOUSE),
    (["Ah", "2h", "5h", "9h", "Jh", "2c", "3d"], FLUSH),
    (["5h", "4d", "3c", "2s", "Ah", "9d", "Ks"], STRAIGHT),
    (["9h", "9d", "9c", "2s", "Ah", "5d", "Ks"], TRIPS),
    (["9h", "9d", "2c", "2s", "Ah", "5d", "Ks"], TWO_PAIR),
    (["9h", "9d", "7c", "2s", "Ah", "5d", "Ks"], PAIR),
])
def test_categories(cards, categorie):
    assert category_of(evaluate(cards)) == categorie


def test_departages():
    board = ["2c", "3d", "4h", "7s", "9s"]
    assert compare([["Ah", "Ad"] + board, ["Kh", "Kd"] + board]) == [0]
    assert compare([["Ah", "Kd"] + board, ["As", "Kc"] + board]) == [0, 1]
    # la quinte au 6 bat la roue
    assert compare([["5h", "6d", "2c", "3d", "4h"], ["Ah", "5s", "2c", "3d", "4h"]]) == [0]


@pytest.mark.parametrize("mains,board,attendu,marge", [
    ([["Ah", "Ad"], ["Ks", "Kd"]], [], 82.0, 3.0),
    ([["Ah", "Kh"], ["Qs", "Qd"]], [], 46.0, 3.0),
    ([["Jh", "Th"], ["As", "Ad"]], [], 22.0, 3.0),
    ([["Ah", "Kd"], ["7c", "7d"]], ["Ks", "7h", "2c"], 4.0, 4.0),
])
def test_equites_connues(mains, board, attendu, marge):
    resultat = equity(mains, board=board, iterations=6000, seed=11)
    assert abs(resultat.as_percent()[0] - attendu) < marge


def test_equite_contre_une_range():
    resultat = equity([["Ah", "Kd"], "QQ+, AKs"], iterations=4000, seed=3)
    assert 25 < resultat.as_percent()[0] < 45
    assert abs(sum(resultat.as_percent()) - 100) < 0.001


def test_notation_des_ranges():
    r = parse_range("77+, AQs+, AKo, A2s-A5s")
    assert "AA" in r and "77" in r and "AQs" in r and "AKo" in r and "A3s" in r
    assert "66" not in r and "AQo" not in r
    assert len(range_combos(r)) == 6 * 8 + 4 * 2 + 12 + 4 * 4
    assert round(range_percent(parse_range("AA")), 2) == round(100 * 6 / 1326, 2)


def test_range_en_pourcentage():
    r = top_percent(10)
    assert abs(range_percent(r) - 10) < 0.5
    assert "AA" in r and "72o" not in r
    assert range_to_text(r).startswith("AA, KK, QQ")


def test_cartes_mortes_exclues():
    combos = range_combos(parse_range("AA"), dead=["Ah"])
    assert len(combos) == 3
    assert all("Ah" not in c for c in combos)


def test_utilitaires_cartes():
    assert parse_cards("AhKd") == ["Ah", "Kd"]
    assert parse_cards("ah kd") == ["Ah", "Kd"]
    assert hand_code(["Ah", "Kh"]) == "AKs"
    assert hand_code(["Ah", "Kd"]) == "AKo"
    assert hand_code(["7h", "7d"]) == "77"
    assert round(pot_odds(50, 100), 1) == 33.3
