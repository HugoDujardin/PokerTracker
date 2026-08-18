"""Tests du moteur de compteurs statistiques."""
import pytest

from pokertracker.core.parsers import registry
from pokertracker.core.stats import definitions as sd
from pokertracker.core.stats.counters import compute_hand_counters

HEADER = ("PokerStars Hand #{hid}:  Hold'em No Limit ($0.50/$1.00 USD) - 2024/05/01 20:00:00 ET\n"
          "Table 'Test' 6-max Seat #{btn} is the button\n"
          "Seat 1: P1 ($100 in chips)\n"
          "Seat 2: P2 ($100 in chips)\n"
          "Seat 3: P3 ($100 in chips)\n"
          "Seat 4: P4 ($100 in chips)\n"
          "Seat 5: P5 ($100 in chips)\n"
          "Seat 6: P6 ($100 in chips)\n")


def build(body: str, hid: str = "1", btn: int = 6) -> dict:
    text = HEADER.format(hid=hid, btn=btn) + body + "\n*** SUMMARY ***\nTotal pot $0 | Rake $0\n"
    hands = list(registry.parse_text(text))
    assert hands, "l'historique de test doit etre lisible"
    return compute_hand_counters(hands[0])


def test_3bet_et_fold_to_3bet():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: raises $2 to $3\n"
        "P4: raises $7 to $10\n"
        "P5: folds\n"
        "P6: folds\n"
        "P1: folds\n"
        "P2: folds\n"
        "P3: folds\n")
    assert rows["P3"]["rfi"] == 1 and rows["P3"]["rfi_opp"] == 1
    assert rows["P4"]["three_bet"] == 1 and rows["P4"]["three_bet_opp"] == 1
    assert rows["P3"]["fold_to_3bet"] == 1 and rows["P3"]["fold_to_3bet_opp"] == 1
    assert rows["P5"]["cold_4bet_opp"] == 1 and rows["P5"]["cold_4bet"] == 0
    assert rows["P4"]["vpip"] == 1 and rows["P4"]["pfr"] == 1


def test_squeeze_et_cold_call():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: raises $2 to $3\n"
        "P4: calls $3\n"
        "P5: raises $9 to $12\n"
        "P6: folds\n"
        "P1: folds\n"
        "P2: folds\n"
        "P3: folds\n"
        "P4: folds\n")
    assert rows["P4"]["cold_call"] == 1
    assert rows["P5"]["squeeze"] == 1 and rows["P5"]["squeeze_opp"] == 1
    assert rows["P5"]["three_bet"] == 1


def test_vol_de_blindes_et_defense():
    rows = build(
        "P4: posts small blind $0.50\n"
        "P5: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P6: folds\n"
        "P1: folds\n"
        "P2: folds\n"
        "P3: raises $2 to $3\n"
        "P4: folds\n"
        "P5: raises $8 to $11\n"
        "P3: folds\n",
        btn=3)
    assert rows["P3"]["steal"] == 1 and rows["P3"]["steal_opp"] == 1
    assert rows["P4"]["fold_to_steal"] == 1 and rows["P4"]["fold_to_steal_opp"] == 1
    assert rows["P5"]["resteal"] == 1 and rows["P5"]["fold_to_steal"] == 0


def test_limp_et_isolation():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: calls $1\n"
        "P4: raises $3 to $4\n"
        "P5: folds\n"
        "P6: folds\n"
        "P1: folds\n"
        "P2: folds\n"
        "P3: folds\n")
    assert rows["P3"]["limp"] == 1 and rows["P3"]["limp_fold"] == 1
    assert rows["P4"]["iso_raise"] == 1 and rows["P4"]["iso_opp"] == 1
    assert rows["P4"]["rfi"] == 0        # le pot n'etait plus non ouvert


def test_cbet_et_fold_to_cbet():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: raises $2 to $3\n"
        "P4: calls $3\n"
        "P5: folds\n"
        "P6: folds\n"
        "P1: folds\n"
        "P2: folds\n"
        "*** FLOP *** [2h 7d Jc]\n"
        "P3: bets $4\n"
        "P4: folds\n")
    assert rows["P3"]["cbet_f"] == 1 and rows["P3"]["cbet_opp_f"] == 1
    assert rows["P4"]["fold_to_cbet_f"] == 1 and rows["P4"]["fold_to_cbet_opp_f"] == 1
    assert rows["P3"]["saw_flop"] == 1 and rows["P3"]["wwsf_opp"] == 1


def test_checkraise_et_donk():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: raises $2 to $3\n"
        "P2: calls $2\n"
        "*** FLOP *** [2h 7d Jc]\n"
        "P2: bets $3\n"
        "P3: calls $3\n"
        "*** TURN *** [2h 7d Jc] [9s]\n"
        "P2: checks\n"
        "P3: bets $8\n"
        "P2: raises $16 to $24\n"
        "P3: folds\n")
    assert rows["P2"]["donk_f"] == 1 and rows["P2"]["donk_opp_f"] == 1
    assert rows["P2"]["checkraise_t"] == 1 and rows["P2"]["checkraise_opp_t"] == 1
    assert rows["P3"]["fold_to_bet_t"] == 1


def test_probe_et_delayed_cbet():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: raises $2 to $3\n"
        "P2: calls $2\n"
        "*** FLOP *** [2h 7d Jc]\n"
        "P2: checks\n"
        "P3: checks\n"
        "*** TURN *** [2h 7d Jc] [9s]\n"
        "P2: bets $4\n"
        "P3: folds\n")
    assert rows["P3"]["cbet_f"] == 0 and rows["P3"]["cbet_opp_f"] == 1
    assert rows["P2"]["probe_t"] == 1 and rows["P2"]["probe_opp_t"] == 1


def test_showdown_et_gains():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: raises $2 to $3\n"
        "P2: calls $2\n"
        "*** FLOP *** [2h 7d Jc]\n"
        "P2: checks\n"
        "P3: checks\n"
        "*** TURN *** [2h 7d Jc] [9s]\n"
        "P2: checks\n"
        "P3: checks\n"
        "*** RIVER *** [2h 7d Jc 9s] [4d]\n"
        "P2: checks\n"
        "P3: checks\n"
        "*** SHOW DOWN ***\n"
        "P2: shows [Ah Kh] (high card Ace)\n"
        "P3: shows [Qs Qd] (a pair of Queens)\n"
        "P3 collected $6 from pot\n")
    assert rows["P3"]["wtsd"] == 1 and rows["P3"]["wsd"] == 1 and rows["P3"]["wwsf"] == 1
    assert rows["P2"]["wtsd"] == 1 and rows["P2"]["wsd"] == 0
    assert rows["P3"]["amount_won"] == 6.0


def test_vpip_compte_une_seule_fois():
    rows = build(
        "P1: posts small blind $0.50\n"
        "P2: posts big blind $1\n"
        "*** HOLE CARDS ***\n"
        "P3: raises $2 to $3\n"
        "P4: raises $7 to $10\n"
        "P3: calls $7\n")
    assert rows["P3"]["vpip"] == 1 and rows["P3"]["pfr"] == 1
    assert rows["P3"]["call_3bet"] == 1


def test_calcul_des_statistiques_derivees():
    agg = {"vpip": 25, "vpip_opp": 100, "pfr": 18, "pfr_opp": 100,
           "three_bet": 6, "three_bet_opp": 60, "hands": 100, "bb_net": 5.5,
           "bet_f": 10, "raise_f": 2, "call_f": 6, "call_t": 2, "call_r": 2,
           "bet_t": 0, "raise_t": 0, "bet_r": 0, "raise_r": 0}
    assert sd.get("vpip").format(agg) == "25"
    assert sd.get("pfr").format(agg) == "18"
    assert sd.get("3bet").format(agg) == "10"
    assert sd.get("af").format(agg) == "1.20"
    assert sd.get("bb100").format(agg) == "+5.5"
    assert sd.get("wtsd").format(agg) == "-"          # aucune observation
    assert sd.get("wtsd").sample(agg) == 0
