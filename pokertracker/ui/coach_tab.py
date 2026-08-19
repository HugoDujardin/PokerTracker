"""Onglet « Coach IA »: analyse d'un coup ou des statistiques d'un joueur."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTextEdit,
                               QVBoxLayout, QWidget)

from ..ai.coach import (CoachConfig, CoachError, EFFORT_LEVELS, PokerCoach, build_hand_context,
                        build_stats_context, hand_question, stats_question)
from ..config import Settings
from ..core.db import Database
from ..core.models import Hand
from ..core.parsers import registry

MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]


class _Worker(QObject):
    """Execute l'appel a l'assistant hors du fil de l'interface."""

    chunk = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, coach: PokerCoach, context: str, question: str) -> None:
        super().__init__()
        self.coach = coach
        self.context = context
        self.question = question
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            text = self.coach.ask(self.context, self.question,
                                  on_chunk=self.chunk.emit, stop=lambda: self._stop)
            self.finished.emit(text)
        except CoachError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                       # pragma: no cover - robustesse
            self.failed.emit(f"Erreur inattendue: {exc}")


class CoachTab(QWidget):
    """Interface du coach: choix du contexte, question libre, reponse en direct."""

    def __init__(self, db: Database, settings: Settings,
                 current_hand: Optional[Callable[[], Optional[Hand]]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.current_hand = current_hand
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None

        # ---- reglages
        self.api_key = QLineEdit(settings.ai_api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("cle ANTHROPIC_API_KEY (ou variable d'environnement)")
        self.api_key.editingFinished.connect(self._save_settings)
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self.model.setCurrentText(settings.ai_model)
        self.model.currentTextChanged.connect(self._save_settings)
        self.effort = QComboBox()
        self.effort.addItems(EFFORT_LEVELS)
        self.effort.setCurrentText(settings.ai_effort)
        self.effort.currentTextChanged.connect(self._save_settings)

        settings_box = QGroupBox("Assistant")
        form = QFormLayout(settings_box)
        form.addRow("Cle d'API", self.api_key)
        form.addRow("Modele", self.model)
        form.addRow("Niveau d'analyse", self.effort)
        privacy = QLabel("Les donnees de la main ou les statistiques choisies sont envoyees "
                         "a l'API Anthropic pour etre analysees. Rien n'est envoye tant que "
                         "vous ne lancez pas une analyse.")
        privacy.setWordWrap(True)
        privacy.setStyleSheet("color:#8fb3d9;")
        form.addRow(privacy)

        # ---- contexte
        self.source = QComboBox()
        self.source.addItems(["Main affichee dans l'onglet Mains", "Statistiques d'un joueur"])
        self.source.currentIndexChanged.connect(self._refresh_context)
        self.player = QComboBox()
        self.player.currentIndexChanged.connect(self._refresh_context)
        self.question = QLineEdit()
        self.question.setPlaceholderText("question libre (facultatif) — sinon analyse complete")
        self.btn_run = QPushButton("Analyser")
        self.btn_run.clicked.connect(self.run_analysis)
        self.btn_stop = QPushButton("Arreter")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_analysis)
        self.btn_refresh = QPushButton("Rafraichir le contexte")
        self.btn_refresh.clicked.connect(self._refresh_context)

        context_box = QGroupBox("Contexte envoye")
        context_layout = QVBoxLayout(context_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Source:"))
        row.addWidget(self.source, 1)
        row.addWidget(QLabel("Joueur:"))
        row.addWidget(self.player, 1)
        row.addWidget(self.btn_refresh)
        context_layout.addLayout(row)
        self.context_view = QPlainTextEdit()
        self.context_view.setReadOnly(True)
        context_layout.addWidget(self.context_view, 1)

        ask_row = QHBoxLayout()
        ask_row.addWidget(self.question, 1)
        ask_row.addWidget(self.btn_run)
        ask_row.addWidget(self.btn_stop)

        self.answer = QTextEdit()
        self.answer.setReadOnly(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(settings_box)
        left_layout.addWidget(context_box, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Analyse"))
        right_layout.addWidget(self.answer, 1)
        right_layout.addWidget(self.status)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([560, 620])

        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        layout.addLayout(ask_row)

    # ------------------------------------------------------------------
    def coach(self) -> PokerCoach:
        return PokerCoach(CoachConfig(api_key=self.api_key.text().strip(),
                                      model=self.model.currentText(),
                                      effort=self.effort.currentText()))

    def _save_settings(self) -> None:
        self.settings.ai_api_key = self.api_key.text().strip()
        self.settings.ai_model = self.model.currentText()
        self.settings.ai_effort = self.effort.currentText()
        self.settings.save()

    def reload_players(self) -> None:
        current = self.player.currentText()
        self.player.blockSignals(True)
        self.player.clear()
        for row in self.db.heroes():
            self.player.addItem(f"{row['name']} ({row['room']})", row["id"])
        for row in self.db.find_players("", limit=100):
            if not row["is_hero"]:
                self.player.addItem(f"{row['name']} ({row['room']})", row["id"])
        index = self.player.findText(current)
        if index >= 0:
            self.player.setCurrentIndex(index)
        self.player.blockSignals(False)
        self._refresh_context()

    # ------------------------------------------------------------------
    def build_context(self) -> tuple[str, str]:
        """(contexte, question par defaut) selon la source choisie."""
        if self.source.currentIndex() == 0:
            hand = self.current_hand() if self.current_hand else None
            if hand is None:
                return ("", "")
            names = [s.player for s in hand.seats]
            stats = self.db.aggregate_many(names, room=hand.room)
            return build_hand_context(hand, stats), hand_question(self.question.text())
        player_id = self.player.currentData()
        if player_id is None:
            return ("", "")
        agg = self.db.aggregate([player_id])
        by_position = self.db.aggregate([player_id], group_by="hp.position")
        return (build_stats_context(agg, by_position, self.player.currentText()),
                stats_question(self.question.text()))

    def _refresh_context(self) -> None:
        context, _question = self.build_context()
        if not context:
            self.context_view.setPlainText(
                "Selectionnez une main dans l'onglet « Mains » (ou choisissez "
                "« Statistiques d'un joueur ») puis rafraichissez le contexte.")
        else:
            self.context_view.setPlainText(context)

    # ------------------------------------------------------------------
    def run_analysis(self) -> None:
        if self._thread is not None:
            return
        coach = self.coach()
        ok, reason = coach.available()
        if not ok:
            QMessageBox.warning(self, "Coach IA", reason)
            self.status.setText(reason)
            return
        context, question = self.build_context()
        if not context:
            QMessageBox.information(self, "Coach IA", "Aucun contexte a analyser.")
            return
        self.context_view.setPlainText(context)
        self.answer.clear()
        self.status.setText(f"Analyse en cours avec {coach.config.model}...")
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._thread = QThread(self)
        self._worker = _Worker(coach, context, question)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.chunk.connect(self._append)
        self._worker.finished.connect(self._done)
        self._worker.failed.connect(self._error)
        self._thread.start()

    def stop_analysis(self) -> None:
        if self._worker:
            self._worker.stop()
        self.status.setText("Analyse interrompue.")

    def _append(self, text: str) -> None:
        cursor = self.answer.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.answer.setTextCursor(cursor)

    def _cleanup(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _done(self, text: str) -> None:
        self.status.setText(f"Analyse terminee ({len(text)} caracteres).")
        self._cleanup()

    def _error(self, message: str) -> None:
        self.status.setText(message)
        QMessageBox.warning(self, "Coach IA", message)
        self._cleanup()
