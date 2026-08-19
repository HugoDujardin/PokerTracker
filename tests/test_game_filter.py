"""Filtre par variante: ne jamais melanger Hold'em et Omaha."""
import pytest

from conftest import load
from pokertracker.core.db import Filter
from pokertracker.core.models import GameType, detect_game
from pokertracker.hud.manager import HudManager
from pokertracker.hud.profile import default_profile


@pytest.mark.parametrize("libelle,attendu", [
    ("Hold'em No Limit", GameType.NLHE),
    ("NL Texas Hold'em", GameType.NLHE),
    ("Fixed Limit Hold'em", GameType.LHE),
    ("Omaha Pot Limit", GameType.PLO),
    ("5 Card Omaha Pot Limit", GameType.PLO5),
    ("Omaha Hi/Lo Pot Limit", GameType.PLO8),
    ("Triple Draw", GameType.OTHER),
])
def test_detection_des_variantes(libelle, attendu):
    assert detect_game(libelle) is attendu


def test_parser_omaha():
    hand = load("pokerstars_plo")[0]
    assert hand.game is GameType.PLO and hand.game.is_omaha
    assert len(hand.seat_of("Hero").cards) == 4        # quatre cartes privatives


def _base_mixte(db):
    db.insert_hands(load("pokerstars_cash"))
    db.insert_hands(load("pokerstars_plo"))
    return db.player_id("Hero", "PokerStars")


def test_agregation_par_variante(db):
    hero = _base_mixte(db)
    assert db.aggregate([hero])["hands"] == 3                       # toutes variantes
    assert db.aggregate([hero], Filter(games=["nlhe"]))["hands"] == 2
    assert db.aggregate([hero], Filter(games=["plo"]))["hands"] == 1
    assert db.aggregate([hero], Filter(games=["plo5"]))["hands"] == 0


def test_le_filtre_de_variante_reste_sur_le_chemin_rapide(db):
    _base_mixte(db)
    assert Filter(games=["nlhe"]).uses_totals()
    assert not Filter(games=["nlhe"]).is_empty()
    rapide = db.aggregate_many(["Hero"], room="PokerStars", flt=Filter(games=["nlhe"]))
    assert rapide["Hero"]["hands"] == 2
    lignes = list(db.conn.execute(
        "SELECT game, hands FROM player_totals t JOIN players p ON p.id = t.player_id "
        "WHERE p.name = 'Hero' ORDER BY game"))
    assert [(r["game"], r["hands"]) for r in lignes] == [("nlhe", 2), ("plo", 1)]


def test_reconstruction_des_cumuls_par_variante(db):
    hero = _base_mixte(db)
    db.rebuild_totals()
    assert db.aggregate([hero], Filter(games=["nlhe"]))["hands"] == 2
    assert db.aggregate([hero], Filter(games=["plo"]))["hands"] == 1
    db.rebuild_counters()
    assert db.aggregate([hero], Filter(games=["plo"]))["hands"] == 1


def test_rapport_groupe_par_variante(db):
    hero = _base_mixte(db)
    groupes = db.aggregate([hero], group_by="h.game")
    assert {k: v["hands"] for k, v in groupes.items()} == {"nlhe": 2, "plo": 1}


def test_hud_n_affiche_que_la_variante_de_la_table(db):
    _base_mixte(db)
    manager = HudManager(db, default_profile())
    manager.on_new_hands(load("pokerstars_plo"))
    etat = list(manager.tables.values())[0]
    assert etat.game == "plo"
    assert manager.stats_for("Hero", "PokerStars", game=etat.game)["hands"] == 1
    manager.on_new_hands(load("pokerstars_cash"))
    etat_nlhe = manager.tables[manager.table_key("PokerStars", "Aludra II")]
    assert manager.stats_for("Hero", "PokerStars", game=etat_nlhe.game)["hands"] == 2


def test_hud_sans_separation_si_desactivee(db):
    _base_mixte(db)
    manager = HudManager(db, default_profile(), filter_by_game=False)
    assert manager.stats_for("Hero", "PokerStars", game="plo")["hands"] == 3


def test_popup_du_hud_filtre_aussi(db):
    _base_mixte(db)
    manager = HudManager(db, default_profile())
    sections = dict(manager.popup_data("Hero", "PokerStars", "plo"))
    mains = [v for label, v, _n in sections["Global"] if label == "Mains"]
    assert mains == ["1"]


def test_coach_precise_la_variante(db):
    from pokertracker.ai.analyses import stats_analysis
    hero = _base_mixte(db)
    analyse = stats_analysis(db, hero, "Hero", game="nlhe")
    assert "Hold'em No Limit" in analyse.context.splitlines()[0]
    assert "2 mains" in analyse.context.splitlines()[0]
