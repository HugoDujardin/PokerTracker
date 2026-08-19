"""Onglet « Coach IA » — analyses en un clic.

Une rangee de boutons declenche directement l'analyse la plus courante:
dernier tournoi, tournoi choisi dans la liste, dernier coup joue, coup
affiche dans le replayer, statistiques globales. Les reglages (fournisseur,
cle, modele) sont regroupes dans un bandeau repliable: une fois la cle
saisie, on ne les rouvre plus.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ..ai.analyses import (Analysis, hand_analysis, last_hand_analysis, last_tournament_analysis,
                           stats_analysis, tournament_analysis)
from ..ai.coach import CoachConfig, CoachError, PokerCoach
from ..ai.providers import PROVIDERS
from ..config import Settings
from ..core.db import Database
from ..core.models import Hand


class _Worker(QObject):
    """Execute l'appel hors du fil de l'interface."""

    chunk = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, coach: PokerCoach, analysis: Analysis) -> None:
        super().__init__()
        self.coach = coach
        self.analysis = analysis
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            texte = self.coach.ask(self.analysis.context, self.analysis.question,
                                   on_chunk=self.chunk.emit, stop=lambda: self._stop)
            self.finished.emit(texte)
        except CoachError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                      # pragma: no cover - robustesse
            self.failed.emit(f"Erreur inattendue: {exc}")


class CoachTab(QWidget):
    """Interface simplifiee du coach."""

    def __init__(self, db: Database, settings: Settings,
                 current_hand: Optional[Callable[[], Optional[Hand]]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.current_hand = current_hand
        self.last_analysis: Optional[Analysis] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None

        # ---- analyses en un clic
        self.btn_last_tournament = QPushButton("Analyser le dernier tournoi")
        self.btn_last_tournament.clicked.connect(self.analyse_last_tournament)
        self.tournament_box = QComboBox()
        self.btn_tournament = QPushButton("Analyser ce tournoi")
        self.btn_tournament.clicked.connect(self.analyse_selected_tournament)
        self.btn_last_hand = QPushButton("Analyser le dernier coup joue")
        self.btn_last_hand.clicked.connect(self.analyse_last_hand)
        self.btn_current_hand = QPushButton("Analyser le coup affiche (onglet Mains)")
        self.btn_current_hand.clicked.connect(self.analyse_current_hand)
        self.btn_stats = QPushButton("Analyser mes statistiques")
        self.btn_stats.clicked.connect(self.analyse_stats)
        self.player_box = QComboBox()

        actions = QGroupBox("Analyses")
        actions_layout = QVBoxLayout(actions)
        ligne1 = QHBoxLayout()
        ligne1.addWidget(self.btn_last_tournament)
        ligne1.addWidget(self.tournament_box, 1)
        ligne1.addWidget(self.btn_tournament)
        actions_layout.addLayout(ligne1)
        ligne2 = QHBoxLayout()
        ligne2.addWidget(self.btn_last_hand)
        ligne2.addWidget(self.btn_current_hand)
        ligne2.addWidget(QLabel("Joueur:"))
        ligne2.addWidget(self.player_box, 1)
        ligne2.addWidget(self.btn_stats)
        actions_layout.addLayout(ligne2)
        self.question = QLineEdit()
        self.question.setPlaceholderText(
            "question precise (facultatif) — ex: « fallait-il payer la river ? »")
        self.question.returnPressed.connect(self.analyse_last_hand)
        actions_layout.addWidget(self.question)

        # ---- reponse
        self.title = QLabel("")
        self.title.setStyleSheet("color:#8fb3d9;")
        self.title.setWordWrap(True)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setFont(QFont("Segoe UI", 10))
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.btn_stop = QPushButton("Arreter")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_analysis)
        self.btn_context = QPushButton("Voir les donnees envoyees")
        self.btn_context.clicked.connect(self.show_context)
        self.btn_copy = QPushButton("Copier l'analyse")
        self.btn_copy.clicked.connect(self.copy_answer)
        barre = QHBoxLayout()
        barre.addWidget(self.status, 1)
        barre.addWidget(self.btn_context)
        barre.addWidget(self.btn_copy)
        barre.addWidget(self.btn_stop)

        # ---- reglages (replies par defaut si une cle est deja connue)
        self.provider_box = QComboBox()
        for name, provider in PROVIDERS.items():
            suffixe = " — offre gratuite" if provider.free_tier else " — payant"
            self.provider_box.addItem(provider.label + suffixe, name)
        index = self.provider_box.findData(settings.ai_provider)
        self.provider_box.setCurrentIndex(max(0, index))
        self.provider_box.currentIndexChanged.connect(self._provider_changed)
        self.api_key = QLineEdit(settings.ai_key(settings.ai_provider))
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("collez votre cle d'API ici")
        self.api_key.editingFinished.connect(self._save_settings)
        self.btn_key = QPushButton("Obtenir une cle")
        self.btn_key.clicked.connect(self._open_key_page)
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.currentTextChanged.connect(self._save_settings)
        self.btn_models = QPushButton("Modeles disponibles")
        self.btn_models.clicked.connect(self._refresh_models)
        self.deep = QCheckBox("Analyse approfondie")
        self.deep.setChecked(settings.ai_deep_analysis)
        self.deep.setToolTip("Decochez pour des reponses plus rapides et moins gourmandes "
                             "en quota.")
        self.deep.stateChanged.connect(self._save_settings)

        self.settings_box = QGroupBox("Reglages de l'assistant")
        self.settings_box.setCheckable(True)
        reglages = QVBoxLayout(self.settings_box)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Fournisseur:"))
        row1.addWidget(self.provider_box)
        row1.addWidget(QLabel("Cle d'API:"))
        row1.addWidget(self.api_key, 1)
        row1.addWidget(self.btn_key)
        reglages.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Modele:"))
        row2.addWidget(self.model_box, 1)
        row2.addWidget(self.btn_models)
        row2.addWidget(self.deep)
        reglages.addLayout(row2)
        self.privacy = QLabel("")
        self.privacy.setWordWrap(True)
        self.privacy.setStyleSheet("color:#8fb3d9;")
        reglages.addWidget(self.privacy)
        self.settings_box.toggled.connect(self._toggle_settings)

        layout = QVBoxLayout(self)
        layout.addWidget(actions)
        layout.addWidget(self.title)
        layout.addWidget(self.answer, 1)
        layout.addLayout(barre)
        layout.addWidget(self.settings_box)

        self._provider_changed()
        self.settings_box.setChecked(not self.coach().available()[0])
        self._toggle_settings(self.settings_box.isChecked())

    # ------------------------------------------------------------ reglages
    def coach(self) -> PokerCoach:
        return PokerCoach(CoachConfig(
            provider=self.provider_box.currentData(),
            api_key=self.api_key.text().strip(),
            model=self.model_box.currentText().strip(),
            deep_analysis=self.deep.isChecked(),
        ))

    def _provider_changed(self) -> None:
        name = self.provider_box.currentData()
        provider = PROVIDERS[name]
        self.api_key.blockSignals(True)
        self.api_key.setText(self.settings.ai_key(name))
        self.api_key.blockSignals(False)
        self.model_box.blockSignals(True)
        self.model_box.clear()
        self.model_box.addItems(provider.models)
        self.model_box.setCurrentText(self.settings.ai_model
                                      if self.settings.ai_model in provider.models
                                      else provider.default_model)
        self.model_box.blockSignals(False)
        gratuit = ("Offre gratuite: une cle Google AI Studio suffit, sans carte bancaire "
                   "(quotas par minute et par jour)." if provider.free_tier else
                   "Fournisseur payant, facture a l'usage.")
        self.privacy.setText(
            f"{gratuit} Seules les donnees de l'analyse demandee (la main, le tournoi ou vos "
            f"statistiques) sont envoyees, et uniquement au moment ou vous lancez une analyse. "
            f"Bouton « Voir les donnees envoyees » pour les consulter.")
        self._save_settings()
        self._update_status()

    def _save_settings(self) -> None:
        name = self.provider_box.currentData()
        self.settings.ai_provider = name
        self.settings.set_ai_key(name, self.api_key.text().strip())
        self.settings.ai_model = self.model_box.currentText().strip()
        self.settings.ai_deep_analysis = self.deep.isChecked()
        self.settings.save()

    def _toggle_settings(self, ouvert: bool) -> None:
        for widget in (self.provider_box, self.api_key, self.btn_key, self.model_box,
                       self.btn_models, self.deep, self.privacy):
            widget.setVisible(ouvert)

    def _open_key_page(self) -> None:
        provider = PROVIDERS[self.provider_box.currentData()]
        QDesktopServices.openUrl(QUrl(getattr(provider, "key_url", "")))

    def _refresh_models(self) -> None:
        coach = self.coach()
        ok, raison = coach.available()
        if not ok:
            QMessageBox.information(self, "Coach IA", raison)
            return
        modeles = coach.models()
        courant = self.model_box.currentText()
        self.model_box.blockSignals(True)
        self.model_box.clear()
        self.model_box.addItems(modeles)
        self.model_box.setCurrentText(courant if courant in modeles else modeles[0])
        self.model_box.blockSignals(False)
        self.status.setText(f"{len(modeles)} modeles disponibles pour cette cle.")

    def _update_status(self) -> None:
        ok, raison = self.coach().available()
        self.status.setText("Pret." if ok else raison)
        for bouton in (self.btn_last_tournament, self.btn_tournament, self.btn_last_hand,
                       self.btn_current_hand, self.btn_stats):
            bouton.setEnabled(ok and self._thread is None)

    # ------------------------------------------------------------ donnees
    def reload_players(self) -> None:
        courant = self.player_box.currentText()
        self.player_box.blockSignals(True)
        self.player_box.clear()
        for row in self.db.heroes():
            self.player_box.addItem(f"{row['name']} ({row['room']})", row["id"])
        for row in self.db.find_players("", limit=60):
            if not row["is_hero"]:
                self.player_box.addItem(f"{row['name']} ({row['room']})", row["id"])
        index = self.player_box.findText(courant)
        if index >= 0:
            self.player_box.setCurrentIndex(index)
        self.player_box.blockSignals(False)

        self.tournament_box.blockSignals(True)
        self.tournament_box.clear()
        for row in self.db.tournaments(limit=200):
            date = (row["started_at"] or "")[:10]
            place = f"{row['finish_place']}/{row['entrants']}" if row["finish_place"] else "-"
            self.tournament_box.addItem(
                f"{date} · {row['name'] or row['tournament_id']} · {place} · "
                f"{row['profit']:+.2f}", row["id"])
        self.tournament_box.blockSignals(False)
        self._update_status()

    def hero_id(self) -> Optional[int]:
        heroes = self.db.heroes()
        return heroes[0]["id"] if heroes else self.player_box.currentData()

    # ------------------------------------------------------------ analyses
    def analyse_last_tournament(self) -> None:
        analysis = last_tournament_analysis(self.db, self.hero_id(), self.question.text())
        if analysis is None:
            QMessageBox.information(self, "Coach IA",
                                    "Aucun tournoi en base. Importez les fichiers de resume "
                                    "de tournoi (dossier « TournSummary » de votre room).")
            return
        self.run_analysis(analysis)

    def analyse_selected_tournament(self) -> None:
        tournament_id = self.tournament_box.currentData()
        if tournament_id is None:
            QMessageBox.information(self, "Coach IA", "Aucun tournoi a analyser.")
            return
        row = self.db.tournament_by_id(tournament_id)
        if row is None:
            return
        self.run_analysis(tournament_analysis(self.db, row, self.hero_id(),
                                              self.question.text()))

    def analyse_last_hand(self) -> None:
        hero = self.hero_id()
        analysis = last_hand_analysis(self.db, hero, self.question.text()) if hero else None
        if analysis is None:
            QMessageBox.information(self, "Coach IA", "Aucune main en base pour ce joueur.")
            return
        self.run_analysis(analysis)

    def analyse_current_hand(self) -> None:
        hand = self.current_hand() if self.current_hand else None
        if hand is None:
            QMessageBox.information(self, "Coach IA",
                                    "Selectionnez d'abord une main dans l'onglet « Mains ».")
            return
        self.run_analysis(hand_analysis(self.db, hand, self.question.text()))

    def analyse_stats(self) -> None:
        player_id = self.player_box.currentData()
        if player_id is None:
            QMessageBox.information(self, "Coach IA", "Aucun joueur selectionne.")
            return
        self.run_analysis(stats_analysis(self.db, player_id, self.player_box.currentText(),
                                         self.question.text()))

    # ------------------------------------------------------------ execution
    def run_analysis(self, analysis: Analysis) -> None:
        if self._thread is not None:
            return
        coach = self.coach()
        ok, raison = coach.available()
        if not ok:
            self.settings_box.setChecked(True)
            QMessageBox.warning(self, "Coach IA", raison)
            self.status.setText(raison)
            return
        if analysis.empty():
            QMessageBox.information(self, "Coach IA", "Aucune donnee a analyser.")
            return
        self.last_analysis = analysis
        self.title.setText(f"<b>{analysis.title}</b>"
                           + (f" — {analysis.subtitle}" if analysis.subtitle else ""))
        self.answer.clear()
        self.status.setText(f"Analyse en cours ({coach.provider().label}, "
                            f"{coach.config.model or coach.provider().default_model})...")
        self.btn_stop.setEnabled(True)
        for bouton in (self.btn_last_tournament, self.btn_tournament, self.btn_last_hand,
                       self.btn_current_hand, self.btn_stats):
            bouton.setEnabled(False)

        self._thread = QThread(self)
        self._worker = _Worker(coach, analysis)
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

    def show_context(self) -> None:
        if self.last_analysis is None:
            QMessageBox.information(self, "Coach IA",
                                    "Lancez une analyse pour voir les donnees envoyees.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Donnees envoyees a l'assistant")
        dialog.resize(760, 640)
        vue = QPlainTextEdit(dialog)
        vue.setReadOnly(True)
        vue.setPlainText(f"{self.last_analysis.context}\n\n---\n\n{self.last_analysis.question}")
        layout = QVBoxLayout(dialog)
        layout.addWidget(vue)
        dialog.exec()

    def copy_answer(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.answer.toPlainText())
        self.status.setText("Analyse copiee dans le presse-papiers.")

    def _append(self, texte: str) -> None:
        self.answer.moveCursor(self.answer.textCursor().MoveOperation.End)
        self.answer.insertPlainText(texte)
        self.answer.ensureCursorVisible()

    def _cleanup(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self.btn_stop.setEnabled(False)
        self._update_status()

    def _done(self, texte: str) -> None:
        self.status.setText("Analyse terminee.")
        self._cleanup()

    def _error(self, message: str) -> None:
        self.status.setText(message)
        QMessageBox.warning(self, "Coach IA", message)
        self._cleanup()
