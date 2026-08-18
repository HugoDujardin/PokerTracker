"""Editeur de profils HUD.

Permet de composer les panneaux (lignes de statistiques), leurs conditions
d'affichage (HUD dynamique) et leurs couleurs, puis de sauvegarder le
profil dans la base.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.db import Database
from ..core.stats import definitions as sd
from ..hud.profile import (BUILTIN_PROFILES, ColorRule, HudPanel, HudProfile, PanelCondition,
                           StatCell, default_profile)

POSITIONS = ["UTG", "UTG1", "UTG2", "MP", "MP1", "HJ", "CO", "BTN", "SB", "BB"]


class HudEditor(QWidget):
    """Editeur complet d'un profil HUD."""

    profile_changed = Signal(object)

    def __init__(self, db: Database, profile: Optional[HudProfile] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.profile = profile or default_profile()
        self._build_ui()
        self.reload_profiles()
        self.load_profile(self.profile)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.profile_box = QComboBox()
        self.profile_box.currentTextChanged.connect(self._on_profile_selected)
        btn_new = QPushButton("Nouveau")
        btn_new.clicked.connect(self._new_profile)
        btn_save = QPushButton("Enregistrer")
        btn_save.clicked.connect(self.save_profile)
        btn_export = QPushButton("Exporter JSON")
        btn_export.clicked.connect(self._export)

        top = QHBoxLayout()
        top.addWidget(QLabel("Profil:"))
        top.addWidget(self.profile_box, 1)
        top.addWidget(btn_new)
        top.addWidget(btn_save)
        top.addWidget(btn_export)

        # ---- panneaux
        self.panel_list = QListWidget()
        self.panel_list.currentRowChanged.connect(self._on_panel_selected)
        btn_add_panel = QPushButton("+ panneau")
        btn_add_panel.clicked.connect(self._add_panel)
        btn_del_panel = QPushButton("- panneau")
        btn_del_panel.clicked.connect(self._del_panel)
        btn_up = QPushButton("↑")
        btn_up.clicked.connect(lambda: self._move_panel(-1))
        btn_down = QPushButton("↓")
        btn_down.clicked.connect(lambda: self._move_panel(1))
        panel_buttons = QHBoxLayout()
        for b in (btn_add_panel, btn_del_panel, btn_up, btn_down):
            panel_buttons.addWidget(b)
        left = QVBoxLayout()
        left.addWidget(QLabel("Panneaux (le premier dont la condition est vraie est affiche)"))
        left.addWidget(self.panel_list, 1)
        left.addLayout(panel_buttons)
        left_widget = QWidget()
        left_widget.setLayout(left)

        # ---- conditions
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._apply_panel_fields)
        self.scope_box = QComboBox()
        self.scope_box.addItems(["all", "position"])
        self.scope_box.currentTextChanged.connect(self._apply_panel_fields)
        self.positions_edit = QLineEdit()
        self.positions_edit.setPlaceholderText("ex: SB, BB (vide = toutes)")
        self.positions_edit.editingFinished.connect(self._apply_panel_fields)
        self.min_players = QSpinBox(); self.min_players.setRange(0, 10)
        self.max_players = QSpinBox(); self.max_players.setRange(0, 10)
        self.min_hands = QSpinBox(); self.min_hands.setRange(0, 100000)
        self.min_stack = QDoubleSpinBox(); self.min_stack.setRange(0, 1000)
        self.max_stack = QDoubleSpinBox(); self.max_stack.setRange(0, 1000)
        for w in (self.min_players, self.max_players, self.min_hands):
            w.valueChanged.connect(self._apply_panel_fields)
        for w in (self.min_stack, self.max_stack):
            w.valueChanged.connect(self._apply_panel_fields)

        cond_box = QGroupBox("Condition d'affichage (HUD dynamique)")
        form = QFormLayout(cond_box)
        form.addRow("Nom du panneau", self.name_edit)
        form.addRow("Statistiques filtrees sur", self.scope_box)
        form.addRow("Positions", self.positions_edit)
        form.addRow("Joueurs min / max", self._pair(self.min_players, self.max_players))
        form.addRow("Tapis min / max (bb)", self._pair(self.min_stack, self.max_stack))
        form.addRow("Mains minimum", self.min_hands)

        # ---- grille de stats
        self.cells = QTableWidget(0, 6)
        self.cells.setHorizontalHeaderLabels(["Ligne", "Statistique", "Libelle", "Ech. min",
                                              "Seuil bas", "Seuil haut"])
        self.cells.itemChanged.connect(self._on_cell_edited)
        btn_add_cell = QPushButton("+ statistique")
        btn_add_cell.clicked.connect(self._add_cell)
        btn_del_cell = QPushButton("- statistique")
        btn_del_cell.clicked.connect(self._del_cell)
        self.stat_picker = QComboBox()
        for stat in sd.STATS:
            self.stat_picker.addItem(f"{stat.label}  ({stat.code})", stat.code)
        cell_buttons = QHBoxLayout()
        cell_buttons.addWidget(self.stat_picker, 1)
        cell_buttons.addWidget(btn_add_cell)
        cell_buttons.addWidget(btn_del_cell)

        right = QVBoxLayout()
        right.addWidget(cond_box)
        right.addWidget(QLabel("Statistiques du panneau"))
        right.addWidget(self.cells, 1)
        right.addLayout(cell_buttons)
        right_widget = QWidget()
        right_widget.setLayout(right)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left_widget)
        split.addWidget(right_widget)
        split.setSizes([220, 620])

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(split, 1)

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(a)
        lay.addWidget(b)
        return box

    # -------------------------------------------------------------- profils
    def reload_profiles(self) -> None:
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        names = list(BUILTIN_PROFILES)
        for name in self.db.load_profiles():
            if name not in names:
                names.append(name)
        self.profile_box.addItems(names)
        if self.profile.name in names:
            self.profile_box.setCurrentText(self.profile.name)
        self.profile_box.blockSignals(False)

    def _on_profile_selected(self, name: str) -> None:
        saved = self.db.load_profiles()
        if name in saved:
            self.load_profile(HudProfile.from_json(saved[name]))
        elif name in BUILTIN_PROFILES:
            self.load_profile(HudProfile.from_json(BUILTIN_PROFILES[name].to_json()))

    def load_profile(self, profile: HudProfile) -> None:
        self.profile = profile
        self.panel_list.clear()
        for panel in profile.panels:
            self.panel_list.addItem(QListWidgetItem(panel.name))
        if profile.panels:
            self.panel_list.setCurrentRow(0)
        self.profile_changed.emit(profile)

    def save_profile(self) -> None:
        self.db.save_profile(self.profile.name, self.profile.to_json())
        self.reload_profiles()
        self.profile_changed.emit(self.profile)
        QMessageBox.information(self, "HUD", f"Profil « {self.profile.name} » enregistre.")

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Nouveau profil", "Nom du profil:")
        if not ok or not name.strip():
            return
        profile = default_profile()
        profile.name = name.strip()
        self.db.save_profile(profile.name, profile.to_json())
        self.reload_profiles()
        self.profile_box.setCurrentText(profile.name)
        self.load_profile(profile)

    def _export(self) -> None:
        QMessageBox.information(self, "Profil HUD", self.profile.to_json()[:4000])

    # -------------------------------------------------------------- panneaux
    def current_panel(self) -> Optional[HudPanel]:
        row = self.panel_list.currentRow()
        if 0 <= row < len(self.profile.panels):
            return self.profile.panels[row]
        return None

    def _on_panel_selected(self, row: int) -> None:
        panel = self.current_panel()
        if panel is None:
            return
        blockers = [self.name_edit, self.scope_box, self.positions_edit, self.min_players,
                    self.max_players, self.min_hands, self.min_stack, self.max_stack]
        for w in blockers:
            w.blockSignals(True)
        self.name_edit.setText(panel.name)
        self.scope_box.setCurrentText(panel.scope)
        self.positions_edit.setText(", ".join(panel.condition.positions))
        self.min_players.setValue(panel.condition.min_players)
        self.max_players.setValue(panel.condition.max_players)
        self.min_hands.setValue(panel.condition.min_hands)
        self.min_stack.setValue(panel.condition.min_stack_bb)
        self.max_stack.setValue(panel.condition.max_stack_bb)
        for w in blockers:
            w.blockSignals(False)
        self._fill_cells(panel)

    def _apply_panel_fields(self) -> None:
        panel = self.current_panel()
        if panel is None:
            return
        panel.name = self.name_edit.text().strip() or panel.name
        panel.scope = self.scope_box.currentText()
        panel.condition = PanelCondition(
            positions=[p.strip().upper() for p in self.positions_edit.text().split(",") if p.strip()],
            min_players=self.min_players.value(),
            max_players=self.max_players.value(),
            min_hands=self.min_hands.value(),
            min_stack_bb=self.min_stack.value(),
            max_stack_bb=self.max_stack.value(),
        )
        row = self.panel_list.currentRow()
        if 0 <= row < self.panel_list.count():
            self.panel_list.item(row).setText(panel.name)
        self.profile_changed.emit(self.profile)

    def _add_panel(self) -> None:
        panel = HudPanel(name=f"Panneau {len(self.profile.panels) + 1}",
                         rows=[[StatCell("hands"), StatCell("vpip"), StatCell("pfr")]])
        self.profile.panels.insert(0, panel)
        self.load_profile(self.profile)

    def _del_panel(self) -> None:
        row = self.panel_list.currentRow()
        if 0 <= row < len(self.profile.panels) and len(self.profile.panels) > 1:
            self.profile.panels.pop(row)
            self.load_profile(self.profile)

    def _move_panel(self, delta: int) -> None:
        row = self.panel_list.currentRow()
        new = row + delta
        if 0 <= row < len(self.profile.panels) and 0 <= new < len(self.profile.panels):
            panels = self.profile.panels
            panels[row], panels[new] = panels[new], panels[row]
            self.load_profile(self.profile)
            self.panel_list.setCurrentRow(new)

    # ------------------------------------------------------------ cellules
    def _fill_cells(self, panel: HudPanel) -> None:
        self.cells.blockSignals(True)
        rows = [(r, cell) for r, row in enumerate(panel.rows) for cell in row]
        self.cells.setRowCount(len(rows))
        for i, (line, cell) in enumerate(rows):
            stat = cell.definition()
            low = next((c.value for c in cell.colors if c.op == "<"), 0)
            high = next((c.value for c in cell.colors if c.op == ">"), 0)
            values = [str(line + 1), f"{stat.label if stat else cell.code} ({cell.code})",
                      cell.label, str(cell.min_sample), f"{low:g}", f"{high:g}"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 1:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.cells.setItem(i, col, item)
        self.cells.resizeColumnsToContents()
        self.cells.blockSignals(False)

    def _cells_flat(self, panel: HudPanel) -> List[StatCell]:
        return [cell for row in panel.rows for cell in row]

    def _on_cell_edited(self, item: QTableWidgetItem) -> None:
        panel = self.current_panel()
        if panel is None:
            return
        flat = self._cells_flat(panel)
        if item.row() >= len(flat):
            return
        cell = flat[item.row()]
        text = item.text().strip()
        try:
            if item.column() == 0:
                self._move_cell_to_line(panel, cell, max(1, int(text or 1)) - 1)
            elif item.column() == 2:
                cell.label = text
            elif item.column() == 3:
                cell.min_sample = int(text or 0)
            elif item.column() in (4, 5):
                value = float(text or 0)
                op = "<" if item.column() == 4 else ">"
                cell.colors = [c for c in cell.colors if c.op != op]
                if value:
                    color = "#5fb3ff" if op == "<" else "#ff6b6b"
                    cell.colors.append(ColorRule(op, value, 0, color))
        except ValueError:
            pass
        self.profile_changed.emit(self.profile)

    def _move_cell_to_line(self, panel: HudPanel, cell: StatCell, line: int) -> None:
        for row in panel.rows:
            if cell in row:
                row.remove(cell)
        while len(panel.rows) <= line:
            panel.rows.append([])
        panel.rows[line].append(cell)
        panel.rows[:] = [r for r in panel.rows if r] or [[cell]]
        self._fill_cells(panel)

    def _add_cell(self) -> None:
        panel = self.current_panel()
        if panel is None:
            return
        code = self.stat_picker.currentData()
        if not panel.rows:
            panel.rows.append([])
        panel.rows[-1].append(StatCell(code))
        self._fill_cells(panel)
        self.profile_changed.emit(self.profile)

    def _del_cell(self) -> None:
        panel = self.current_panel()
        row = self.cells.currentRow()
        if panel is None or row < 0:
            return
        flat = self._cells_flat(panel)
        if row >= len(flat):
            return
        cell = flat[row]
        for line in panel.rows:
            if cell in line:
                line.remove(cell)
        panel.rows[:] = [r for r in panel.rows if r]
        self._fill_cells(panel)
        self.profile_changed.emit(self.profile)
