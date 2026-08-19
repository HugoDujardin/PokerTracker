"""Suivi financier des tournois et de la bankroll."""
from datetime import datetime
from decimal import Decimal

from pokertracker.core.db import Filter
from pokertracker.core.parsers.summaries import TournamentResult, parse_summaries
from conftest import DATA


def summaries(name: str):
    return parse_summaries((DATA / f"{name}.txt").read_text(encoding="utf-8"))


def test_resume_pokerstars():
    resultats = summaries("ps_summary")
    assert len(resultats) == 2
    itm, ko = resultats
    assert itm.tournament_id == "3000000001"
    assert (itm.buyin, itm.fee) == (Decimal("9.10"), Decimal("0.90"))
    assert itm.entrants == 245 and itm.finish_place == 12
    assert itm.prize == Decimal("45.30") and itm.itm
    assert itm.profit == Decimal("35.30")
    assert itm.started_at == datetime(2024, 3, 2, 20, 0, 0)
    # tournoi a primes: la cagnotte totale ne doit pas etre prise pour un gain
    assert ko.bounty_buyin == Decimal("4.55")
    assert ko.prize == 0 and ko.bounty_won == Decimal("9.10")
    assert ko.profit == Decimal("-0.90") and not ko.itm


def test_resume_winamax():
    resultat = summaries("winamax_summary")[0]
    assert resultat.room == "Winamax" and resultat.fmt == "spin"
    assert resultat.entrants == 3 and resultat.finish_place == 1
    assert resultat.prize == Decimal("1.35")
    assert resultat.cost == Decimal("0.50") and resultat.profit == Decimal("0.85")


def test_enregistrement_et_bilan(db):
    assert db.insert_tournaments(summaries("ps_summary") + summaries("winamax_summary")) == 3
    assert db.insert_tournaments(summaries("ps_summary")) == 0        # pas de doublon
    stats = db.tournament_stats()
    assert stats["entries"] == 3
    assert round(stats["cost"], 2) == 20.50
    assert round(stats["profit"], 2) == 35.25
    assert stats["itm"] == 2 and round(stats["itm_pct"], 1) == 66.7
    assert stats["wins"] == 1
    assert round(stats["roi"], 1) == 172.0


def test_detection_de_la_bulle(db):
    """Sans prix, une sortie juste au-dessus des places payees est une bulle."""
    def resultat(place: int, prize: str = "0") -> TournamentResult:
        return TournamentResult(room="PokerStars", tournament_id=f"t{place}", entrants=100,
                                finish_place=place, prize=Decimal(prize), buyin=Decimal(10),
                                started_at=datetime(2024, 5, 1, 20, 0))
    db.insert_tournaments([resultat(16), resultat(30), resultat(12, "40"), resultat(17)],
                          bubble_ratio=0.15)
    rows = {r["tournament_id"]: r for r in db.tournaments()}
    assert rows["t16"]["bubble"] == 1        # 15 places payees estimees
    assert rows["t17"]["bubble"] == 1
    assert rows["t30"]["bubble"] == 0        # trop loin de la bulle
    assert rows["t12"]["bubble"] == 0 and rows["t12"]["itm"] == 1
    assert db.tournament_stats()["bubbles"] == 2


def test_filtres_par_periode(db):
    db.insert_tournaments(summaries("ps_summary"))
    ancien = Filter(date_to=datetime(2024, 3, 2, 23, 59))
    assert db.tournament_stats(ancien)["entries"] == 1
    assert db.tournament_stats(Filter(date_from=datetime(2025, 1, 1)))["entries"] == 0
    assert db.tournament_stats(Filter(rooms=["Winamax"]))["entries"] == 0


def test_courbe_et_groupes(db):
    db.insert_tournaments(summaries("ps_summary") + summaries("winamax_summary"))
    courbe = db.tournament_curve()
    assert len(courbe) == 3
    assert round(courbe[-1][2], 2) == 35.25
    groupes = db.tournament_groups("fmt")
    assert set(groupes) == {"mtt", "spin"}
    assert groupes["spin"]["entries"] == 1


def test_bankroll(db, ps_hands):
    db.insert_hands(ps_hands)
    db.insert_tournaments(summaries("winamax_summary"))
    hero = db.player_id("Hero", "PokerStars")
    db.add_bankroll_entry("depot", 200, "virement")
    db.add_bankroll_entry("retrait", 50, "retrait")
    summary = db.bankroll_summary(hero)
    assert round(summary["movements"], 2) == 150.0
    assert round(summary["cash"], 2) == 36.25          # resultats cash du heros
    assert round(summary["tournaments"], 2) == 0.85
    assert round(summary["total"], 2) == 187.10
    assert len(db.bankroll_timeline(hero)) == 5        # 2 mouvements + 1 tournoi + 2 mains
    db.delete_bankroll_entry(db.bankroll_entries()[0]["id"])
    assert len(db.bankroll_entries()) == 1


def test_import_des_resumes(db, tmp_path):
    """Les resumes sont reconnus automatiquement au milieu des historiques."""
    import shutil
    import os
    import time
    from pokertracker.core.importer import Importer

    for name in ("pokerstars_mtt", "ps_summary"):
        target = tmp_path / f"{name}.txt"
        shutil.copy(DATA / f"{name}.txt", target)
        os.utime(target, (time.time() - 60,) * 2)
    result = Importer(db).import_directory(tmp_path)
    assert result.hands == 1 and result.tournaments == 2
    # la main du tournoi est rattachee au resume correspondant
    row = [r for r in db.tournaments() if r["tournament_id"] == "3000000001"][0]
    assert row["hands_played"] == 1
