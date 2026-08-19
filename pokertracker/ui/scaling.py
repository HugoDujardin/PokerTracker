"""Adaptation de l'interface a la police et au facteur d'echelle du systeme.

Windows 11 est souvent regle a 125 % ou 150 %: sans precaution, les libelles
des boutons et des listes deroulantes se retrouvent tronques. Ces fonctions
recalculent les largeurs minimales a partir des metriques reelles du texte.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QWidget)

#: marge horizontale ajoutee au texte d'un bouton (bordures + remplissage)
BUTTON_PADDING = 30
COMBO_PADDING = 38


def fit_button(button: QPushButton, *alternatives: str) -> None:
    """Donne au bouton une largeur suffisante pour son texte.

    `alternatives` permet de reserver la place des libelles que le bouton
    prendra plus tard (par exemple « Pause » pour un bouton « Lecture »).
    """
    metrics = button.fontMetrics()
    widest = max([metrics.horizontalAdvance(t) for t in (button.text(), *alternatives) if t] or [0])
    button.setMinimumWidth(max(button.minimumWidth(), widest + BUTTON_PADDING))


def fit_combo(combo: QComboBox) -> None:
    combo.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
    metrics = combo.fontMetrics()
    widest = max([metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())]
                 or [metrics.horizontalAdvance(combo.currentText())])
    combo.setMinimumWidth(max(combo.minimumWidth(), min(widest + COMBO_PADDING, 420)))


def fit_table(table: QTableWidget) -> None:
    header = table.horizontalHeader()
    header.setMinimumSectionSize(max(40, table.fontMetrics().horizontalAdvance("00000")))
    table.setTextElideMode(table.textElideMode())
    table.setWordWrap(False)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)


def fit_widgets(root: QWidget) -> None:
    """Applique les ajustements a toute une hierarchie de widgets."""
    for button in root.findChildren(QPushButton):
        fit_button(button)
    for combo in root.findChildren(QComboBox):
        fit_combo(combo)
    for table in root.findChildren(QTableWidget):
        fit_table(table)
    for label in root.findChildren(QLabel):
        if label.wordWrap():
            label.setMinimumHeight(label.sizeHint().height())
