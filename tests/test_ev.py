"""Gains ajustes a l'equite (all-in EV)."""
from conftest import load
from pokertracker.core.stats.ev import compute_ev, is_allin_showdown
from pokertracker.core.stats import definitions as sd


def test_detection_des_allin(ps_hands):
    assert not is_allin_showdown(ps_hands[0])      # main jouee jusqu'a la riviere sans tapis
    assert is_allin_showdown(ps_hands[1])          # tapis paye au turn


def test_ev_exacte_au_turn(ps_hands):
    """QQ (brelan) contre AA au turn: seul un as sauve l'adversaire (2 outs)."""
    hand = ps_hands[1]
    ev = compute_ev(hand)
    assert ev is not None
    equity_hero = 42 / 44                          # 44 cartes, 2 perdantes
    collected = 88.25
    attendu = equity_hero * collected - 44.50
    assert abs(ev["Hero"] - attendu) < 0.01
    assert abs(ev["Hero"] - 39.74) < 0.05
    # le resultat reel est meilleur que l'esperance: la main a ete gagnee
    assert float(hand.seat_of("Hero").net) > ev["Hero"]


def test_conservation_de_l_argent(ps_hands):
    """La somme des gains ajustes vaut la somme des gains reels: -rake."""
    hand = ps_hands[1]
    ev = compute_ev(hand)
    assert abs(sum(ev.values()) + float(hand.rake)) < 0.05


def test_main_sans_allin_conserve_son_resultat(ps_hands):
    assert compute_ev(ps_hands[0]) is None


def test_stats_et_courbe_ev(db, ps_hands):
    db.insert_hands(ps_hands)
    pid = db.player_id("Hero", "PokerStars")
    agg = db.aggregate([pid])
    assert agg["allin_ev_hands"] == 1
    assert abs(agg["ev_net"] - 32.24) < 0.05
    assert sd.get("ev_bb100").format(agg) != "-"
    curve = db.bankroll_curve(pid)
    assert len(curve[0]) == 6                      # main, ts, gains, bb, ev, ev_bb
    assert curve[-1][4] < curve[-1][2]             # ajuste plus bas que le reel ici


def test_recalcul_des_compteurs(db, ps_hands):
    db.insert_hands(ps_hands)
    db.conn.execute("UPDATE hand_players SET ev_net = 0, ev_bb = 0, vpip = 0")
    db.conn.commit()
    db.rebuild_totals()
    assert db.aggregate([db.player_id("Hero", "PokerStars")])["ev_net"] == 0
    assert db.rebuild_counters() == 2
    agg = db.aggregate([db.player_id("Hero", "PokerStars")])
    assert abs(agg["ev_net"] - 32.24) < 0.05
    assert agg["vpip"] == 2
