"""Argent reel / argent fictif: detection et exclusion par defaut."""
from conftest import DATA, load
from pokertracker.core.db import Filter
from pokertracker.core.parsers import registry
from pokertracker.core.parsers.summaries import parse_summaries


def _texte(nom: str) -> str:
    return (DATA / f"{nom}.txt").read_text(encoding="utf-8")


def test_detection_pokerstars():
    assert load("pokerstars_cash")[0].real_money
    fictif = _texte("pokerstars_cash").replace("Hold'em No Limit ($0.25/$0.50 USD)",
                                               "Hold'em No Limit (50/100)")
    assert not list(registry.parse_text(fictif))[0].real_money


def test_detection_tournoi_fictif():
    assert load("pokerstars_mtt")[0].real_money
    fictif = _texte("pokerstars_mtt").replace("$10+$1 USD", "5000+500 play money")
    assert not list(registry.parse_text(fictif))[0].real_money


def test_detection_winamax_et_partypoker():
    assert load("winamax_cash")[0].real_money
    wina = _texte("winamax_cash").replace("(real money)", "(play money)")
    assert not list(registry.parse_text(wina))[0].real_money
    assert load("partypoker_cash")[0].real_money
    party = _texte("partypoker_cash").replace("(Real Money)", "(Play Money)")
    assert not list(registry.parse_text(party))[0].real_money


def _base_mixte(db):
    db.insert_hands(load("pokerstars_cash"))
    fictif = (_texte("pokerstars_cash")
              .replace("Hold'em No Limit ($0.25/$0.50 USD)", "Hold'em No Limit (50/100)")
              .replace("241234567890", "941234567890")
              .replace("241234567891", "941234567891"))
    db.insert_hands(registry.parse_text(fictif))
    return db.player_id("Hero", "PokerStars")


def test_exclusion_par_defaut(db):
    hero = _base_mixte(db)
    assert db.counts()["hands"] == 4
    assert db.aggregate([hero])["hands"] == 2                          # argent reel seul
    assert db.aggregate([hero], Filter(money="play"))["hands"] == 2
    assert db.aggregate([hero], Filter(money="all"))["hands"] == 4


def test_cumuls_precalcules_sans_argent_fictif(db):
    _base_mixte(db)
    assert db.aggregate_many(["Hero"], room="PokerStars")["Hero"]["hands"] == 2
    db.rebuild_totals()
    assert db.aggregate_many(["Hero"], room="PokerStars")["Hero"]["hands"] == 2
    db.rebuild_counters()
    assert db.aggregate_many(["Hero"], room="PokerStars")["Hero"]["hands"] == 2


def test_courbes_et_rapports(db):
    hero = _base_mixte(db)
    assert len(db.bankroll_curve(hero)) == 2
    assert len(db.bankroll_curve(hero, Filter(money="all"))) == 4
    groupes = db.aggregate([hero], group_by="hp.position")
    assert sum(v["hands"] for v in groupes.values()) == 2


def test_tournois_fictifs_exclus(db):
    resultats = parse_summaries(_texte("ps_summary"))
    texte_fictif = (_texte("ps_summary")
                    .replace("Buy-In: $9.10/$0.90 USD", "Buy-In: 5000/500 play money")
                    .replace("Buy-In: $4.55/$4.55/$0.90 USD", "Buy-In: 2500/2500/500 play money")
                    .replace("#300000000", "#900000000"))
    fictif = parse_summaries(texte_fictif)
    db.insert_tournaments(resultats + fictif)
    assert db.tournament_stats()["entries"] == 2                      # les 2 reels
    assert db.tournament_stats(Filter(money="all"))["entries"] == 4
    # la bankroll ne compte que l'argent reel
    reel = db.tournament_stats()["profit"]
    assert abs(db.bankroll_summary()["tournaments"] - reel) < 0.01


def test_hud_ignore_l_argent_fictif(db):
    from pokertracker.hud.manager import HudManager
    from pokertracker.hud.profile import default_profile
    _base_mixte(db)
    manager = HudManager(db, default_profile())
    assert manager.stats_for("Hero", "PokerStars")["hands"] == 2
