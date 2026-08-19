"""Import des fichiers d'historique dans la base."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from ..db import Database
from ..models import Hand
from ..parsers import registry
from ..parsers.summaries import detect_summary

HH_SUFFIXES = (".txt", ".log", ".hhs", ".xml")


@dataclass
class ImportResult:
    files: int = 0
    hands: int = 0
    skipped: int = 0
    tournaments: int = 0              # resumes de tournoi enregistres
    archived: int = 0                 # octets recopies dans l'archive
    errors: list[str] = field(default_factory=list)

    def __iadd__(self, other: "ImportResult") -> "ImportResult":
        self.files += other.files
        self.hands += other.hands
        self.skipped += other.skipped
        self.tournaments += other.tournaments
        self.archived += other.archived
        self.errors.extend(other.errors)
        return self


class Importer:
    """Importe un fichier ou une arborescence, en ne relisant que le nouveau
    contenu des fichiers deja vus (les rooms ajoutent les mains a la fin)."""

    #: delai (s) au-dela duquel un fichier est considere comme stable
    settle_delay: float = 3.0

    def __init__(self, db: Database,
                 on_hands: Optional[Callable[[list[Hand]], None]] = None,
                 archive_dir: Optional[str | os.PathLike] = None) -> None:
        self.db = db
        self.on_hands = on_hands
        #: copie de securite des historiques (les rooms les effacent au bout
        #: de quelques mois); None desactive l'archivage
        self.archive_dir = Path(archive_dir) if archive_dir else None
        #: part du champ payee, utilisee pour estimer la bulle des tournois
        self.bubble_ratio = 0.15

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

        text = ""
        readers = registry.parsers
        if readers:
            try:
                text = readers[0].read_file(path)
            except OSError as exc:
                res.errors.append(f"{path}: {exc}")
                return res

        # un fichier de resume de tournoi ne contient pas de mains: il
        # alimente le suivi financier (gains, places, ITM, bulles)
        summary_parser = detect_summary(text)
        if summary_parser is not None:
            results = list(summary_parser.parse_text(text[offset:]))
            saved = self.db.insert_tournaments(results, bubble_ratio=self.bubble_ratio)
            dates = [r.started_at for r in results if r.started_at]
            archived = self.archive(text[offset:], summary_parser.room, [], Path(path).name,
                                    subfolder="tournois", when=min(dates) if dates else None)
            self.db.upsert_file(path, summary_parser.room, stat.st_size, stat.st_mtime,
                                len(text), 0)
            res.files = 1
            res.tournaments = saved
            res.archived = archived
            return res

        parser = registry.detect(text)
        if parser is None:
            res.skipped += 1
            return res

        if offset > len(text):       # fichier tronque ou recree par la room
            offset = 0
        chunk = text[offset:]
        # un fichier qui n'a pas bouge depuis quelques secondes est considere
        # comme stable: on peut le lire en entier. Sinon (main en cours
        # d'ecriture pendant une session), on s'arrete a la derniere main
        # complete et le reste sera lu au prochain passage.
        settled = (time.time() - stat.st_mtime) > self.settle_delay
        consumed = len(chunk) if settled else parser.complete_length(chunk)
        chunk = chunk[:consumed]
        hands = list(parser.parse_text(chunk))

        archived = self.archive(chunk, parser.room, hands, Path(path).name) if chunk else 0
        inserted = self.db.insert_hands(hands)
        self.db.upsert_file(path, parser.room, stat.st_size, stat.st_mtime,
                            offset + consumed, inserted)
        res.files = 1
        res.hands = inserted
        res.archived = archived
        if hands and self.on_hands:
            self.on_hands(hands)
        return res

    # ------------------------------------------------------------------
    def archive(self, chunk: str, room: str, hands: list[Hand], filename: str,
                subfolder: str = "", when: Optional[datetime] = None) -> int:
        """Recopie les mains importees dans l'archive locale.

        Les rooms purgent leurs dossiers d'historiques (souvent au bout de
        quelques mois): sans copie, les mains anciennes ne peuvent plus etre
        reimportees en cas de reconstruction de la base. Le contenu est
        ajoute en fin de fichier, si bien qu'un import incrementiel ne
        duplique jamais ce qui a deja ete archive.
        """
        if not self.archive_dir or not chunk.strip():
            return 0
        when = when or (hands[0].played_at if hands else datetime.now())
        target_dir = self.archive_dir / (room or "inconnu") / f"{when:%Y-%m}"
        if subfolder:
            target_dir = target_dir / subfolder
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            with open(target, "a", encoding="utf-8") as fh:
                if target.stat().st_size:
                    fh.write("\n\n")
                fh.write(chunk.strip())
                fh.write("\n\n")
        except OSError:
            return 0
        return len(chunk.encode("utf-8"))

    def archive_size(self) -> tuple[int, int]:
        """(nombre de fichiers, octets) presents dans l'archive."""
        if not self.archive_dir or not self.archive_dir.exists():
            return 0, 0
        files = [p for p in self.archive_dir.rglob("*") if p.is_file()]
        return len(files), sum(p.stat().st_size for p in files)

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
        for p in sorted(it):
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
