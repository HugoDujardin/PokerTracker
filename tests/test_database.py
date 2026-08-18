"""Tests de la base de donnees et des agregations."""
from datetime import datetime

from conftest import load
from pokertracker.core.db import Filter, stake_label
from pokertracker.core.stats import definitions as sd


def test_insertion_et_doublons(db):
    hands = load("pokerstars_cash")
    assert db.insert_hands(hands) == 2
    assert db.insert_hands(hands) == 0            # la meme main n'est jamais reimportee
    assert db.counts()["hands"] == 2
    assert db.counts()["players"] == 6


def test_agregation_par_joueur(db):
    db.insert_hands(load("pokerstars_cash"))
    pid = db.player_id("Hero", "PokerStars")
    agg = db.aggregate([pid])
    assert agg["hands"] == 2
    assert agg["vpip"] == 2 and agg["pfr"] == 2
    assert sd.get("vpip").format(agg) == "100"
    assert round(agg["amount_net"], 2) == 36.25


def test_filtres(db):
    db.insert_hands(load("pokerstars_cash"))
    db.insert_hands(load("winamax_cash"))
    hero_ps = db.player_id("Hero", "PokerStars")
    assert db.aggregate([hero_ps], Filter(rooms=["Winamax"]))["hands"] == 0
    assert db.aggregate([hero_ps], Filter(rooms=["PokerStars"]))["hands"] == 2
    assert db.aggregate([hero_ps], Filter(positions=["UTG"]))["hands"] == 1
    assert db.aggregate([hero_ps], Filter(date_from=datetime(2030, 1, 1)))["hands"] == 0
    assert db.aggregate([hero_ps], Filter(min_players=7))["hands"] == 0


def test_agregation_groupee(db):
    db.insert_hands(load("pokerstars_cash"))
    pid = db.player_id("Hero", "PokerStars")
    groups = db.aggregate([pid], group_by="hp.position")
    assert {k: v["hands"] for k, v in groups.items()} == {"MP": 1, "UTG": 1}


def test_stats_multi_joueurs_pour_le_hud(db):
    db.insert_hands(load("pokerstars_cash"))
    aggs = db.aggregate_many(["Hero", "Villain2", "Inconnu"], room="PokerStars")
    assert set(aggs) == {"Hero", "Villain2"}
    assert aggs["Villain2"]["hands"] == 2


def test_courbe_de_gains(db):
    db.insert_hands(load("pokerstars_cash"))
    pid = db.player_id("Hero", "PokerStars")
    curve = db.bankroll_curve(pid)
    assert len(curve) == 2
    assert round(curve[-1][2], 2) == 36.25          # cumul en argent
    assert round(curve[-1][3], 1) == 72.5           # cumul en bb


def test_notes_et_profils(db):
    db.insert_hands(load("pokerstars_cash"))
    pid = db.player_id("Villain2", "PokerStars")
    db.set_note(pid, "paye trop large", "#7a2c2c", "fish")
    row = db.get_player("Villain2", "PokerStars")
    assert row["note"] == "paye trop large" and row["label"] == "fish"
    db.save_profile("Mon profil", '{"name": "Mon profil"}')
    assert "Mon profil" in db.load_profiles()


def test_libelle_de_limite():
    hand = load("pokerstars_cash")[0]
    assert stake_label(hand) == "0.25/0.5"
    mtt = load("pokerstars_mtt")[0]
    assert stake_label(mtt).startswith("MTT")


def test_valeurs_distinctes(db):
    db.insert_hands(load("pokerstars_cash"))
    db.insert_hands(load("ggpoker_cash"))
    assert set(db.distinct("room")) == {"PokerStars", "GGPoker"}
    assert "0.25/0.5" in db.distinct("stake")


def test_cumuls_incrementaux_coherents(db):
    """Les cumuls precalcules (utilises par le HUD) doivent egaler le recalcul."""
    db.insert_hands(load("pokerstars_cash"))
    db.insert_hands(load("ggpoker_cash"))
    rapide = db.aggregate_many(["Hero"], room="PokerStars")["Hero"]
    db.rebuild_totals()
    recalcule = db.aggregate_many(["Hero"], room="PokerStars")["Hero"]
    assert rapide == recalcule
    pid = db.player_id("Hero", "PokerStars")
    lent = db.aggregate([pid], Filter(rooms=["PokerStars"]))
    assert lent["hands"] == rapide["hands"] == 2
    assert lent["vpip"] == rapide["vpip"]


def test_cumuls_ignores_si_filtre(db):
    db.insert_hands(load("pokerstars_cash"))
    pid = db.player_id("Hero", "PokerStars")
    assert Filter().is_empty()
    assert not Filter(positions=["BTN"]).is_empty()
    assert db.aggregate([pid], Filter(positions=["UTG"]))["hands"] == 1
    assert db.aggregate([pid])["hands"] == 2
