"""Tests de l'interface (executes hors ecran)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import load  # noqa: E402
from pokertracker.config import Settings  # noqa: E402
from pokertracker.core.importer import HandHistoryWatcher  # noqa: E402
from pokertracker.hud.manager import HudManager  # noqa: E402
from pokertracker.hud.overlay import HudController  # noqa: E402
from pokertracker.hud.profile import default_profile  # noqa: E402
from pokertracker.hud.table_tracker import TableWindow  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def rempli(db):
    db.insert_hands(load("pokerstars_cash"))
    db.insert_hands(load("winamax_cash"))
    return db


def test_tableau_de_bord(qt_app, rempli):
    from pokertracker.ui.tabs import DashboardTab
    tab = DashboardTab(rempli)
    tab.reload_heroes()
    assert "mains" in tab.summary.text()
    assert tab.sessions.rowCount() >= 1
    assert tab.stats_table.rowCount() > 20


def test_onglet_joueurs(qt_app, rempli):
    from pokertracker.ui.tabs import PlayersTab
    tab = PlayersTab(rempli)
    tab.refresh_list()
    assert tab.players.rowCount() > 0
    tab.players.selectRow(0)
    assert tab.current_player is not None
    tab.note.setPlainText("test note")
    tab._save_note()
    assert rempli.get_player(tab.current_player["name"],
                            tab.current_player["room"])["note"] == "test note"


def test_onglet_mains_et_replayer(qt_app, rempli):
    from pokertracker.ui.tabs import HandsTab
    tab = HandsTab(rempli)
    tab.reload_players()
    assert tab.hands.rowCount() > 0
    tab.hands.selectRow(0)
    assert tab.replayer.hand is not None
    assert len(tab.replayer.frames) > 3
    tab.replayer.goto(len(tab.replayer.frames) - 1)
    tab.replayer.compute_equity()


def test_onglet_rapports(qt_app, rempli):
    from pokertracker.ui.tabs import ReportsTab
    tab = ReportsTab(rempli)
    tab.reload_players()
    assert tab.table.rowCount() > 0
    tab.group_box.setCurrentText("Limite")
    assert tab.table.columnCount() > 3


def test_onglet_ranges(qt_app):
    from pokertracker.ui.tabs import RangesTab
    tab = RangesTab()
    tab.range_text.setText("QQ+, AKs")
    tab._on_text_changed()
    assert "mains" in tab.info.text()
    tab.hero_cards.setText("AhKd")
    tab.villain_range.setText("QQ+")
    tab.iterations.setValue(600)
    tab._compute()
    assert "%" in tab.result.text()


def test_editeur_de_hud(qt_app, db):
    from pokertracker.ui.hud_editor import HudEditor
    editor = HudEditor(db)
    assert editor.panel_list.count() == 3
    editor.panel_list.setCurrentRow(0)
    avant = editor.cells.rowCount()
    editor._add_cell()
    assert editor.cells.rowCount() == avant + 1
    editor.profile.name = "Profil test"
    db.save_profile(editor.profile.name, editor.profile.to_json())
    assert "Profil test" in db.load_profiles()


def test_panneaux_hud_positionnes(qt_app, rempli):
    from pokertracker.hud.manager import TableHud
    hands = load("pokerstars_cash")
    manager = HudManager(rempli, default_profile())
    manager.on_new_hands(hands)
    controller = HudController(manager, Settings())
    state = list(manager.tables.values())[0]
    window = TableWindow(handle=1, title="t", room="PokerStars", table_name="Aludra II",
                         x=100, y=100, width=800, height=600)
    controller._refresh_table(TableHud(window=window, state=state,
                                       panels=manager.build_panels(state)), set())
    assert len(controller.panels) == 6
    for widget in controller.panels.values():
        assert 50 <= widget.pos().x() <= 900
        assert 50 <= widget.pos().y() <= 700
    controller.hide_all()


def test_fenetre_principale(qt_app, rempli, tmp_path):
    from pokertracker.ui.main_window import MainWindow
    settings = Settings()
    settings.db_path = str(tmp_path / "x.db")
    watcher = HandHistoryWatcher(rempli, [], 1.0)
    manager = HudManager(rempli, default_profile())
    controller = HudController(manager, settings)
    window = MainWindow(rempli, settings, watcher, manager, controller)
    assert window.tabs.count() == 9
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Tableau de bord", "Joueurs", "Mains", "Rapports", "Tournois", "Ranges",
        "Coach IA", "HUD", "Import"]
    window.update_status()
    assert "Mains:" in window.status_label.text()
    window._on_new_hands(load("ggpoker_cash"))
    assert manager.tables
    window.hud_tab.open_demo()
    assert window.hud_tab.demo is not None
    assert any(t.window.table_name for t in manager.snapshot())
