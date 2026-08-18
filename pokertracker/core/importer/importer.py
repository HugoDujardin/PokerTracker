"""Import des fichiers d'historique dans la base."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..db import Database
from ..models import Hand
from ..parsers import registry

HH_SUFFIXES = (".txt", ".log", ".hhs", ".xml")


@dataclass
class ImportResult:
    files: int = 0
    hands: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def __iadd__(self, other: "ImportResult") -> "ImportResult":
        self.files += other.files
        self.hands += other.hands
        self.skipped += other.skipped
        self.errors.extend(other.errors)
        return self


class Importer:
    """Importe un fichier ou une arborescence, en ne relisant que le nouveau
    contenu des fichiers deja vus (les rooms ajoutent les mains a la fin)."""

    #: delai (s) au-dela duquel un fichier est considere comme stable
    settle_delay: float = 3.0

    def __init__(self, db: Database,
                 on_hands: Optional[Callable[[list[Hand]], None]] = None) -> None:
        self.db = db
        self.on_hands = on_hands

    # ------------------------------------------------------------------
    def import_file(self, path: str | os.PathLike, force: bool = False) -> ImportResult:
        res = ImportResult()
        path = str(Path(path))
        try:
            stat = os.stat(path)
        except OSError as exc:
            res.errors.append(f"{path}: {exc}")
            return res

        state = None if force else self.db.file_state(path)
        offset = int(state["offset"]) if state else 0
        if state and stat.st_size == int(state["size"]) and stat.st_mtime <= float(state["mtime"]):
            res.skipped += 1
            return res

        parser = None
        for p in registry.parsers:
            try:
                head = p.read_file(path)
            except OSError as exc:
                res.errors.append(f"{path}: {exc}")
                return res
            if p.detect(head):
                parser = p
                text = head
                break
        if parser is None:
            res.skipped += 1
            return res

        if offset > len(text):       # fichier tronque/recree
            offset = 0
        chunk = text[offset:]
        # un fichier qui n'a pas bouge depuis quelques secondes est considere
        # comme stable: on peut le lire en entier. Sinon (main en cours
        # d'ecriture pendant une session), on s'arrete a la derniere main
        # complete et le reste sera lu au prochain passage.
        settled = (time.time() - stat.st_mtime) > self.settle_delay
        consumed = len(chunk) if settled else parser.complete_length(chunk)
        chunk = chunk[:consumed]

        hands: list[Hand] = []
        for hand in parser.parse_text(chunk):
            hands.append(hand)
        inserted = self.db.insert_hands(hands)
        self.db.upsert_file(path, parser.room, stat.st_size, stat.st_mtime,
                            offset + consumed, inserted)
        res.files = 1
        res.hands = inserted
        if hands and self.on_hands:
            self.on_hands(hands)
        return res

    # ------------------------------------------------------------------
    def import_directory(self, folder: str | os.PathLike, recursive: bool = True,
                         progress: Optional[Callable[[int, int, str], None]] = None,
                         force: bool = False) -> ImportResult:
        res = ImportResult()
        files = list(self.iter_files(folder, recursive))
        for i, f in enumerate(files, start=1):
            res += self.import_file(f, force=force)
            if progress:
                progress(i, len(files), str(f))
        return res

    @staticmethod
    def iter_files(folder: str | os.PathLike, recursive: bool = True) -> Iterable[Path]:
        folder = Path(folder)
        it = folder.rglob("*") if recursive else folder.glob("*")
        for p in it:
            if p.is_file() and p.suffix.lower() in HH_SUFFIXES:
                yield p


#: emplacements par defaut des historiques sur Windows 11
DEFAULT_HH_DIRS: dict[str, Sequence[str]] = {
    "PokerStars": (r"%LOCALAPPDATA%\PokerStars\HandHistory",
                   r"%USERPROFILE%\AppData\Local\PokerStars.FR\HandHistory"),
    "Winamax": (r"%APPDATA%\wamax\documents\accounts",),
    "GGPoker": (r"%APPDATA%\GGPoker\HandHistory",
                r"%USERPROFILE%\Documents\GGPoker\HandHistory"),
    "PartyPoker": (r"%USERPROFILE%\Documents\PartyGaming\PartyPoker\HandHistory",),
}


def detect_hh_directories() -> dict[str, str]:
    """Retourne les dossiers d'historique existants sur la machine."""
    found: dict[str, str] = {}
    for room, candidates in DEFAULT_HH_DIRS.items():
        for raw in candidates:
            path = Path(os.path.expandvars(raw))
            if path.exists():
                found[room] = str(path)
                break
    return found
