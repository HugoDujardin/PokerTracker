"""Affichage du HUD par-dessus les tables de poker.

Chaque joueur recoit un petit panneau translucide, sans bordure et
toujours au premier plan, positionne au-dessus de son siege. Le panneau
est deplacable a la souris (la position est memorisee), le clic droit
ouvre le menu (popup detaille, note, masquer) et le survol affiche le
popup de statistiques completes.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..config import Settings
from .manager import HudManager, HudPlayerPanel, TableHud
from .seatmap import to_screen

OVERLAY_FLAGS = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                 | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)


class StatLabel(QLabel):
    """Une statistique du panneau (avec info-bulle explicative)."""

    def __init__(self, text: str, color: str, tooltip: str) -> None:
        super().__init__(text)
        self.setStyleSheet(f"color: {color}; background: transparent;")
        self.setToolTip(tooltip)
        self.setAlignment(Qt.AlignCenter)


class HudPanelWidget(QWidget):
    """Panneau HUD d'un joueur."""

    request_popup = Signal(str, str)          # joueur, room
    request_note = Signal(str, str)
    moved = Signal(str, int, QPoint)          # cle de table, siege, decalage

    def __init__(self, table_key: str, seat_no: int, settings: Settings) -> None:
        super().__init__(None, OVERLAY_FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.table_key = table_key
        self.seat_no = seat_no
        self.settings = settings
        self.player = ""
        self.room = ""
        self.offset = QPoint(0, 0)
        self._drag_from: Optional[QPoint] = None
        self._bg = QColor("#101317")
        self._border = QColor("#3a4250")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 4, 6, 4)
        self._layout.setSpacing(1)
        self._title = QLabel("")
        self._title.setStyleSheet("color:#9fb4cc; background: transparent;")
        self._layout.addWidget(self._title)
        self._grid_host = QWidget(self)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(7)
        self._grid.setVerticalSpacing(0)
        self._layout.addWidget(self._grid_host)

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # pragma: no cover - rendu
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg = QColor(self._bg)
        bg.setAlphaF(self.settings.hud_opacity)
        painter.setBrush(bg)
        painter.setPen(QPen(self._border, 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 5, 5)

    def update_content(self, data: HudPlayerPanel, room: str, font: QFont) -> None:
        self.player = data.player
        self.room = room
        self._bg = QColor(data.color or data.panel.background)
        self._border = QColor(data.panel.border)
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        title_bits = []
        if self.settings.show_hand_count or True:
            if data.is_hero:
                title_bits.append("HERO")
            title_bits.append(data.player[:14])
            if data.position:
                title_bits.append(data.position)
        self._title.setText(" · ".join(title_bits))
        self._title.setFont(font)
        self._title.setVisible(bool(title_bits))
        if data.note:
            self.setToolTip(data.note)

        for r, row in enumerate(data.rows):
            for c, cell in enumerate(row):
                stat_label = StatLabel(cell.text, cell.color, f"{cell.title} ({cell.code})")
                stat_label.setFont(font)
                self._grid.addWidget(stat_label, r, c)
        self.adjustSize()

    # ------------------------------------------------------------- souris
    def mousePressEvent(self, event) -> None:  # pragma: no cover - interaction
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:  # pragma: no cover - interaction
        if self._drag_from is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_from
            delta = new_pos - self.pos()
            self.offset += delta
            self.move(new_pos)

    def mouseReleaseEvent(self, event) -> None:  # pragma: no cover - interaction
        if self._drag_from is not None:
            self._drag_from = None
            self.moved.emit(self.table_key, self.seat_no, self.offset)

    def enterEvent(self, event) -> None:  # pragma: no cover - interaction
        if self.settings.popup_on_hover and self.player:
            self.request_popup.emit(self.player, self.room)

    def _menu(self, pos) -> None:  # pragma: no cover - interaction
        menu = QMenu(self)
        act_popup = QAction("Statistiques detaillees", menu)
        act_popup.triggered.connect(lambda: self.request_popup.emit(self.player, self.room))
        act_note = QAction("Note sur le joueur...", menu)
        act_note.triggered.connect(lambda: self.request_note.emit(self.player, self.room))
        act_hide = QAction("Masquer ce panneau", menu)
        act_hide.triggered.connect(self.hide)
        menu.addAction(act_popup)
        menu.addAction(act_note)
        menu.addSeparator()
        menu.addAction(act_hide)
        menu.exec(self.mapToGlobal(pos))


class PopupWindow(QWidget):
    """Popup de statistiques detaillees (equivalent des popups Hand2Note)."""

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            "QWidget { background:#0d1014; color:#dfe6ee; border:1px solid #38414f; }"
            "QLabel[role='section'] { color:#7fc4ff; font-weight:bold; }"
            "QLabel[role='sample'] { color:#6f7d8c; }")
        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(10, 8, 10, 8)
        self._root.setSpacing(16)

    def show_for(self, title: str, sections: List[tuple], at: Optional[QPoint] = None) -> None:
        while self._root.count():
            item = self._root.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for section_title, rows in sections:
            column = QWidget(self)
            box = QVBoxLayout(column)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(1)
            header = QLabel(f"{section_title}")
            header.setProperty("role", "section")
            box.addWidget(header)
            for label, value, sample in rows:
                line = QLabel(f"{label:<16} {value:>5}   ({sample})")
                line.setFont(QFont("Consolas", 9))
                box.addWidget(line)
            box.addStretch(1)
            self._root.addWidget(column)
        self.setWindowTitle(title)
        self.adjustSize()
        pos = at or QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(pos.x() + 12, geo.right() - self.width() - 5)
        y = min(pos.y() + 12, geo.bottom() - self.height() - 5)
        self.move(max(geo.left(), x), max(geo.top(), y))
        self.show()

    def leaveEvent(self, event) -> None:  # pragma: no cover - interaction
        self.hide()


class HudController:
    """Cree, positionne et met a jour les panneaux au rythme d'un timer."""

    def __init__(self, manager: HudManager, settings: Settings) -> None:
        self.manager = manager
        self.settings = settings
        self.enabled = settings.hud_enabled
        self.panels: Dict[Tuple[str, int], HudPanelWidget] = {}
        self.offsets: Dict[str, QPoint] = {}
        self.popup = PopupWindow()
        self.note_callback: Optional[Callable[[str, str], None]] = None
        self._timer = QTimer()
        self._timer.timeout.connect(self.refresh)
        self._font = QFont(manager.profile.font_family, manager.profile.font_size)
        self._load_offsets()

    # ------------------------------------------------------------------
    def start(self, interval_ms: int = 700) -> None:
        self._timer.start(interval_ms)
        self.refresh()

    def stop(self) -> None:
        self._timer.stop()
        self.hide_all()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.hide_all()

    def hide_all(self) -> None:
        for widget in self.panels.values():
            widget.hide()
        self.popup.hide()

    def set_profile_font(self) -> None:
        self._font = QFont(self.manager.profile.font_family, self.manager.profile.font_size)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if not self.enabled:
            return
        seen: set[Tuple[str, int]] = set()
        for table in self.manager.snapshot():
            self._refresh_table(table, seen)
        for key, widget in self.panels.items():
            if key not in seen:
                widget.hide()

    def _refresh_table(self, table: TableHud, seen: set) -> None:
        window = table.window
        rect = (window.x, window.y, window.width, window.height)
        table_key = window.key()
        for data in table.panels:
            key = (table_key, data.seat_no)
            widget = self.panels.get(key)
            if widget is None:
                widget = HudPanelWidget(table_key, data.seat_no, self.settings)
                widget.request_popup.connect(self.show_popup)
                widget.request_note.connect(self._on_note)
                widget.moved.connect(self._on_moved)
                offset = self.offsets.get(f"{table_key}|{data.seat_no}")
                if offset is not None:
                    widget.offset = QPoint(offset)
                self.panels[key] = widget
            widget.update_content(data, table.state.room if table.state else window.room, self._font)
            size = (widget.sizeHint().width(), widget.sizeHint().height())
            x, y = to_screen(rect, (data.rel_x, data.rel_y), size)
            widget.move(x + widget.offset.x(), y + widget.offset.y())
            widget.show()
            seen.add(key)

    # ------------------------------------------------------------------
    def show_popup(self, player: str, room: str) -> None:
        sections = self.manager.popup_data(player, room)
        self.popup.show_for(player, sections)

    def _on_note(self, player: str, room: str) -> None:
        if self.note_callback:
            self.note_callback(player, room)

    def _on_moved(self, table_key: str, seat_no: int, offset: QPoint) -> None:
        self.offsets[f"{table_key}|{seat_no}"] = offset
        self._save_offsets()

    # --------------------------------------------------------- persistance
    def _offsets_path(self):
        from ..config import app_dir
        return app_dir() / "hud_offsets.json"

    def _load_offsets(self) -> None:
        import json
        path = self._offsets_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.offsets = {k: QPoint(int(v[0]), int(v[1])) for k, v in data.items()}

    def _save_offsets(self) -> None:
        import json
        data = {k: [p.x(), p.y()] for k, p in self.offsets.items()}
        try:
            self._offsets_path().write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            pass
