"""Table de demonstration.

Fenetre qui imite une table de poker: elle sert a verifier et a regler le
HUD (position des panneaux, couleurs, popups) sans avoir a ouvrir une vraie
table dans un client de poker.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..hud.seatmap import layout_for
from ..hud.table_tracker import TableWindow


class DemoTable(QWidget):
    """Fausse table, reconnue par le HUD comme une table reelle."""

    def __init__(self, room: str = "PokerStars", table_name: str = "Aludra II",
                 seats: int = 6, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.room = room
        self.table_name = table_name
        self.seats = seats
        self.setWindowTitle(f"{table_name} - $0.25/$0.50 USD - No Limit Hold'em  [demo]")
        self.resize(900, 620)
        self.setStyleSheet("background:#0f1319;")

    def as_table_window(self) -> List[TableWindow]:
        """Expose la fenetre au `TableTracker` du HUD."""
        if not self.isVisible():
            return []
        top_left = self.mapToGlobal(self.rect().topLeft())
        return [TableWindow(handle=int(self.winId()), title=self.windowTitle(),
                            x=top_left.x(), y=top_left.y(), width=self.width(),
                            height=self.height(), room=self.room,
                            table_name=self.table_name, max_seats=self.seats)]

    def paintEvent(self, event) -> None:  # pragma: no cover - rendu
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.setBrush(QBrush(QColor("#1d4c34")))
        painter.setPen(QPen(QColor("#0d2a1d"), 8))
        painter.drawEllipse(QRectF(w * 0.10, h * 0.14, w * 0.80, h * 0.66))
        painter.setPen(QColor("#cfd8e3"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(0, h * 0.44, w, 24), Qt.AlignCenter,
                         f"{self.table_name} — table de demonstration")
        painter.setFont(QFont("Segoe UI", 8))
        for i, (rx, ry) in enumerate(layout_for(self.seats), start=1):
            rect = QRectF(w * rx, h * ry, 120, 34)
            painter.setBrush(QColor("#232b35"))
            painter.setPen(QPen(QColor("#3a4250"), 1))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#9fb0c2"))
            painter.drawText(rect, Qt.AlignCenter, f"siege {i}")
