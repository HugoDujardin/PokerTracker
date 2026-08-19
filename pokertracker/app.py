"""Point d'entree de PokerTracker."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DARK_STYLE = """
/* Aucune taille de police en pixels: la police de l'application (reglee sur
   celle du systeme) est respectee, y compris avec la mise a l'echelle de
   Windows 11 a 125 % ou 150 %. */
QWidget { background-color: #12161c; color: #d8dee6; }
QTabWidget::pane { border: 1px solid #262d38; }
QTabBar::tab { background: #171d25; padding: 7px 16px; border: 1px solid #262d38; border-bottom: none; }
QTabBar::tab:selected { background: #223044; color: #ffffff; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {
    background: #1a212a; border: 1px solid #2c3542; padding: 4px; border-radius: 3px;
    min-height: 1.5em; }
QComboBox { padding-right: 22px; }                 /* place pour la fleche */
QComboBox::drop-down { width: 18px; }
QSpinBox, QDoubleSpinBox, QDateEdit { padding-right: 18px; }
QTabBar::tab { min-height: 1.6em; }
QLabel { padding: 1px; }
QPushButton { background: #223044; border: 1px solid #2f4257; padding: 6px 14px;
    border-radius: 3px; min-height: 1.6em; }
QPushButton:hover { background: #2b3f59; }
QPushButton:pressed { background: #1b2836; }
QTableWidget { background: #151b23; gridline-color: #262d38; alternate-background-color: #181f28; }
QHeaderView::section { background: #1d242e; padding: 5px 8px; border: none;
    border-right: 1px solid #262d38; }
QGroupBox { border: 1px solid #2a323d; margin-top: 12px; border-radius: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8fb3d9; }
QProgressBar { border: 1px solid #2c3542; border-radius: 3px; text-align: center; }
QProgressBar::chunk { background: #3f7fbf; }
QListWidget { background: #151b23; border: 1px solid #262d38; }
QStatusBar { background: #171d25; }
QMenuBar { background: #171d25; } QMenuBar::item:selected { background: #223044; }
QMenu { background: #1a212a; border: 1px solid #2c3542; } QMenu::item:selected { background: #223044; }
QToolTip { background: #1a212a; color: #d8dee6; border: 1px solid #3a4250; }
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pokertracker",
        description="Suivi de mains, statistiques et HUD temps reel pour le poker en ligne.")
    parser.add_argument("--db", help="chemin de la base de donnees")
    parser.add_argument("--import", dest="import_dir", help="importer un dossier puis quitter")
    parser.add_argument("--no-hud", action="store_true", help="demarrer sans le HUD")
    parser.add_argument("--no-watch", action="store_true", help="desactiver l'import temps reel")
    return parser


def run_cli_import(db_path: str, folder: str) -> int:
    """Import en ligne de commande (utile pour un premier chargement massif)."""
    from .core.db import Database
    from .core.importer import Importer

    db = Database(db_path)
    importer = Importer(db)

    def progress(i: int, total: int, path: str) -> None:
        print(f"\r[{i}/{total}] {Path(path).name[:60]:60s}", end="", flush=True)

    result = importer.import_directory(folder, progress=progress)
    print(f"\n{result.hands} mains importees depuis {result.files} fichier(s).")
    if result.errors:
        print(f"{len(result.errors)} erreur(s), dont: {result.errors[0]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from .config import Settings
    settings = Settings.load()
    db_path = args.db or settings.db_path

    if args.import_dir:
        return run_cli_import(db_path, args.import_dir)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QGuiApplication
    from PySide6.QtWidgets import QApplication
    from .core.db import Database
    from .core.importer import HandHistoryWatcher
    from .hud.manager import HudManager
    from .hud.overlay import HudController
    from .hud.profile import BUILTIN_PROFILES, HudProfile, default_profile
    from .ui.main_window import MainWindow

    # respecte exactement le facteur d'echelle de Windows (125 %, 150 %...)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("PokerTracker")
    if sys.platform.startswith("win"):
        app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(DARK_STYLE)

    db = Database(db_path)
    saved = db.load_profiles()
    if settings.hud_profile in saved:
        profile = HudProfile.from_json(saved[settings.hud_profile])
    else:
        profile = HudProfile.from_json(
            BUILTIN_PROFILES.get(settings.hud_profile, default_profile()).to_json())

    watcher = HandHistoryWatcher(db, settings.hh_folders, settings.scan_interval,
                                 archive_dir=settings.effective_archive_dir())
    manager = HudManager(db, profile, min_hands=settings.hud_min_hands)
    manager.restore_recent_tables()      # le HUD est utilisable des le lancement
    watcher.subscribe(manager.on_new_hands)
    controller = HudController(manager, settings)

    window = MainWindow(db, settings, watcher, manager, controller)
    window.show()

    if settings.auto_import and not args.no_watch:
        watcher.start()
    if settings.hud_enabled and not args.no_hud:
        controller.start()

    return app.exec()


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
