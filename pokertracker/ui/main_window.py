"""Fenetre principale de PokerTracker."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSpinBox, QStatusBar, QTabWidget, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from ..config import Settings
from ..core.db import Database
from ..core.importer import HandHistoryWatcher
from ..core.models import Hand
from ..hud.manager import HudManager
from ..hud.overlay import HudController
from ..hud.profile import BUILTIN_PROFILES, HudProfile
from .demo_table import DemoTable
from .scaling import fit_button, fit_widgets
from .hud_editor import HudEditor
from .tabs import DashboardTab, HandsTab, ImportTab, PlayersTab, RangesTab, ReportsTab
from .coach_tab import CoachTab
from .tournaments_tab import TournamentsTab


class HandsBridge(QObject):
    """Relaie les mains importees par le thread de surveillance vers l'interface."""
    new_hands = Signal(list)


class HudTab(QWidget):
    """Reglages du HUD, editeur de profil et table de demonstration."""

    def __init__(self, db: Database, settings: Settings, manager: HudManager,
                 controller: HudController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.manager = manager
        self.controller = controller
        self.demo: Optional[DemoTable] = None

        self.enabled = QCheckBox("HUD active")
        self.enabled.setChecked(settings.hud_enabled)
        self.enabled.stateChanged.connect(self._toggle)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.2, 1.0)
        self.opacity.setSingleStep(0.05)
        self.opacity.setValue(settings.hud_opacity)
        self.opacity.valueChanged.connect(self._apply_settings)
        self.min_hands = QSpinBox()
        self.min_hands.setRange(0, 10000)
        self.min_hands.setValue(settings.hud_min_hands)
        self.min_hands.valueChanged.connect(self._apply_settings)
        self.hover_popup = QCheckBox("Popup au survol")
        self.hover_popup.setChecked(settings.popup_on_hover)
        self.hover_popup.stateChanged.connect(self._apply_settings)

        btn_demo = QPushButton("Ouvrir une table de demonstration")
        btn_demo.clicked.connect(self.open_demo)
        btn_reset = QPushButton("Reinitialiser les positions des panneaux")
        btn_reset.clicked.connect(self._reset_offsets)

        settings_box = QGroupBox("Reglages")
        form = QFormLayout(settings_box)
        form.addRow(self.enabled)
        form.addRow("Opacite", self.opacity)
        form.addRow("Mains minimum pour afficher un joueur", self.min_hands)
        form.addRow(self.hover_popup)
        form.addRow(btn_demo)
        form.addRow(btn_reset)

        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        self.state_label.setStyleSheet("color:#8fb3d9;")
        self.tables = QTableWidget(0, 5)
        self.tables.setHorizontalHeaderLabels(["Room", "Table", "Fenetre", "Joueurs suivis",
                                               "Derniere main"])
        self.tables.verticalHeader().setVisible(False)
        tables_box = QGroupBox("Tables detectees")
        tables_layout = QVBoxLayout(tables_box)
        tables_layout.addWidget(self.state_label)
        tables_layout.addWidget(self.tables)

        self.editor = HudEditor(db, manager.profile)
        self.editor.profile_changed.connect(self._on_profile_changed)

        top = QHBoxLayout()
        top.addWidget(settings_box)
        top.addWidget(tables_box, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.editor, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_tables)
        self._timer.start(2000)

    # ------------------------------------------------------------------
    def _toggle(self) -> None:
        self.settings.hud_enabled = self.enabled.isChecked()
        self.settings.save()
        self.controller.set_enabled(self.settings.hud_enabled)

    def _apply_settings(self) -> None:
        self.settings.hud_opacity = self.opacity.value()
        self.settings.hud_min_hands = self.min_hands.value()
        self.settings.popup_on_hover = self.hover_popup.isChecked()
        self.settings.save()
        self.manager.min_hands = self.settings.hud_min_hands

    def _reset_offsets(self) -> None:
        self.controller.offsets.clear()
        self.controller._save_offsets()
        for widget in self.controller.panels.values():
            widget.offset *= 0
        QMessageBox.information(self, "HUD", "Positions des panneaux reinitialisees.")

    def _on_profile_changed(self, profile: HudProfile) -> None:
        self.manager.profile = profile
        self.controller.set_profile_font()
        self.settings.hud_profile = profile.name
        self.settings.save()

    def open_demo(self) -> None:
        """Ouvre une fausse table, calquee sur la derniere table jouee."""
        if self.demo is None:
            recent = self.db.recent_table_hands(1)
            if recent:
                row = recent[0]
                self.demo = DemoTable(room=row["room"], table_name=row["table_name"] or "Demo",
                                      seats=int(row["nb_players"] or 6))
            else:
                self.demo = DemoTable()
            self.manager.tracker.register_source(self.demo.as_table_window)
        self.manager.restore_recent_tables()
        self.demo.show()
        self.demo.raise_()
        self.controller.set_enabled(self.enabled.isChecked())
        self.controller.refresh()
        self.refresh_tables()

    def refresh_tables(self) -> None:
        snapshot = self.manager.snapshot()
        rows = []
        for table in snapshot:
            state = table.state
            rows.append((table.window.room, table.window.table_name,
                         f"{table.window.width}x{table.window.height}",
                         str(len(table.panels)),
                         state.last_hand_id if state else "-"))
        self.tables.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for col, value in enumerate(row):
                self.tables.setItem(i, col, QTableWidgetItem(str(value)))
        self.state_label.setText(self._diagnostic(snapshot))

    def _diagnostic(self, snapshot) -> str:
        """Explique en clair pourquoi le HUD affiche ou n'affiche pas de panneaux."""
        if not self.enabled.isChecked():
            return "HUD desactive : cochez « HUD active » pour l'afficher."
        if self.db.counts()["hands"] == 0:
            return ("Aucune main en base : importez d'abord vos historiques "
                    "(onglet Import), le HUD a besoin de mains pour afficher des stats.")
        if not snapshot:
            return ("Aucune table de poker detectee. Ouvrez une table dans votre client, "
                    "ou cliquez sur « Ouvrir une table de demonstration » pour un essai.")
        panels = sum(len(t.panels) for t in snapshot)
        if not panels:
            return ("Table detectee mais aucun joueur reconnu : le HUD a besoin d'au moins "
                    "une main deja jouee sur cette table (ou baissez « Mains minimum »).")
        return f"{len(snapshot)} table(s) suivie(s), {panels} panneau(x) affiche(s)."


class MainWindow(QMainWindow):
    """Fenetre principale: onglets, barre d'etat et pilotage du HUD."""

    def __init__(self, db: Database, settings: Settings, watcher: HandHistoryWatcher,
                 manager: HudManager, controller: HudController) -> None:
        super().__init__()
        self.db = db
        self.settings = settings
        self.watcher = watcher
        self.manager = manager
        self.controller = controller
        self.setWindowTitle("PokerTracker — suivi et HUD de poker en ligne")
        self.resize(1280, 820)

        self.dashboard = DashboardTab(db)
        self.players = PlayersTab(db)
        self.hands = HandsTab(db)
        self.reports = ReportsTab(db)
        self.tournaments = TournamentsTab(db)
        self.ranges = RangesTab()
        self.hud_tab = HudTab(db, settings, manager, controller)
        self.coach = CoachTab(db, settings, current_hand=self.selected_hand)
        self.import_tab = ImportTab(db, settings, watcher)
        self.import_tab.imported.connect(lambda n: self.reload_all())

        self.tabs = QTabWidget()
        self.tabs.addTab(self.dashboard, "Tableau de bord")
        self.tabs.addTab(self.players, "Joueurs")
        self.tabs.addTab(self.hands, "Mains")
        self.tabs.addTab(self.reports, "Rapports")
        self.tabs.addTab(self.tournaments, "Tournois")
        self.tabs.addTab(self.ranges, "Ranges")
        self.tabs.addTab(self.coach, "Coach IA")
        self.tabs.addTab(self.hud_tab, "HUD")
        self.tabs.addTab(self.import_tab, "Import")
        self.setCentralWidget(self.tabs)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("")
        self.status.addPermanentWidget(self.status_label)

        self._bridge = HandsBridge()
        self._bridge.new_hands.connect(self._on_new_hands)
        watcher.subscribe(lambda hands: self._bridge.new_hands.emit(list(hands)))
        controller.note_callback = self._edit_note

        self._build_menu()
        # les libelles ne doivent jamais etre tronques, quelle que soit la
        # police du systeme ou la mise a l'echelle de l'ecran
        fit_widgets(self)
        fit_button(self.hands.replayer.btn_play, "Lecture", "Pause")
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self.update_status)
        self._status_timer.start(2000)
        self.reload_all()

    def selected_hand(self):
        """Main actuellement chargee dans le replayer (pour le coach IA)."""
        return self.hands.replayer.hand

    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&Fichier")
        act_import = QAction("Importer un dossier...", self)
        act_import.setShortcut(QKeySequence("Ctrl+I"))
        act_import.triggered.connect(lambda: (self.tabs.setCurrentWidget(self.import_tab),
                                              self.import_tab._add_folder()))
        act_scan = QAction("Importer maintenant", self)
        act_scan.setShortcut(QKeySequence("F5"))
        act_scan.triggered.connect(self.import_tab.run_import)
        act_quit = QAction("Quitter", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_import)
        file_menu.addAction(act_scan)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        hud_menu = menu.addMenu("&HUD")
        self.act_hud = QAction("Activer le HUD", self, checkable=True)
        self.act_hud.setChecked(self.settings.hud_enabled)
        self.act_hud.setShortcut(QKeySequence("Ctrl+H"))
        self.act_hud.triggered.connect(self._toggle_hud)
        act_demo = QAction("Table de demonstration", self)
        act_demo.triggered.connect(self.hud_tab.open_demo)
        hud_menu.addAction(self.act_hud)
        hud_menu.addAction(act_demo)

        help_menu = menu.addMenu("&Aide")
        act_about = QAction("A propos", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    def _toggle_hud(self, checked: bool) -> None:
        self.settings.hud_enabled = checked
        self.settings.save()
        self.controller.set_enabled(checked)
        self.hud_tab.enabled.setChecked(checked)

    def _about(self) -> None:
        counts = self.db.counts()
        QMessageBox.about(
            self, "A propos de PokerTracker",
            "<h3>PokerTracker</h3>"
            "<p>Suivi de mains, statistiques et HUD temps reel pour le poker en ligne, "
            "compatible Windows 11.</p>"
            f"<p>Base: {counts['hands']} mains, {counts['players']} joueurs, "
            f"{counts['files']} fichiers suivis.</p>")

    # ------------------------------------------------------------------
    def _on_new_hands(self, hands: List[Hand]) -> None:
        self.manager.on_new_hands(hands)
        self.status.showMessage(f"{len(hands)} nouvelle(s) main(s) importee(s)", 4000)
        self.controller.refresh()

    def _edit_note(self, player: str, room: str) -> None:
        row = self.db.get_player(player, room)
        if row is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, f"Note sur {player}", "Note:",
                                                 row["note"] or "")
        if ok:
            self.db.set_note(row["id"], text, row["color"] or "", row["label"] or "")
            self.manager.invalidate()

    def reload_all(self) -> None:
        self.dashboard.reload_heroes()
        fit_widgets(self)
        self.players.refresh_list()
        self.hands.reload_players()
        self.reports.reload_players()
        self.tournaments.reload_players()
        self.coach.reload_players()
        self.manager.invalidate()

    def update_status(self) -> None:
        counts = self.db.counts()
        watching = "actif" if self.watcher.running else "arrete"
        tables = len(self.manager.tables)
        self.status_label.setText(
            f"Mains: {counts['hands']}  ·  Joueurs: {counts['players']}  ·  "
            f"Surveillance: {watching}  ·  Tables suivies: {tables}")

    def closeEvent(self, event) -> None:  # pragma: no cover - fermeture
        self.watcher.stop()
        self.controller.stop()
        self.settings.save()
        super().closeEvent(event)
