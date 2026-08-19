"""Onglet « Tournois & bankroll ».

Reunit le suivi financier des tournois (inscriptions, ITM, bulles, ROI,
gains) et la gestion de la bankroll (depots, retraits, resultats cash et
tournois cumules).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.db import Database, Filter
from .widgets import WinningsGraph

FORMAT_LABELS = {"mtt": "MTT", "sng": "Sit & Go", "spin": "Spin / Expresso", "cash": "Cash"}


class TournamentsTab(QWidget):
    """Bilan des tournois et de la bankroll."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.hero_box = QComboBox()
        self.hero_box.currentIndexChanged.connect(self.refresh)
        self.curve_box = QComboBox()
        self.curve_box.addItems(["Profit tournois", "Bankroll complete"])
        self.curve_box.currentIndexChanged.connect(self.refresh)

        from .tabs import FilterBar
        self.filters = FilterBar(db)
        self.filters.changed.connect(self.refresh)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.graph = WinningsGraph()
        self.graph.show_bb = False
        self.graph.show_ev = False

        self.tournaments = QTableWidget(0, 10)
        self.tournaments.setHorizontalHeaderLabels(
            ["Date", "Room", "Tournoi", "Format", "Buy-in", "Joueurs", "Place", "Gains",
             "Profit", "Mains"])
        self.tournaments.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tournaments.verticalHeader().setVisible(False)
        self.tournaments.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        self.by_format = QTableWidget(0, 7)
        self.by_format.setHorizontalHeaderLabels(
            ["Format", "Inscriptions", "Investi", "Profit", "ROI %", "ITM %", "Bulles"])
        self.by_format.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.by_format.verticalHeader().setVisible(False)

        # ---- bankroll
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 1_000_000)
        self.amount.setValue(100.0)
        self.kind = QComboBox()
        self.kind.addItems(["depot", "retrait", "ajustement"])
        self.note = QLineEdit()
        self.note.setPlaceholderText("note (facultatif)")
        btn_add = QPushButton("Enregistrer le mouvement")
        btn_add.clicked.connect(self._add_entry)
        btn_del = QPushButton("Supprimer la ligne")
        btn_del.clicked.connect(self._delete_entry)
        self.entries = QTableWidget(0, 4)
        self.entries.setHorizontalHeaderLabels(["Date", "Type", "Montant", "Note"])
        self.entries.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entries.verticalHeader().setVisible(False)
        self.entries.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.bankroll_label = QLabel("")
        self.bankroll_label.setWordWrap(True)

        bankroll_box = QGroupBox("Bankroll")
        form = QFormLayout(bankroll_box)
        form.addRow(self.bankroll_label)
        row = QHBoxLayout()
        row.addWidget(self.kind)
        row.addWidget(self.amount)
        row.addWidget(self.note, 1)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        form.addRow(row)
        form.addRow(self.entries)

        head = QHBoxLayout()
        head.addWidget(QLabel("Heros:"))
        head.addWidget(self.hero_box)
        head.addWidget(QLabel("Courbe:"))
        head.addWidget(self.curve_box)
        head.addStretch(1)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.summary)
        top_layout.addWidget(self.graph, 1)

        middle = QSplitter(Qt.Horizontal)
        middle.addWidget(self.tournaments)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Par format"))
        right_layout.addWidget(self.by_format)
        right_layout.addWidget(bankroll_box, 1)
        middle.addWidget(right)
        middle.setSizes([620, 560])

        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(middle)
        split.setSizes([320, 420])

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.filters)
        layout.addWidget(split, 1)

    # ------------------------------------------------------------------
    def reload_players(self) -> None:
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
        flt = self.filters.build()
        stats = self.db.tournament_stats(flt)
        currency = "€"
        self.summary.setText(
            f"<b>{stats['entries']}</b> inscriptions &nbsp;·&nbsp; investi "
            f"<b>{stats['cost']:.2f}{currency}</b> &nbsp;·&nbsp; gains "
            f"<b>{stats['won']:.2f}{currency}</b> &nbsp;·&nbsp; profit "
            f"<b>{stats['profit']:+.2f}{currency}</b> &nbsp;·&nbsp; ROI "
            f"<b>{stats['roi']:+.1f}%</b><br>"
            f"ITM <b>{stats['itm']}</b> ({stats['itm_pct']:.1f}%) &nbsp;·&nbsp; "
            f"bulles <b>{stats['bubbles']}</b> ({stats['bubble_pct']:.1f}%) &nbsp;·&nbsp; "
            f"victoires <b>{stats['wins']}</b> &nbsp;·&nbsp; buy-in moyen "
            f"<b>{stats['avg_buyin']:.2f}{currency}</b> &nbsp;·&nbsp; place moyenne "
            f"<b>{stats['avg_place_pct']:.0f}%</b> du champ &nbsp;·&nbsp; "
            f"meilleur resultat <b>{stats['best']:+.2f}{currency}</b>")

        hero_id = self.hero_box.currentData()
        if self.curve_box.currentIndex() == 0:
            self.graph.set_curve(self.db.tournament_curve(flt), currency)
        else:
            self.graph.set_curve(self.db.bankroll_timeline(hero_id), currency)

        rows = self.db.tournaments(flt)
        self.tournaments.setRowCount(len(rows))
        for i, row in enumerate(rows):
            place = f"{row['finish_place']}" if row["finish_place"] else "-"
            if row["bubble"]:
                place += " (bulle)"
            values = [
                (row["started_at"] or "").replace("T", " "),
                row["room"], row["name"] or row["tournament_id"],
                FORMAT_LABELS.get(row["fmt"], row["fmt"] or ""),
                f"{row['cost']:.2f}", str(row["entrants"] or "-"), place,
                f"{row['won']:.2f}", f"{row['profit']:+.2f}", str(row["hands_played"] or 0),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, row["id"])
                if col == 8:
                    item.setForeground(QColor("#5fd08a" if row["profit"] >= 0 else "#ff6b6b"))
                if col == 6 and row["itm"]:
                    item.setForeground(QColor("#5fd08a"))
                self.tournaments.setItem(i, col, item)
        self.tournaments.resizeColumnsToContents()

        groups = self.db.tournament_groups("fmt", flt)
        self.by_format.setRowCount(len(groups))
        for i, (name, data) in enumerate(sorted(groups.items())):
            values = [FORMAT_LABELS.get(name, name), str(data["entries"]),
                      f"{data['cost']:.2f}", f"{data['profit']:+.2f}",
                      f"{data['roi']:+.1f}", f"{data['itm_pct']:.1f}", str(data["bubbles"])]
            for col, value in enumerate(values):
                self.by_format.setItem(i, col, QTableWidgetItem(value))
        self.by_format.resizeColumnsToContents()
        self._refresh_bankroll()

    # ---------------------------------------------------------- bankroll
    def _refresh_bankroll(self) -> None:
        hero_id = self.hero_box.currentData()
        summary = self.db.bankroll_summary(hero_id)
        self.bankroll_label.setText(
            f"Bankroll actuelle: <b>{summary['total']:+.2f}</b> &nbsp;=&nbsp; mouvements "
            f"{summary['movements']:+.2f} &nbsp;+&nbsp; cash game {summary['cash']:+.2f} "
            f"&nbsp;+&nbsp; tournois {summary['tournaments']:+.2f}")
        rows = self.db.bankroll_entries()
        self.entries.setRowCount(len(rows))
        for i, row in enumerate(rows):
            amount = -row["amount"] if row["kind"] == "retrait" else row["amount"]
            values = [(row["date"] or "").replace("T", " "), row["kind"],
                      f"{amount:+.2f}", row["note"] or ""]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, row["id"])
                self.entries.setItem(i, col, item)
        self.entries.resizeColumnsToContents()

    def _add_entry(self) -> None:
        self.db.add_bankroll_entry(self.kind.currentText(), self.amount.value(),
                                   self.note.text(), datetime.now())
        self.note.clear()
        self.refresh()

    def _delete_entry(self) -> None:
        items = self.entries.selectedItems()
        if not items:
            QMessageBox.information(self, "Bankroll", "Selectionnez d'abord une ligne.")
            return
        self.db.delete_bankroll_entry(items[0].data(Qt.UserRole))
        self.refresh()
