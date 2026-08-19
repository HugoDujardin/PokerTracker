"""Replayer de mains: rejoue une main action par action."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..core.equity.cards import CARD_COLORS, SUIT_COLORS, SUIT_SYMBOLS
from ..core.equity.equity import equity
from ..core.models import Action, ActionType, Hand, Street
from ..core.parsers import registry
from ..hud.seatmap import layout_for

ACTION_LABELS = {
    ActionType.FOLD: "se couche",
    ActionType.CHECK: "check",
    ActionType.CALL: "suit",
    ActionType.BET: "mise",
    ActionType.RAISE: "relance a",
    ActionType.POST_SB: "petite blinde",
    ActionType.POST_BB: "grosse blinde",
    ActionType.POST_ANTE: "ante",
    ActionType.POST_STRADDLE: "straddle",
    ActionType.POST_DEAD: "blinde morte",
    ActionType.SHOW: "abat",
    ActionType.MUCK: "jette",
    ActionType.COLLECT: "encaisse",
    ActionType.UNCALLED: "recupere",
}


@dataclass
class Frame:
    """Etat de la table apres une action."""
    street: Street
    board: List[str]
    pot: Decimal
    stacks: Dict[str, Decimal]
    bets: Dict[str, Decimal]
    folded: set
    action: Optional[Action] = None
    text: str = ""


def build_frames(hand: Hand) -> List[Frame]:
    stacks = {s.player: s.stack for s in hand.seats}
    bets: Dict[str, Decimal] = {}
    folded: set = set()
    pot = Decimal(0)
    street = Street.PREFLOP
    frames = [Frame(street, [], pot, dict(stacks), {}, set(), None, "Distribution des cartes")]
    for action in hand.actions:
        if action.street != street and action.type not in (ActionType.COLLECT, ActionType.UNCALLED):
            street = action.street
            pot += sum(bets.values())
            bets = {}
            frames.append(Frame(street, hand.board_of(street), pot, dict(stacks), {}, set(folded),
                                None, f"--- {street.value.upper()} ---"))
        if action.type == ActionType.FOLD:
            folded.add(action.player)
        elif action.type in (ActionType.COLLECT, ActionType.UNCALLED):
            stacks[action.player] = stacks.get(action.player, Decimal(0)) + action.amount
        elif action.amount:
            stacks[action.player] = stacks.get(action.player, Decimal(0)) - action.amount
            bets[action.player] = bets.get(action.player, Decimal(0)) + action.amount
        label = ACTION_LABELS.get(action.type, action.type.value)
        amount = ""
        if action.type in (ActionType.RAISE,):
            amount = f" {action.to_amount}"
        elif action.amount:
            amount = f" {action.amount}"
        text = f"{action.player} {label}{amount}" + (" (all-in)" if action.allin else "")
        frames.append(Frame(street, hand.board_of(street) if street != Street.SHOWDOWN else hand.board,
                            pot + sum(bets.values()), dict(stacks), dict(bets), set(folded),
                            action, text))
    return frames


class TableCanvas(QWidget):
    """Dessin de la table et des joueurs."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.hand: Optional[Hand] = None
        self.frame: Optional[Frame] = None
        self.equities: Dict[str, float] = {}
        self.setMinimumHeight(340)

    def set_hand(self, hand: Optional[Hand], frame: Optional[Frame]) -> None:
        self.hand = hand
        self.frame = frame
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # pragma: no cover - rendu
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#12161c"))
        if not self.hand or not self.frame:
            painter.setPen(QColor("#7b8794"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Selectionnez une main")
            return

        w, h = self.width(), self.height()
        table_rect = QRectF(w * 0.22, h * 0.24, w * 0.56, h * 0.50)
        painter.setBrush(QBrush(QColor("#1d4c34")))
        painter.setPen(QPen(QColor("#0d2a1d"), 6))
        painter.drawEllipse(table_rect)

        # board + pot
        painter.setFont(QFont("Segoe UI", 13, QFont.Bold))
        x = table_rect.center().x() - 15 * len(self.frame.board)
        y = table_rect.center().y() - 22
        for card in self.frame.board:
            rect = QRectF(x, y, 26, 36)
            painter.setBrush(QColor("#f2f3f5"))
            painter.setPen(QPen(QColor("#0b0d10"), 1))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(CARD_COLORS.get(card[1].lower(), "#111")))
            painter.drawText(rect, Qt.AlignCenter,
                             f"{card[0].upper()}{SUIT_SYMBOLS.get(card[1].lower(), '')}")
            x += 30
        painter.setPen(QColor("#e8e8ea"))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(QRectF(table_rect.left(), table_rect.center().y() + 26,
                                table_rect.width(), 22), Qt.AlignCenter,
                         f"Pot: {self.frame.pot} {self.hand.currency}")

        seats = sorted(self.hand.seats, key=lambda s: s.seat_no)
        hero_idx = next((i for i, s in enumerate(seats) if s.is_hero), 0)
        n = len(seats)
        box_w, box_h = 148, 50
        cx, cy = table_rect.center().x(), table_rect.center().y()
        rx, ry = table_rect.width() * 0.52, table_rect.height() * 0.62
        for i, seat in enumerate(seats):
            # le heros est place en bas, les autres tournent dans le sens horaire
            angle = math.pi / 2 + 2 * math.pi * ((i - hero_idx) % n) / n
            px = cx + rx * math.cos(angle) - box_w / 2
            py = cy + ry * math.sin(angle) - box_h / 2
            px = max(2, min(px, w - box_w - 2))
            py = max(2, min(py, h - box_h - 2))
            box = QRectF(px, py, box_w, box_h)
            active = self.frame.action and self.frame.action.player == seat.player
            folded = seat.player in self.frame.folded
            painter.setBrush(QColor("#232b35") if not active else QColor("#2f4b63"))
            painter.setPen(QPen(QColor("#4da3ff" if active else "#3a4250"), 2 if active else 1))
            painter.drawRoundedRect(box, 6, 6)
            painter.setPen(QColor("#8b97a6" if folded else "#e6e6e6"))
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold if seat.is_hero else QFont.Normal))
            name = seat.player[:13] + (" (BTN)" if seat.is_button else "")
            painter.drawText(QRectF(box.left() + 6, box.top() + 2, box_w - 10, 16),
                             Qt.AlignLeft | Qt.AlignVCenter, name)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#a8b4c2"))
            stack = self.frame.stacks.get(seat.player, seat.stack)
            info = f"{seat.position}  {stack}"
            eq = self.equities.get(seat.player)
            if eq is not None and not folded:
                info += f"  ·  {eq:.0f}%"
            painter.drawText(QRectF(box.left() + 6, box.top() + 17, box_w - 10, 14),
                             Qt.AlignLeft | Qt.AlignVCenter, info)
            # cartes du joueur
            cardx = box.left() + 6
            for card in seat.cards:
                rect = QRectF(cardx, box.top() + 32, 17, 16)
                painter.setBrush(QColor("#f2f3f5"))
                painter.setPen(QPen(QColor("#0b0d10"), 1))
                painter.drawRoundedRect(rect, 2, 2)
                painter.setPen(QColor(CARD_COLORS.get(card[1].lower(), "#111")))
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                painter.drawText(rect, Qt.AlignCenter,
                                 f"{card[0].upper()}{SUIT_SYMBOLS.get(card[1].lower(), '')}")
                cardx += 19
            bet = self.frame.bets.get(seat.player)
            if bet:
                painter.setPen(QColor("#f0c848"))
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                painter.drawText(QRectF(box.left() + 62, box.top() + 32, box_w - 66, 16),
                                 Qt.AlignRight | Qt.AlignVCenter, f"mise {bet}")


class Replayer(QWidget):
    """Replayer complet avec controles et calcul d'equite."""

    hand_changed = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.hand: Optional[Hand] = None
        self.frames: List[Frame] = []
        self.index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.next_step)

        self.canvas = TableCanvas(self)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#c8d2de; padding:4px;")
        self.info.setWordWrap(True)
        self.history = QLabel("")
        self.history.setStyleSheet("color:#8b97a6; padding:2px 6px;")
        self.history.setWordWrap(True)

        controls = QHBoxLayout()
        self.btn_first = QPushButton("|<")
        self.btn_prev = QPushButton("<")
        self.btn_play = QPushButton("Lecture")
        self.btn_next = QPushButton(">")
        self.btn_last = QPushButton(">|")
        self.btn_equity = QPushButton("Calculer l'equite")
        for b in (self.btn_first, self.btn_prev, self.btn_play, self.btn_next, self.btn_last):
            # largeur deduite du texte: rien n'est jamais tronque, quelle que
            # soit la police ou la mise a l'echelle de l'ecran
            b.setMinimumWidth(b.fontMetrics().horizontalAdvance(b.text()) + 28)
            b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            controls.addWidget(b)
        controls.addWidget(self.btn_equity)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.info)
        layout.addLayout(controls)
        layout.addWidget(self.history)

        self.btn_first.clicked.connect(lambda: self.goto(0))
        self.btn_prev.clicked.connect(self.prev_step)
        self.btn_next.clicked.connect(self.next_step)
        self.btn_last.clicked.connect(lambda: self.goto(len(self.frames) - 1))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_equity.clicked.connect(self.compute_equity)

    # ------------------------------------------------------------------
    def load_raw(self, raw_text: str) -> bool:
        hands = list(registry.parse_text(raw_text))
        if not hands:
            return False
        self.load_hand(hands[0])
        return True

    def load_hand(self, hand: Hand) -> None:
        self.hand = hand
        self.frames = build_frames(hand)
        self.canvas.equities = {}
        self.goto(0)
        self.hand_changed.emit(hand)

    def goto(self, index: int) -> None:
        if not self.frames:
            self.canvas.set_hand(None, None)
            self.info.setText("")
            return
        self.index = max(0, min(index, len(self.frames) - 1))
        frame = self.frames[self.index]
        self.canvas.set_hand(self.hand, frame)
        if self.hand:
            self.info.setText(
                f"{self.hand.room} · {self.hand.table_name} · {self.hand.played_at:%d/%m/%Y %H:%M} · "
                f"{self.hand.sb}/{self.hand.bb} {self.hand.currency}   —   "
                f"etape {self.index + 1}/{len(self.frames)} : {frame.text}")
        self.history.setText(" | ".join(f.text for f in self.frames[:self.index + 1]))

    def next_step(self) -> None:
        if self.index >= len(self.frames) - 1:
            self._timer.stop()
            self.btn_play.setText("Lecture")
            return
        self.goto(self.index + 1)

    def prev_step(self) -> None:
        self.goto(self.index - 1)

    def toggle_play(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.btn_play.setText("Lecture")
        else:
            self._timer.start(900)
            self.btn_play.setText("Pause")

    # ------------------------------------------------------------------
    def compute_equity(self) -> None:
        """Equite des joueurs encore en jeu, avec le board de l'etape courante."""
        if not self.hand or not self.frames:
            return
        frame = self.frames[self.index]
        players = [s for s in self.hand.seats
                   if s.player not in frame.folded and (s.cards or s.is_hero)]
        known = [s for s in players if len(s.cards) == 2]
        if len(known) < 2:
            self.info.setText(self.info.text() + "   [equite: cartes inconnues]")
            return
        result = equity([list(s.cards) for s in known], board=frame.board, iterations=3000)
        self.canvas.equities = {s.player: pct for s, pct in zip(known, result.as_percent())}
        self.canvas.update()
