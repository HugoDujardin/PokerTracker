"""Surveillance temps reel des dossiers d'historique.

Un thread scrute les dossiers configures et importe le contenu ajoute aux
fichiers. C'est ce qui alimente le HUD pendant une session: des qu'une main
est ecrite par la room, elle est parsee puis diffusee aux abonnes.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..db import Database
from ..models import Hand
from .importer import Importer


class HandHistoryWatcher:
    """Boucle de scrutation (compatible Windows 11: aucune API specifique)."""

    def __init__(self, db: Database, folders: Sequence[str] = (), interval: float = 1.0,
                 archive_dir: Optional[str] = None) -> None:
        self.db = db
        self.archive_dir = archive_dir
        self.folders: list[str] = [str(f) for f in folders]
        self.interval = interval
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._subscribers: list[Callable[[list[Hand]], None]] = []
        self._lock = threading.RLock()
        self.last_error: str = ""
        self.imported_hands = 0
        self.active_files: dict[str, float] = {}

    # ------------------------------------------------------------------
    def subscribe(self, callback: Callable[[list[Hand]], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def add_folder(self, folder: str) -> None:
        with self._lock:
            if folder and folder not in self.folders:
                self.folders.append(folder)

    def set_folders(self, folders: Iterable[str]) -> None:
        with self._lock:
            self.folders = [str(f) for f in folders]

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="hh-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    def _dispatch(self, hands: list[Hand]) -> None:
        if not hands:
            return
        self.imported_hands += len(hands)
        with self._lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(hands)
            except Exception as exc:  # pragma: no cover - un abonne ne doit pas tuer le thread
                self.last_error = f"subscriber: {exc}"

    def scan_once(self) -> int:
        """Un tour de scrutation. Retourne le nombre de mains importees."""
        importer = Importer(self.db, on_hands=self._dispatch, archive_dir=self.archive_dir)
        total = 0
        with self._lock:
            folders = list(self.folders)
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for path in Importer.iter_files(folder):
                try:
                    st = path.stat()
                except OSError:
                    continue
                key = str(path)
                if self.active_files.get(key) == st.st_mtime:
                    continue
                self.active_files[key] = st.st_mtime
                res = importer.import_file(path)
                total += res.hands
                if res.errors:
                    self.last_error = res.errors[-1]
        return total

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:  # pragma: no cover
                self.last_error = str(exc)
            self._stop.wait(self.interval)
