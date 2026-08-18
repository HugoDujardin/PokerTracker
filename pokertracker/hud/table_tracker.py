"""Detection et suivi des fenetres de table de poker (Windows 11).

L'implementation utilise directement user32 via ctypes: aucune dependance
native supplementaire n'est necessaire, et le module reste importable sur
les autres systemes (ou il ne detecte simplement aucune table, ce qui
permet de developper et de tester le reste de l'application).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

IS_WINDOWS = sys.platform.startswith("win")


@dataclass
class TableWindow:
    handle: int
    title: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    room: str = ""
    table_name: str = ""
    stake: str = ""
    max_seats: int = 0
    foreground: bool = False

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    def key(self) -> str:
        return f"{self.room}:{self.table_name or self.handle}"


# ---------------------------------------------------------------------------
# Reconnaissance des titres de fenetre
# ---------------------------------------------------------------------------

@dataclass
class RoomPattern:
    room: str
    #: le titre doit contenir l'un de ces motifs pour etre considere comme table
    matchers: List[re.Pattern]
    #: extraction du nom de table (groupe 'name') et eventuellement 'stake'
    extractors: List[re.Pattern] = field(default_factory=list)
    #: motifs a exclure (lobby, caisse, etc.)
    excludes: List[re.Pattern] = field(default_factory=list)


ROOM_PATTERNS: List[RoomPattern] = [
    RoomPattern(
        room="PokerStars",
        matchers=[re.compile(r"(?:No Limit|Pot Limit|Limit)\s+Hold'?em", re.I),
                  re.compile(r"Omaha", re.I),
                  re.compile(r"Tournament\s+\d+", re.I)],
        extractors=[
            re.compile(r"^(?P<name>.+?)\s+-\s+(?P<stake>[$€£][\d.,]+/[$€£][\d.,]+)", re.I),
            re.compile(r"^Tournament\s+(?P<name>\d+\s+Table\s+\d+)", re.I),
            re.compile(r"^(?P<name>[^-]+)", re.I),
        ],
        excludes=[re.compile(r"Lobby|Caisse|Cashier|Tournament Lobby", re.I)],
    ),
    RoomPattern(
        room="Winamax",
        matchers=[re.compile(r"Holdem|Omaha|Expresso", re.I)],
        extractors=[
            re.compile(r"^(?P<name>.+?)\s+/\s+(?P<stake>[\d.,]+\s*€?\s*/\s*[\d.,]+\s*€?)", re.I),
            re.compile(r"^(?P<name>[^-/]+)"),
        ],
        excludes=[re.compile(r"Winamax\.fr$|Lobby", re.I)],
    ),
    RoomPattern(
        room="GGPoker",
        matchers=[re.compile(r"NLH|PLO|Rush|Hold'?em", re.I)],
        extractors=[re.compile(r"^(?P<name>[^-]+)")],
        excludes=[re.compile(r"Lobby|Shop|Cashier", re.I)],
    ),
    RoomPattern(
        room="PartyPoker",
        matchers=[re.compile(r"Hold'?em|Omaha", re.I)],
        extractors=[re.compile(r"^(?P<name>[^-]+)")],
        excludes=[re.compile(r"Lobby|Cashier", re.I)],
    ),
]

RE_MAX_SEATS = re.compile(r"(\d+)\s*-?\s*max", re.I)


def identify_table(title: str) -> Optional[TableWindow]:
    """Analyse un titre de fenetre et retourne une table identifiee, ou None."""
    title = (title or "").strip()
    if len(title) < 3:
        return None
    for pattern in ROOM_PATTERNS:
        if any(x.search(title) for x in pattern.excludes):
            continue
        if not any(m.search(title) for m in pattern.matchers):
            continue
        name, stake = title, ""
        for ex in pattern.extractors:
            m = ex.search(title)
            if m:
                name = (m.groupdict().get("name") or title).strip()
                stake = (m.groupdict().get("stake") or "").strip()
                break
        seats = RE_MAX_SEATS.search(title)
        return TableWindow(handle=0, title=title, room=pattern.room, table_name=name,
                           stake=stake, max_seats=int(seats.group(1)) if seats else 0)
    return None


# ---------------------------------------------------------------------------
# Enumeration des fenetres
# ---------------------------------------------------------------------------

class TableTracker:
    """Retourne la liste des tables de poker actuellement ouvertes."""

    def __init__(self) -> None:
        self._extra_windows: List[Callable[[], List[TableWindow]]] = []

    def register_source(self, source: Callable[[], List[TableWindow]]) -> None:
        """Ajoute une source de tables (ex: table de demonstration interne)."""
        self._extra_windows.append(source)

    # ------------------------------------------------------------------
    def list_tables(self) -> List[TableWindow]:
        tables = self._list_windows_tables()
        for source in self._extra_windows:
            try:
                tables.extend(source())
            except Exception:
                continue
        return tables

    def _list_windows_tables(self) -> List[TableWindow]:
        if not IS_WINDOWS:
            return []
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        result: List[TableWindow] = []
        foreground = user32.GetForegroundWindow()

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            table = identify_table(buf.value)
            if table is None:
                return True
            rect = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return True
            point = wintypes.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(point))
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width < 200 or height < 150:          # trop petit pour etre une table
                return True
            table.handle = int(hwnd)
            table.x, table.y = int(point.x), int(point.y)
            table.width, table.height = int(width), int(height)
            table.foreground = int(hwnd) == int(foreground)
            result.append(table)
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def is_window_alive(handle: int) -> bool:
        if not IS_WINDOWS or not handle:
            return True
        import ctypes
        return bool(ctypes.windll.user32.IsWindow(handle))

    @staticmethod
    def window_rect(handle: int) -> Optional[tuple[int, int, int, int]]:
        if not IS_WINDOWS or not handle:
            return None
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.GetClientRect(handle, ctypes.byref(rect)):
            return None
        point = wintypes.POINT(0, 0)
        user32.ClientToScreen(handle, ctypes.byref(point))
        return (int(point.x), int(point.y), int(rect.right - rect.left),
                int(rect.bottom - rect.top))
