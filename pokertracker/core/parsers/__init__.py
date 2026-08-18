"""Parsers d'historiques de mains, un par room.

L'import de ce module enregistre tous les parsers disponibles dans le
`registry` partage, qui detecte automatiquement le format d'un fichier.
"""
from .base import HandParser, ParseError, ParserRegistry, registry, to_decimal  # noqa: F401
from . import pokerstars, winamax, ggpoker, partypoker  # noqa: F401,E402

__all__ = ["HandParser", "ParseError", "ParserRegistry", "registry", "to_decimal"]
