"""Tests du HUD: profils dynamiques, placement et appariement des tables."""
from conftest import load
from pokertracker.hud.manager import HudManager, TableState
from pokertracker.hud.profile import (HudPanel, HudProfile, PanelCondition, PlayerContext,
                                      StatCell, default_profile)
from pokertracker.hud.seatmap import seat_positions, to_screen
from pokertracker.hud.table_tracker import TableWindow, identify_table


def test_selection_dynamique_du_panneau():
    profile = default_profile()
    assert profile.panel_for(PlayerContext(position="CO", stack_bb=100, nb_players=6)).name \
        == "Principal"
    assert profile.panel_for(PlayerContext(position="BB", stack_bb=100, nb_players=6)).name \
        == "Defense des blindes"
    assert profile.panel_for(PlayerContext(position="CO", stack_bb=18, nb_players=6)).name \
        == "Tapis court"
    # profondeur inconnue: la condition sur le tapis ne s'applique pas
    assert profile.panel_for(PlayerContext(position="CO", nb_players=6)).name == "Principal"


def test_conditions_personnalisees():
    condition = PanelCondition(positions=["BTN"], min_players=3, min_hands=50)
    assert condition.matches(PlayerContext(position="BTN", nb_players=6, hands=100))
    assert not condition.matches(PlayerContext(position="BTN", nb_players=6, hands=10))
    assert not condition.matches(PlayerContext(position="CO", nb_players=6, hands=100))


def test_serialisation_du_profil():
    profile = default_profile()
    copie = HudProfile.from_json(profile.to_json())
    assert copie.to_json() == profile.to_json()
    assert [p.name for p in copie.panels] == [p.name for p in profile.panels]
    assert copie.panels[0].rows[0][0].code == profile.panels[0].rows[0][0].code


def test_coloration_des_valeurs():
    cell = default_profile().panels[-1].rows[0][1]        # VPIP
    texte, couleur = cell.display({"vpip": 45, "vpip_opp": 100})
    assert texte == "45" and couleur == "#ff6b6b"          # au-dessus du seuil haut
    texte, couleur = cell.display({"vpip": 10, "vpip_opp": 100})
    assert texte == "10" and couleur == "#5fb3ff"
    texte, couleur = cell.display({"vpip": 25, "vpip_opp": 100})
    assert couleur == "#e6e6e6"


def test_echantillon_minimum():
    cell = StatCell("3bet", min_sample=30)
    assert cell.display({"three_bet": 1, "three_bet_opp": 5})[0] == "-"
    assert cell.display({"three_bet": 6, "three_bet_opp": 60})[0] == "10"


def test_placement_des_sieges():
    positions = seat_positions([1, 2, 3, 4, 5, 6], hero_seat=2, max_seats=6)
    assert len(positions) == 6
    # le heros est place en bas de la table
    assert positions[2][1] > 0.6
    assert to_screen((100, 200, 800, 600), (0.5, 0.5)) == (500, 500)


def test_etat_de_table_et_positions_suivantes():
    hands = load("pokerstars_cash")
    state = TableState(room="PokerStars", table_name="Aludra II")
    state.update_from_hand(hands[0])
    assert state.button_seat == 4
    assert state.seats[4].position == "BTN"
    assert state.seats[5].next_position == "BTN"     # le bouton avance d'un siege
    assert state.seats[2].player == "Hero" and state.seats[2].is_hero


def test_panneaux_du_hud(db):
    hands = load("pokerstars_cash")
    db.insert_hands(hands)
    manager = HudManager(db, default_profile())
    manager.on_new_hands(hands)
    state = list(manager.tables.values())[0]
    panels = manager.build_panels(state)
    assert len(panels) == 6
    hero = next(p for p in panels if p.is_hero)
    assert hero.rows and hero.rows[0][0].text != ""
    assert 0 <= hero.rel_x <= 1 and 0 <= hero.rel_y <= 1


def test_filtre_sur_le_nombre_de_mains(db):
    hands = load("pokerstars_cash")
    db.insert_hands(hands)
    manager = HudManager(db, default_profile(), min_hands=10)
    manager.on_new_hands(hands)
    state = list(manager.tables.values())[0]
    panels = manager.build_panels(state)
    assert [p.player for p in panels] == ["Hero"]     # seul le heros reste affiche


def test_appariement_fenetre_table(db):
    hands = load("pokerstars_cash")
    db.insert_hands(hands)
    manager = HudManager(db, default_profile())
    manager.on_new_hands(hands)
    window = TableWindow(handle=1, title="Aludra II - $0.25/$0.50 USD - No Limit Hold'em",
                         room="PokerStars", table_name="Aludra II")
    assert manager.match_window(window).table_name == "Aludra II"
    autre = TableWindow(handle=2, title="X", room="PokerStars", table_name="Table inconnue")
    assert manager.match_window(autre) is not None    # une seule table suivie: repli


def test_reconnaissance_des_titres():
    table = identify_table("Aludra II - $0.25/$0.50 USD - No Limit Hold'em")
    assert table and table.room == "PokerStars" and table.table_name == "Aludra II"
    assert identify_table("PokerStars Lobby") is None
    assert identify_table("Bloc-notes") is None
    winamax = identify_table("Nice 05 / 0,05 € / 0,10 € - Holdem NL")
    assert winamax and winamax.room == "Winamax"


def test_popup(db):
    hands = load("pokerstars_cash")
    db.insert_hands(hands)
    manager = HudManager(db, default_profile())
    manager.on_new_hands(hands)
    sections = manager.popup_data("Hero", "PokerStars")
    titres = [t for t, _ in sections]
    assert titres == ["Preflop", "Flop", "Turn", "River", "Global"]
    assert any(label == "VPIP" for label, _v, _n in sections[0][1])
