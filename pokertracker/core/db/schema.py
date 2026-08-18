"""Generation du schema SQLite.

Les colonnes de compteurs de `hand_players` sont derivees de la liste
`counters.ALL_COUNTERS`: ajouter un compteur suffit a faire evoluer le
schema (voir `Database.migrate`).
"""
from __future__ import annotations

from ..stats.counters import COUNTERS, FLOAT_COUNTERS

SCHEMA_VERSION = 4

BASE_TABLES = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    room        TEXT,
    size        INTEGER DEFAULT 0,
    mtime       REAL DEFAULT 0,
    offset      INTEGER DEFAULT 0,
    hands_count INTEGER DEFAULT 0,
    imported_at TEXT
);

CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    room       TEXT NOT NULL DEFAULT '',
    is_hero    INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen  TEXT,
    note       TEXT DEFAULT '',
    color      TEXT DEFAULT '',
    label      TEXT DEFAULT '',
    UNIQUE(name, room)
);

CREATE TABLE IF NOT EXISTS hands (
    id            INTEGER PRIMARY KEY,
    hand_id       TEXT NOT NULL,
    room          TEXT NOT NULL,
    played_at     TEXT NOT NULL,
    played_ts     REAL NOT NULL,
    game          TEXT,
    fmt           TEXT,
    table_name    TEXT,
    max_seats     INTEGER,
    nb_players    INTEGER,
    sb            REAL,
    bb            REAL,
    ante          REAL,
    currency      TEXT,
    stake         TEXT,
    board         TEXT,
    pot           REAL,
    rake          REAL,
    tournament_id TEXT,
    hero_id       INTEGER,
    file_id       INTEGER,
    raw_text      TEXT,
    UNIQUE(hand_id, room)
);

CREATE TABLE IF NOT EXISTS tables_seen (
    id        INTEGER PRIMARY KEY,
    room      TEXT,
    name      TEXT,
    last_seen TEXT,
    UNIQUE(room, name)
);

CREATE TABLE IF NOT EXISTS hud_profiles (
    id      INTEGER PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hands_ts     ON hands(played_ts);
CREATE INDEX IF NOT EXISTS idx_hands_room   ON hands(room);
CREATE INDEX IF NOT EXISTS idx_hands_table  ON hands(table_name);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(name);
"""

HAND_PLAYERS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_hp_player ON hand_players(player_id);
CREATE INDEX IF NOT EXISTS idx_hp_hand   ON hand_players(hand_id);
CREATE INDEX IF NOT EXISTS idx_hp_pos    ON hand_players(position);
"""

HAND_PLAYERS_FIXED = [
    ("hand_id", "INTEGER NOT NULL"),
    ("player_id", "INTEGER NOT NULL"),
    ("seat_no", "INTEGER"),
    ("position", "TEXT"),
    ("stack", "REAL"),
    ("stack_bb", "REAL"),
    ("cards", "TEXT"),
    ("is_hero", "INTEGER DEFAULT 0"),
    ("showed", "INTEGER DEFAULT 0"),
    ("net", "REAL DEFAULT 0"),
    ("won", "REAL DEFAULT 0"),
]


def hand_players_ddl() -> str:
    cols = [f"    {name} {decl}" for name, decl in HAND_PLAYERS_FIXED]
    cols += [f"    {c} INTEGER DEFAULT 0" for c in COUNTERS]
    cols += [f"    {c} REAL DEFAULT 0" for c in FLOAT_COUNTERS]
    cols.append("    PRIMARY KEY (hand_id, player_id)")
    return "CREATE TABLE IF NOT EXISTS hand_players (\n" + ",\n".join(cols) + "\n);"


def player_totals_ddl() -> str:
    """Table de cumuls par joueur.

    Elle evite au HUD de resommer des centaines de milliers de lignes a
    chaque main: les compteurs y sont incrementes au fil de l'import.
    """
    cols = ["    player_id INTEGER PRIMARY KEY"]
    cols += [f"    {c} INTEGER DEFAULT 0" for c in COUNTERS]
    cols += [f"    {c} REAL DEFAULT 0" for c in FLOAT_COUNTERS]
    return "CREATE TABLE IF NOT EXISTS player_totals (\n" + ",\n".join(cols) + "\n);"


def full_schema() -> str:
    return (BASE_TABLES + "\n" + hand_players_ddl() + "\n" + HAND_PLAYERS_INDEXES + "\n"
            + player_totals_ddl())
