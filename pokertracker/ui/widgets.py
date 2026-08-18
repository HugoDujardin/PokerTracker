"""Composants graphiques reutilisables."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QHeaderView, QLabel, QSizePolicy, QTableWidget, QTableWidgetItem,
                               QWidget)

from ..core.equity.cards import SUIT_COLORS, SUIT_SYMBOLS
from ..core.equity.ranges import GRID, nb_combos
from ..core.stats import definitions as sd

DARK_BG = "#12161c"
GRID_COLOR = "#2a323d"
LINE_COLOR = "#4da3ff"
LINE_COLOR_2 = "#f0a848"


class WinningsGraph(QWidget):
    """Courbe de gains cumules (argent et grosses blindes)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.points: List[Tuple[int, float, float]] = []      # (main, cumul argent, cumul bb)
        self.currency = "€"
        self.show_bb = True
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_curve(self, curve: Sequence[Tuple[int, float, float, float]], currency: str = "€") -> None:
        self.points = [(int(i), float(money), float(bb)) for i, _ts, money, bb in curve]
        self.currency = currency
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - rendu
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(48, 12, -12, -24)
        painter.fillRect(self.rect(), QColor(DARK_BG))
        painter.setPen(QPen(QColor(GRID_COLOR), 1))
        for i in range(5):
            y = rect.top() + i * rect.height() / 4
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        if len(self.points) < 2:
            painter.setPen(QColor("#7b8794"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Pas encore de donnees")
            return

        values = [p[2] if self.show_bb else p[1] for p in self.points]
        vmin, vmax = min(values + [0.0]), max(values + [0.0])
        span = (vmax - vmin) or 1.0
        n = len(values)

        def to_xy(i: int, v: float) -> QPointF:
            x = rect.left() + rect.width() * i / max(1, n - 1)
            y = rect.bottom() - rect.height() * (v - vmin) / span
            return QPointF(x, y)

        zero_y = to_xy(0, 0.0).y()
        painter.setPen(QPen(QColor("#556070"), 1, Qt.DashLine))
        painter.drawLine(QPointF(rect.left(), zero_y), QPointF(rect.right(), zero_y))

        poly = QPolygonF([to_xy(i, v) for i, v in enumerate(values)])
        area = QPolygonF(poly)
        area.append(QPointF(rect.right(), zero_y))
        area.append(QPointF(rect.left(), zero_y))
        color = QColor(LINE_COLOR if values[-1] >= 0 else "#ff6b6b")
        fill = QColor(color)
        fill.setAlpha(48)
        painter.setBrush(QBrush(fill))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(area)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, 2))
        painter.drawPolyline(poly)

        painter.setPen(QColor("#93a3b5"))
        painter.setFont(QFont("Segoe UI", 8))
        unit = "bb" if self.show_bb else self.currency
        for i in range(5):
            v = vmax - i * span / 4
            y = rect.top() + i * rect.height() / 4
            painter.drawText(QRectF(0, y - 8, 44, 16), Qt.AlignRight | Qt.AlignVCenter,
                             f"{v:,.0f}{unit}")
        painter.drawText(QRectF(rect.left(), rect.bottom() + 4, rect.width(), 18),
                         Qt.AlignLeft, "1 main")
        painter.drawText(QRectF(rect.left(), rect.bottom() + 4, rect.width(), 18),
                         Qt.AlignRight, f"{n} mains")


class RangeGrid(QWidget):
    """Grille 13x13 des mains de depart, editable a la souris."""

    changed = Signal()

    CELL = 30

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.weights: Dict[str, float] = {}
        self.editable = True
        self._painting_value: Optional[float] = None
        self.setMinimumSize(self.CELL * 13 + 2, self.CELL * 13 + 2)
        self.setMouseTracking(True)

    def set_weights(self, weights: Dict[str, float]) -> None:
        self.weights = dict(weights)
        self.update()
        self.changed.emit()

    def cell_at(self, x: int, y: int) -> Optional[str]:
        col = int(x // self.CELL)
        row = int(y // self.CELL)
        if 0 <= row < 13 and 0 <= col < 13:
            return GRID[row][col]
        return None

    def mousePressEvent(self, event) -> None:  # pragma: no cover - interaction
        if not self.editable:
            return
        code = self.cell_at(event.position().x(), event.position().y())
        if code:
            self._painting_value = 0.0 if self.weights.get(code, 0) else 1.0
            self._apply(code)

    def mouseMoveEvent(self, event) -> None:  # pragma: no cover - interaction
        if self._painting_value is None:
            return
        code = self.cell_at(event.position().x(), event.position().y())
        if code:
            self._apply(code)

    def mouseReleaseEvent(self, event) -> None:  # pragma: no cover - interaction
        self._painting_value = None

    def _apply(self, code: str) -> None:
        if self._painting_value:
            self.weights[code] = self._painting_value
        else:
            self.weights.pop(code, None)
        self.update()
        self.changed.emit()

    def paintEvent(self, event) -> None:  # pragma: no cover - rendu
        painter = QPainter(self)
        painter.setFont(QFont("Segoe UI", 7))
        for r, row in enumerate(GRID):
            for c, code in enumerate(row):
                rect = QRectF(c * self.CELL, r * self.CELL, self.CELL - 1, self.CELL - 1)
                weight = self.weights.get(code, 0.0)
                if weight:
                    base = QColor("#2f7d4f") if r == c else (
                        QColor("#2b5f8f") if code.endswith("s") else QColor("#7a4a2c"))
                    base.setAlphaF(0.35 + 0.65 * min(1.0, weight))
                    painter.fillRect(rect, base)
                else:
                    painter.fillRect(rect, QColor("#191e25"))
                painter.setPen(QColor("#2a323d"))
                painter.drawRect(rect)
                painter.setPen(QColor("#d8dee6" if weight else "#78828f"))
                painter.drawText(rect, Qt.AlignCenter, code)


class CardsLabel(QLabel):
    """Affiche des cartes en couleur ('Ah Kd')."""

    def __init__(self, cards: Sequence[str] = (), size: int = 13,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.size_pt = size
        self.set_cards(cards)

    def set_cards(self, cards: Sequence[str]) -> None:
        parts = []
        for card in cards:
            if len(card) != 2:
                continue
            suit = card[1].lower()
            color = SUIT_COLORS.get(suit, "#dddddd")
            parts.append(f"<span style='color:{color}'>{card[0].upper()}"
                         f"{SUIT_SYMBOLS.get(suit, suit)}</span>")
        self.setText(f"<span style='font-size:{self.size_pt}pt'>" + " ".join(parts) + "</span>")


class StatsTable(QTableWidget):
    """Tableau de statistiques (une ligne par stat, valeur + echantillon)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["Statistique", "Valeur", "Echantillon", "Description"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

    def show_stats(self, agg: dict, codes: Sequence[str] = ()) -> None:
        stats = [sd.get(c) for c in codes] if codes else sd.STATS
        stats = [s for s in stats if s]
        self.setRowCount(len(stats))
        for row, stat in enumerate(stats):
            self.setItem(row, 0, QTableWidgetItem(stat.label))
            value_item = QTableWidgetItem(stat.format(agg))
            value_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, 1, value_item)
            sample_item = QTableWidgetItem(str(stat.sample(agg)))
            sample_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, 2, sample_item)
            self.setItem(row, 3, QTableWidgetItem(stat.description))


class ComparisonTable(QTableWidget):
    """Tableau croise: une ligne par groupe (position, limite...), une
    colonne par statistique."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)

    def show_groups(self, groups: Dict[str, dict], codes: Sequence[str],
                    group_label: str = "Groupe", order: Sequence[str] = ()) -> None:
        stats = [sd.get(c) for c in codes]
        stats = [s for s in stats if s]
        keys = [k for k in order if k in groups] or sorted(groups)
        self.setColumnCount(1 + len(stats))
        self.setHorizontalHeaderLabels([group_label] + [s.label for s in stats])
        self.setRowCount(len(keys))
        for row, key in enumerate(keys):
            agg = groups[key]
            self.setItem(row, 0, QTableWidgetItem(str(key or "-")))
            for col, stat in enumerate(stats, start=1):
                item = QTableWidgetItem(stat.format(agg))
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(f"{stat.label}: {stat.description}\nEchantillon: {stat.sample(agg)}")
                self.setItem(row, col, item)
        self.resizeColumnsToContents()
