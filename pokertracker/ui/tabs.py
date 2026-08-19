"""Onglets principaux de l'application."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget)

from ..core.db import Database, Filter
from ..core.equity.equity import equity
from ..core.equity.ranges import parse_range, range_percent, range_to_text
from ..core.importer import Importer, detect_hh_directories
from ..core.stats import definitions as sd
from ..core.parsers import registry
from .replayer import Replayer
from .widgets import CardsLabel, ComparisonTable, RangeGrid, StatsTable, WinningsGraph

POSITION_ORDER = ["UTG", "UTG1", "UTG2", "MP", "MP1", "HJ", "CO", "BTN", "SB", "BB"]
SUMMARY_CODES = ["hands", "vpip", "pfr", "3bet", "f3bet", "steal", "cbet_f", "wtsd", "wsd",
                 "wwsf", "af", "bb100"]


class FilterBar(QWidget):
    """Barre de filtres commune (room, limite, format, periode)."""

    changed = Signal()

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.room = QComboBox()
        self.stake = QComboBox()
        self.fmt = QComboBox()
        self.players = QComboBox()
        self.players.addItems(["Tous", "Heads-up (2)", "6-max (3-6)", "Full ring (7+)"])
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(datetime.now().date() - timedelta(days=365 * 3))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(datetime.now().date())
        self.play_money = QCheckBox("Inclure l'argent fictif")
        self.play_money.setToolTip("Par defaut, seules les tables et les tournois en argent "
                                   "reel sont pris en compte.")
        self.play_money.stateChanged.connect(self.changed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for label, widget in (("Room", self.room), ("Limite", self.stake), ("Format", self.fmt),
                              ("Joueurs", self.players), ("Du", self.date_from),
                              ("Au", self.date_to)):
            layout.addWidget(QLabel(label))
            layout.addWidget(widget)
        layout.addWidget(self.play_money)
        layout.addStretch(1)
        for widget in (self.room, self.stake, self.fmt, self.players):
            widget.currentIndexChanged.connect(self.changed)
        for widget in (self.date_from, self.date_to):
            widget.dateChanged.connect(self.changed)
        self.reload()

    def reload(self) -> None:
        for widget, column in ((self.room, "room"), (self.stake, "stake"), (self.fmt, "fmt")):
            current = widget.currentText()
            widget.blockSignals(True)
            widget.clear()
            widget.addItem("Tous")
            try:
                widget.addItems(self.db.distinct(column))
            except Exception:
                pass
            index = widget.findText(current)
            widget.setCurrentIndex(max(0, index))
            widget.blockSignals(False)

    def build(self) -> Filter:
        flt = Filter()
        if self.room.currentIndex() > 0:
            flt.rooms = [self.room.currentText()]
        if self.stake.currentIndex() > 0:
            flt.stakes = [self.stake.currentText()]
        if self.fmt.currentIndex() > 0:
            flt.formats = [self.fmt.currentText()]
        choice = self.players.currentIndex()
        if choice == 1:
            flt.min_players, flt.max_players = 2, 2
        elif choice == 2:
            flt.min_players, flt.max_players = 3, 6
        elif choice == 3:
            flt.min_players = 7
        flt.date_from = datetime.combine(self.date_from.date().toPython(), datetime.min.time())
        flt.date_to = datetime.combine(self.date_to.date().toPython(), datetime.max.time())
        flt.money = "all" if self.play_money.isChecked() else "real"
        return flt


class DashboardTab(QWidget):
    """Vue d'ensemble des resultats du heros."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.hero_box = QComboBox()
        self.hero_box.currentIndexChanged.connect(self.refresh)
        self.unit_box = QComboBox()
        self.unit_box.addItems(["bb", "argent"])
        self.unit_box.currentIndexChanged.connect(self.refresh)
        self.show_ev = QCheckBox("Courbe ajustee a l'equite (all-in EV)")
        self.show_ev.setChecked(True)
        self.show_ev.setToolTip("Remplace le resultat des all-in par leur esperance "
                                "mathematique: l'ecart entre les deux courbes est la chance.")
        self.show_ev.stateChanged.connect(self.refresh)
        self.filters = FilterBar(db)
        self.filters.changed.connect(self.refresh)

        self.graph = WinningsGraph()
        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#cfd8e3;")
        self.summary.setWordWrap(True)
        self.sessions = QTableWidget(0, 7)
        self.sessions.setHorizontalHeaderLabels(
            ["Debut", "Duree", "Mains", "Limites", "Gains", "bb/100", "Tables"])
        self.sessions.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sessions.verticalHeader().setVisible(False)
        self.sessions.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stats_table = StatsTable()

        head = QHBoxLayout()
        head.addWidget(QLabel("Heros:"))
        head.addWidget(self.hero_box)
        head.addWidget(QLabel("Unite:"))
        head.addWidget(self.unit_box)
        head.addWidget(self.show_ev)
        head.addStretch(1)

        split = QSplitter(Qt.Vertical)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.summary)
        top_layout.addWidget(self.graph, 1)
        split.addWidget(top)
        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(self.sessions)
        bottom.addWidget(self.stats_table)
        bottom.setSizes([500, 500])
        split.addWidget(bottom)
        split.setSizes([420, 300])

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.filters)
        layout.addWidget(split, 1)

    # ------------------------------------------------------------------
    def reload_heroes(self) -> None:
        current = self.hero_box.currentText()
        self.hero_box.blockSignals(True)
        self.hero_box.clear()
        for row in self.db.heroes():
            self.hero_box.addItem(f"{row['name']} ({row['room']})", row["id"])
        index = self.hero_box.findText(current)
        if index >= 0:
            self.hero_box.setCurrentIndex(index)
        self.hero_box.blockSignals(False)
        self.filters.reload()
        self.refresh()

    def refresh(self) -> None:
        player_id = self.hero_box.currentData()
        if player_id is None:
            self.summary.setText("Importez des mains pour voir vos resultats.")
            return
        flt = self.filters.build()
        agg = self.db.aggregate([player_id], flt)
        curve = self.db.bankroll_curve(player_id, flt)
        self.graph.show_bb = self.unit_box.currentText() == "bb"
        self.graph.show_ev = self.show_ev.isChecked()
        self.graph.set_curve(curve)
        hands = int(agg.get("hands", 0) or 0)
        net = float(agg.get("amount_net", 0) or 0)
        bb = float(agg.get("bb_net", 0) or 0)
        winrate = 100 * bb / hands if hands else 0
        ev_bb = float(agg.get("ev_bb", 0) or 0)
        ev_rate = 100 * ev_bb / hands if hands else 0
        luck = bb - ev_bb
        allin = int(agg.get("allin_ev_hands", 0) or 0)
        self.summary.setText(
            f"<b>{hands}</b> mains &nbsp;·&nbsp; gains <b>{net:+.2f}</b> &nbsp;·&nbsp; "
            f"<b>{winrate:+.2f}</b> bb/100 &nbsp;·&nbsp; "
            f"ajuste <b>{ev_rate:+.2f}</b> bb/100 &nbsp;·&nbsp; "
            f"chance <b>{luck:+.1f}</b> bb sur {allin} all-in &nbsp;·&nbsp; "
            f"VPIP {sd.get('vpip').format(agg)} / PFR {sd.get('pfr').format(agg)} / "
            f"3Bet {sd.get('3bet').format(agg)}")
        self.stats_table.show_stats(agg)
        self._fill_sessions(player_id, flt)

    def _fill_sessions(self, player_id: int, flt: Filter, gap_minutes: int = 30) -> None:
        where, params = flt.where()
        sql = (f"SELECT h.played_ts, h.stake, h.table_name, hp.net, hp.bb_net FROM hand_players hp "
               f"JOIN hands h ON h.id = hp.hand_id WHERE {where} AND hp.player_id = ? "
               f"ORDER BY h.played_ts")
        rows = list(self.db.conn.execute(sql, params + [player_id]))
        sessions: List[dict] = []
        for row in rows:
            if sessions and row["played_ts"] - sessions[-1]["end"] <= gap_minutes * 60:
                session = sessions[-1]
            else:
                session = {"start": row["played_ts"], "end": row["played_ts"], "hands": 0,
                           "net": 0.0, "bb": 0.0, "stakes": set(), "tables": set()}
                sessions.append(session)
            session["end"] = row["played_ts"]
            session["hands"] += 1
            session["net"] += row["net"] or 0
            session["bb"] += row["bb_net"] or 0
            session["stakes"].add(row["stake"])
            session["tables"].add(row["table_name"])
        sessions.reverse()
        self.sessions.setRowCount(len(sessions))
        for i, session in enumerate(sessions):
            duration = timedelta(seconds=int(session["end"] - session["start"]))
            values = [
                datetime.fromtimestamp(session["start"]).strftime("%d/%m/%Y %H:%M"),
                str(duration),
                str(session["hands"]),
                ", ".join(sorted(x for x in session["stakes"] if x))[:22],
                f"{session['net']:+.2f}",
                f"{100 * session['bb'] / session['hands']:+.1f}" if session["hands"] else "-",
                str(len(session["tables"])),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (4, 5):
                    item.setForeground(QColor("#5fd08a" if not value.startswith("-") else "#ff6b6b"))
                    item.setTextAlignment(Qt.AlignCenter)
                self.sessions.setItem(i, col, item)


class PlayersTab(QWidget):
    """Recherche de joueurs, statistiques detaillees et notes."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.current_player: Optional[dict] = None

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un joueur...")
        self.search.textChanged.connect(self.refresh_list)
        self.players = QTableWidget(0, 7)
        self.players.setHorizontalHeaderLabels(["Joueur", "Room", "Mains", "VPIP", "PFR", "3Bet",
                                                "bb/100"])
        self.players.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.players.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.players.verticalHeader().setVisible(False)
        self.players.itemSelectionChanged.connect(self._on_selected)
        self.players.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        self.stats_table = StatsTable()
        self.positions = ComparisonTable()
        self.note = QTextEdit()
        self.note.setPlaceholderText("Note sur le joueur (visible dans le HUD)")
        self.color = QComboBox()
        self.color.addItems(["", "#7a2c2c", "#2c5f7a", "#2c7a45", "#7a6a2c", "#5a2c7a"])
        self.label = QLineEdit()
        self.label.setPlaceholderText("Etiquette: fish, reg, nit...")
        btn_save = QPushButton("Enregistrer la note")
        btn_save.clicked.connect(self._save_note)

        note_box = QGroupBox("Note et etiquette")
        form = QFormLayout(note_box)
        form.addRow(self.note)
        form.addRow("Couleur", self.color)
        form.addRow("Etiquette", self.label)
        form.addRow(btn_save)

        left = QVBoxLayout()
        left.addWidget(self.search)
        left.addWidget(self.players, 1)
        left_widget = QWidget()
        left_widget.setLayout(left)

        right = QVBoxLayout()
        right.addWidget(QLabel("Statistiques par position"))
        right.addWidget(self.positions, 1)
        right.addWidget(QLabel("Toutes les statistiques"))
        right.addWidget(self.stats_table, 2)
        right.addWidget(note_box)
        right_widget = QWidget()
        right_widget.setLayout(right)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left_widget)
        split.addWidget(right_widget)
        split.setSizes([380, 700])
        layout = QVBoxLayout(self)
        layout.addWidget(split)

    # ------------------------------------------------------------------
    def refresh_list(self) -> None:
        rows = self.db.find_players(self.search.text(), limit=300)
        ids = [r["id"] for r in rows]
        aggs = {}
        if ids:
            for row in rows:
                aggs[row["id"]] = None
        self.players.setRowCount(len(rows))
        for i, row in enumerate(rows):
            agg = self.db.aggregate([row["id"]])
            values = [row["name"], row["room"], str(int(agg.get("hands", 0) or 0)),
                      sd.get("vpip").format(agg), sd.get("pfr").format(agg),
                      sd.get("3bet").format(agg), sd.get("bb100").format(agg)]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row["id"])
                if col > 1:
                    item.setTextAlignment(Qt.AlignCenter)
                if row["color"] and col == 0:
                    item.setBackground(QColor(row["color"]))
                self.players.setItem(i, col, item)

    def _on_selected(self) -> None:
        items = self.players.selectedItems()
        if not items:
            return
        player_id = items[0].data(Qt.UserRole)
        row = self.db.conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        if row is None:
            return
        self.current_player = dict(row)
        agg = self.db.aggregate([player_id])
        self.stats_table.show_stats(agg)
        groups = self.db.aggregate([player_id], group_by="hp.position")
        self.positions.show_groups(groups, SUMMARY_CODES, "Position", POSITION_ORDER)
        self.note.setPlainText(row["note"] or "")
        self.color.setCurrentText(row["color"] or "")
        self.label.setText(row["label"] or "")

    def _save_note(self) -> None:
        if not self.current_player:
            return
        self.db.set_note(self.current_player["id"], self.note.toPlainText(),
                         self.color.currentText(), self.label.text())
        self.refresh_list()

    def select_player(self, name: str) -> None:
        self.search.setText(name)
        self.refresh_list()
        if self.players.rowCount():
            self.players.selectRow(0)


class HandsTab(QWidget):
    """Liste des mains jouees et replayer."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.player_box = QComboBox()
        self.player_box.currentIndexChanged.connect(self.refresh)
        self.only_won = QCheckBox("Mains gagnees")
        self.only_won.stateChanged.connect(self.refresh)
        self.only_showdown = QCheckBox("Avec abattage")
        self.only_showdown.stateChanged.connect(self.refresh)
        self.filters = FilterBar(db)
        self.filters.changed.connect(self.refresh)

        self.hands = QTableWidget(0, 7)
        self.hands.setHorizontalHeaderLabels(["Date", "Room", "Table", "Limite", "Position",
                                              "Cartes", "Gain"])
        self.hands.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hands.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.hands.verticalHeader().setVisible(False)
        self.hands.itemSelectionChanged.connect(self._on_selected)
        self.hands.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.replayer = Replayer()

        head = QHBoxLayout()
        head.addWidget(QLabel("Joueur:"))
        head.addWidget(self.player_box, 1)
        head.addWidget(self.only_won)
        head.addWidget(self.only_showdown)

        left = QVBoxLayout()
        left.addLayout(head)
        left.addWidget(self.filters)
        left.addWidget(self.hands, 1)
        left_widget = QWidget()
        left_widget.setLayout(left)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left_widget)
        split.addWidget(self.replayer)
        split.setSizes([520, 640])
        layout = QVBoxLayout(self)
        layout.addWidget(split)

    def reload_players(self) -> None:
        current = self.player_box.currentText()
        self.player_box.blockSignals(True)
        self.player_box.clear()
        for row in self.db.heroes():
            self.player_box.addItem(f"{row['name']} ({row['room']})", row["id"])
        for row in self.db.find_players("", limit=100):
            if not row["is_hero"]:
                self.player_box.addItem(f"{row['name']} ({row['room']})", row["id"])
        index = self.player_box.findText(current)
        if index >= 0:
            self.player_box.setCurrentIndex(index)
        self.player_box.blockSignals(False)
        self.filters.reload()
        self.refresh()

    def refresh(self) -> None:
        player_id = self.player_box.currentData()
        if player_id is None:
            return
        rows = self.db.hands_of_player(player_id, self.filters.build(), limit=1000)
        if self.only_won.isChecked():
            rows = [r for r in rows if (r["net"] or 0) > 0]
        if self.only_showdown.isChecked():
            rows = [r for r in rows if r["cards"]]
        self.hands.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = [row["played_at"].replace("T", " "), row["room"], row["table_name"],
                      row["stake"], row["position"] or "", row["cards"] or "",
                      f"{row['net']:+.2f}"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, row["id"])
                if col == 6:
                    item.setForeground(QColor("#5fd08a" if (row["net"] or 0) >= 0 else "#ff6b6b"))
                self.hands.setItem(i, col, item)

    def _on_selected(self) -> None:
        items = self.hands.selectedItems()
        if not items:
            return
        hand_row = self.db.hand_by_id(items[0].data(Qt.UserRole))
        if hand_row and hand_row["raw_text"]:
            self.replayer.load_raw(hand_row["raw_text"])


class ReportsTab(QWidget):
    """Rapports croises: statistiques par position, limite, format..."""

    GROUPS = {
        "Position": ("hp.position", POSITION_ORDER),
        "Limite": ("h.stake", []),
        "Room": ("h.room", []),
        "Format": ("h.fmt", []),
        "Table": ("h.table_name", []),
        "Nombre de joueurs": ("h.nb_players", []),
    }

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.player_box = QComboBox()
        self.player_box.currentIndexChanged.connect(self.refresh)
        self.group_box = QComboBox()
        self.group_box.addItems(list(self.GROUPS))
        self.group_box.currentIndexChanged.connect(self.refresh)
        self.category_box = QComboBox()
        self.category_box.addItems(["Resume"] + sd.CATEGORIES)
        self.category_box.currentIndexChanged.connect(self.refresh)
        self.filters = FilterBar(db)
        self.filters.changed.connect(self.refresh)
        self.table = ComparisonTable()

        head = QHBoxLayout()
        head.addWidget(QLabel("Joueur:"))
        head.addWidget(self.player_box, 1)
        head.addWidget(QLabel("Grouper par:"))
        head.addWidget(self.group_box)
        head.addWidget(QLabel("Statistiques:"))
        head.addWidget(self.category_box)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.filters)
        layout.addWidget(self.table, 1)

    def reload_players(self) -> None:
        current = self.player_box.currentText()
        self.player_box.blockSignals(True)
        self.player_box.clear()
        for row in self.db.heroes():
            self.player_box.addItem(f"{row['name']} ({row['room']})", row["id"])
        for row in self.db.find_players("", limit=100):
            if not row["is_hero"]:
                self.player_box.addItem(f"{row['name']} ({row['room']})", row["id"])
        index = self.player_box.findText(current)
        if index >= 0:
            self.player_box.setCurrentIndex(index)
        self.player_box.blockSignals(False)
        self.filters.reload()
        self.refresh()

    def refresh(self) -> None:
        player_id = self.player_box.currentData()
        if player_id is None:
            return
        column, order = self.GROUPS[self.group_box.currentText()]
        groups = self.db.aggregate([player_id], self.filters.build(), group_by=column)
        groups = {str(k): v for k, v in groups.items()}
        category = self.category_box.currentText()
        codes = SUMMARY_CODES if category == "Resume" else [s.code for s in sd.by_category(category)]
        self.table.show_groups(groups, codes, self.group_box.currentText(), order)


class RangesTab(QWidget):
    """Grille de ranges et calculateur d'equite."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.grid = RangeGrid()
        self.grid.changed.connect(self._on_grid_changed)
        self.range_text = QLineEdit()
        self.range_text.setPlaceholderText("ex: 77+, AQs+, AKo  ou  15%")
        self.range_text.returnPressed.connect(self._on_text_changed)
        self.info = QLabel("")
        btn_clear = QPushButton("Effacer")
        btn_clear.clicked.connect(lambda: self.grid.set_weights({}))

        self.hero_cards = QLineEdit("AhKd")
        self.villain_range = QLineEdit("QQ+, AKs")
        self.board = QLineEdit("")
        self.board.setPlaceholderText("ex: Ks 7h 2c")
        self.iterations = QSpinBox()
        self.iterations.setRange(500, 200000)
        self.iterations.setValue(8000)
        self.iterations.setSingleStep(1000)
        btn_equity = QPushButton("Calculer l'equite")
        btn_equity.clicked.connect(self._compute)
        self.result = QLabel("")
        self.result.setStyleSheet("color:#cfd8e3;")
        self.result.setWordWrap(True)

        top = QHBoxLayout()
        top.addWidget(QLabel("Range:"))
        top.addWidget(self.range_text, 1)
        top.addWidget(btn_clear)

        calc = QGroupBox("Calculateur d'equite")
        form = QFormLayout(calc)
        form.addRow("Main du heros", self.hero_cards)
        form.addRow("Range adverse", self.villain_range)
        form.addRow("Board", self.board)
        form.addRow("Simulations", self.iterations)
        form.addRow(btn_equity)
        form.addRow(self.result)

        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(self.grid)
        left.addWidget(self.info)
        left.addStretch(1)
        left_widget = QWidget()
        left_widget.setLayout(left)

        layout = QHBoxLayout(self)
        layout.addWidget(left_widget)
        layout.addWidget(calc, 1)

    def _on_grid_changed(self) -> None:
        text = range_to_text(self.grid.weights)
        self.range_text.setText(text)
        self.info.setText(f"{len(self.grid.weights)} mains · "
                          f"{range_percent(self.grid.weights):.1f}% des combinaisons")
        self.villain_range.setText(text or "100%")

    def _on_text_changed(self) -> None:
        self.grid.set_weights(parse_range(self.range_text.text()))

    def _compute(self) -> None:
        from ..core.equity.cards import parse_cards
        hero = parse_cards(self.hero_cards.text())
        board = parse_cards(self.board.text())
        if len(hero) != 2:
            self.result.setText("Main du heros invalide.")
            return
        villain = self.villain_range.text().strip() or "100%"
        res = equity([hero, villain], board=board, iterations=self.iterations.value())
        eq = res.as_percent()
        self.result.setText(f"Heros <b>{eq[0]:.1f}%</b> · adversaire <b>{eq[1]:.1f}%</b> "
                            f"({res.iterations} simulations)")


class ImportTab(QWidget):
    """Configuration des dossiers d'historique et import."""

    imported = Signal(int)

    def __init__(self, db: Database, settings, watcher, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.watcher = watcher

        self.folders = QListWidget()
        self.folders.addItems(settings.hh_folders)
        btn_add = QPushButton("Ajouter un dossier...")
        btn_add.clicked.connect(self._add_folder)
        btn_remove = QPushButton("Retirer")
        btn_remove.clicked.connect(self._remove_folder)
        btn_detect = QPushButton("Detecter automatiquement")
        btn_detect.clicked.connect(self._detect)
        btn_import = QPushButton("Importer maintenant")
        btn_import.clicked.connect(self.run_import)

        self.auto_import = QCheckBox("Import automatique en temps reel (HUD)")
        self.auto_import.setChecked(settings.auto_import)
        self.auto_import.stateChanged.connect(self._toggle_auto)

        self.archive = QCheckBox("Archiver une copie des historiques importes")
        self.archive.setChecked(settings.archive_enabled)
        self.archive.setToolTip("Les rooms effacent leurs historiques au bout de quelques mois.\n"
                                "La copie permet de reconstruire la base a tout moment.")
        self.archive.stateChanged.connect(self._toggle_archive)
        self.archive_label = QLabel("")
        btn_archive_dir = QPushButton("Choisir le dossier d'archive...")
        btn_archive_dir.clicked.connect(self._choose_archive)
        archive_row = QHBoxLayout()
        archive_row.addWidget(self.archive)
        archive_row.addWidget(btn_archive_dir)
        archive_row.addWidget(self.archive_label, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)

        buttons = QHBoxLayout()
        for b in (btn_add, btn_remove, btn_detect, btn_import):
            buttons.addWidget(b)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dossiers d'historiques de mains"))
        layout.addWidget(self.folders)
        layout.addLayout(buttons)
        layout.addWidget(self.auto_import)
        layout.addLayout(archive_row)
        layout.addWidget(self.progress)
        layout.addWidget(QLabel("Journal"))
        layout.addWidget(self.log, 1)
        self.refresh_archive_label()

    # ------------------------------------------------------------------
    def _folders(self) -> List[str]:
        return [self.folders.item(i).text() for i in range(self.folders.count())]

    def _persist(self) -> None:
        self.settings.hh_folders = self._folders()
        self.settings.save()
        self.watcher.set_folders(self.settings.hh_folders)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier d'historiques")
        if folder:
            self.folders.addItem(folder)
            self._persist()

    def _remove_folder(self) -> None:
        row = self.folders.currentRow()
        if row >= 0:
            self.folders.takeItem(row)
            self._persist()

    def _detect(self) -> None:
        found = detect_hh_directories()
        existing = set(self._folders())
        for room, path in found.items():
            if path not in existing:
                self.folders.addItem(path)
                self.log.appendPlainText(f"{room}: {path}")
        if not found:
            self.log.appendPlainText("Aucun dossier connu trouve. Ajoutez-le manuellement.")
        self._persist()

    def _toggle_auto(self) -> None:
        self.settings.auto_import = self.auto_import.isChecked()
        self.settings.save()
        if self.settings.auto_import:
            self.watcher.set_folders(self._folders())
            self.watcher.start()
            self.log.appendPlainText("Surveillance temps reel activee.")
        else:
            self.watcher.stop()
            self.log.appendPlainText("Surveillance temps reel arretee.")

    def _toggle_archive(self) -> None:
        self.settings.archive_enabled = self.archive.isChecked()
        self.settings.save()
        self.watcher.archive_dir = self.settings.effective_archive_dir()
        self.refresh_archive_label()

    def _choose_archive(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier d'archive",
                                                  self.settings.archive_dir)
        if folder:
            self.settings.archive_dir = folder
            self.settings.save()
            self.watcher.archive_dir = self.settings.effective_archive_dir()
            self.refresh_archive_label()

    def refresh_archive_label(self) -> None:
        if not self.settings.archive_enabled:
            self.archive_label.setText("Archivage desactive.")
            return
        files, size = Importer(self.db, archive_dir=self.settings.archive_dir).archive_size()
        self.archive_label.setText(
            f"{self.settings.archive_dir}  —  {files} fichier(s), {size / 1e6:.1f} Mo")

    def run_import(self) -> None:
        folders = self._folders()
        if not folders:
            QMessageBox.warning(self, "Import", "Ajoutez d'abord un dossier d'historiques.")
            return
        importer = Importer(self.db, archive_dir=self.settings.effective_archive_dir())
        self.progress.setVisible(True)
        total = 0
        for folder in folders:
            files = list(Importer.iter_files(folder))
            self.progress.setMaximum(max(1, len(files)))
            for i, path in enumerate(files, start=1):
                result = importer.import_file(path)
                total += result.hands
                self.progress.setValue(i)
                if result.hands:
                    self.log.appendPlainText(f"{path.name}: {result.hands} mains")
                for err in result.errors:
                    self.log.appendPlainText(f"ERREUR {err}")
        self.progress.setVisible(False)
        self.log.appendPlainText(f"Import termine: {total} nouvelles mains.")
        self.refresh_archive_label()
        self.imported.emit(total)
