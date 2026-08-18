"""Infrastructure commune aux parsers d'historiques de mains."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import Iterator, Optional

from ..models import Hand

# Tolere les formats "1 234,56", "1,234.56", "$12.50", "12.50€"
_NUM_CLEAN = re.compile(r"[^\d,.\-]")


def to_decimal(value: str | None) -> Decimal:
    if value is None:
        return Decimal(0)
    txt = _NUM_CLEAN.sub("", str(value)).strip()
    if not txt:
        return Decimal(0)
    if "," in txt and "." in txt:
        # le dernier separateur rencontre est le separateur decimal
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        # "1,50" (decimal) vs "1,500" (milliers) -> 2 decimales = decimal
        head, _, tail = txt.rpartition(",")
        txt = f"{head}.{tail}" if len(tail) in (1, 2) else txt.replace(",", "")
    try:
        return Decimal(txt)
    except InvalidOperation:
        return Decimal(0)


def parse_buyin(text: str | None) -> Decimal:
    """Cout total d'un tournoi: '$10+$1' -> 11, '0,45€ + 0,05€' -> 0.50."""
    if not text:
        return Decimal(0)
    parts = [p for p in re.split(r"\+", str(text)) if re.search(r"\d", p)]
    return sum((to_decimal(p) for p in parts), Decimal(0))


class ParseError(ValueError):
    """Historique illisible ou format non reconnu."""


class HandParser(ABC):
    """Interface commune a tous les parsers de room."""

    room: str = "unknown"
    #: encodages a essayer, dans l'ordre, a la lecture d'un fichier
    encodings: tuple[str, ...] = ("utf-8-sig", "utf-16", "cp1252", "latin-1")

    @abstractmethod
    def detect(self, text: str) -> bool:
        """Retourne True si ce parser reconnait le contenu du fichier."""

    @abstractmethod
    def split_hands(self, text: str) -> Iterator[str]:
        """Decoupe le contenu d'un fichier en blocs de mains."""

    @abstractmethod
    def parse_hand(self, block: str) -> Hand:
        """Transforme un bloc texte en objet `Hand`."""

    #: marqueur de fin de main, utilise pour ne pas importer une main que la
    #: room est encore en train d'ecrire
    end_marker = re.compile(r"\*\*+\s*SUMMARY\s*\*\*+", re.I)

    def complete_length(self, chunk: str) -> int:
        """Longueur du prefixe de `chunk` ne contenant que des mains completes."""
        last = None
        for m in self.end_marker.finditer(chunk):
            last = m
        if last is None:
            return 0
        blank = chunk.find("\n\n", last.end())
        if blank != -1:
            return blank + 2
        # la derniere main est en cours d'ecriture: on s'arrete juste avant
        prev = chunk.rfind("\n\n", 0, last.start())
        return prev + 2 if prev != -1 else 0

    # ------------------------------------------------------------------
    def parse_text(self, text: str) -> Iterator[Hand]:
        for block in self.split_hands(text):
            block = block.strip()
            if not block:
                continue
            try:
                hand = self.parse_hand(block)
            except ParseError:
                continue
            except Exception as exc:  # pragma: no cover - robustesse import
                raise ParseError(f"{self.room}: {exc}") from exc
            if hand is not None:
                yield hand

    def read_file(self, path) -> str:
        data = open(path, "rb").read()
        for enc in self.encodings:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return data.decode("latin-1", errors="replace")


class ParserRegistry:
    """Selectionne automatiquement le parser adapte a un fichier."""

    def __init__(self) -> None:
        self._parsers: list[HandParser] = []

    def register(self, parser: HandParser) -> HandParser:
        self._parsers.append(parser)
        return parser

    @property
    def parsers(self) -> list[HandParser]:
        return list(self._parsers)

    def detect(self, text: str) -> Optional[HandParser]:
        for p in self._parsers:
            try:
                if p.detect(text):
                    return p
            except Exception:
                continue
        return None

    def parse_text(self, text: str) -> Iterator[Hand]:
        parser = self.detect(text)
        if parser is None:
            return iter(())
        return parser.parse_text(text)

    def parse_file(self, path) -> Iterator[Hand]:
        raw = HandParser.read_file(self._parsers[0], path) if self._parsers else ""
        return self.parse_text(raw)


registry = ParserRegistry()
