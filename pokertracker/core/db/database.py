"""Acces a la base SQLite du tracker."""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..models import Hand
from ..stats.counters import ALL_COUNTERS, COUNTERS, FLOAT_COUNTERS, compute_hand_counters
from . import schema as schema_mod


def stake_label(hand: Hand) -> str:
    if hand.table_format.value != "cash":
        return f"{hand.table_format.value.upper()} {hand.buyin or ''}".strip()
    def fmt(x):
        s = f"{float(x):.2f}".rstrip("0").rstrip(".")
        return s
    return f"{fmt(hand.sb)}/{fmt(hand.bb)}"


@dataclass
class Filter:
    """Filtre applique aux agregations (rapports, HUD, graphiques)."""

    rooms: Sequence[str] = ()
    formats: Sequence[str] = ()
    games: Sequence[str] = ()
    stakes: Sequence[str] = ()
    positions: Sequence[str] = ()
    tables: Sequence[str] = ()
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_players: Optional[int] = None
    max_players: Optional[int] = None
    hero_only: bool = False
    last_n_hands: Optional[int] = None

    def is_empty(self) -> bool:
        """Aucun critere: les cumuls precalcules peuvent etre utilises."""
        return not any((self.rooms, self.formats, self.games, self.stakes, self.positions,
                        self.tables, self.date_from, self.date_to, self.min_players,
                        self.max_players, self.hero_only, self.last_n_hands))

    def where(self) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        def inlist(col: str, values: Sequence[str]):
            if values:
                clauses.append(f"{col} IN ({','.join('?' * len(values))})")
                params.extend(values)
        inlist("h.room", self.rooms)
        inlist("h.fmt", self.formats)
        inlist("h.game", self.games)
        inlist("h.stake", self.stakes)
        inlist("h.table_name", self.tables)
        inlist("hp.position", self.positions)
        if self.date_from:
            clauses.append("h.played_ts >= ?")
            params.append(self.date_from.timestamp())
        if self.date_to:
            clauses.append("h.played_ts <= ?")
            params.append(self.date_to.timestamp())
        if self.min_players:
            clauses.append("h.nb_players >= ?")
            params.append(self.min_players)
        if self.max_players:
            clauses.append("h.nb_players <= ?")
            params.append(self.max_players)
        if self.hero_only:
            clauses.append("hp.is_hero = 1")
        return (" AND ".join(clauses) if clauses else "1=1"), params


class Database:
    """Couche d'acces SQLite, utilisable depuis plusieurs threads."""

    def __init__(self, path: str | os.PathLike = "pokertracker.db") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._player_ids: dict[tuple[str, str], int] = {}
        self.migrate()

    # ------------------------------------------------------------ connexion
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA cache_size=-64000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -------------------------------------------------------------- schema
    def migrate(self) -> None:
        with self._write_lock:
            self.conn.executescript(schema_mod.full_schema())
            existing = {r[1] for r in self.conn.execute("PRAGMA table_info(hand_players)")}
            for col in COUNTERS:
                if col not in existing:
                    self.conn.execute(f"ALTER TABLE hand_players ADD COLUMN {col} INTEGER DEFAULT 0")
            for col in FLOAT_COUNTERS:
                if col not in existing:
                    self.conn.execute(f"ALTER TABLE hand_players ADD COLUMN {col} REAL DEFAULT 0")
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                              (str(schema_mod.SCHEMA_VERSION),))
            self.conn.commit()

    # ------------------------------------------------------------- joueurs
    def player_id(self, name: str, room: str = "", is_hero: bool = False) -> int:
        key = (name, room)
        cached = self._player_ids.get(key)
        if cached is not None:
            if is_hero:
                self.conn.execute("UPDATE players SET is_hero = 1 WHERE id = ?", (cached,))
            return cached
        row = self.conn.execute("SELECT id FROM players WHERE name = ? AND room = ?",
                                (name, room)).fetchone()
        if row:
            pid = int(row["id"])
            if is_hero:
                self.conn.execute("UPDATE players SET is_hero = 1 WHERE id = ?", (pid,))
        else:
            cur = self.conn.execute(
                "INSERT INTO players(name, room, is_hero, first_seen) VALUES (?,?,?,?)",
                (name, room, int(is_hero), datetime.now().isoformat(timespec="seconds")),
            )
            pid = int(cur.lastrowid)
            self.conn.execute("INSERT OR IGNORE INTO player_totals(player_id) VALUES (?)", (pid,))
        self._player_ids[key] = pid
        return pid

    def find_players(self, term: str = "", limit: int = 200) -> list[sqlite3.Row]:
        sql = ("SELECT p.*, (SELECT COUNT(*) FROM hand_players hp WHERE hp.player_id = p.id) AS hands "
               "FROM players p WHERE p.name LIKE ? ORDER BY hands DESC LIMIT ?")
        return list(self.conn.execute(sql, (f"%{term}%", limit)))

    def set_note(self, player_id: int, note: str, color: str = "", label: str = "") -> None:
        with self._write_lock:
            self.conn.execute("UPDATE players SET note = ?, color = ?, label = ? WHERE id = ?",
                              (note, color, label, player_id))
            self.conn.commit()

    def get_player(self, name: str, room: str = "") -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM players WHERE name = ? AND room = ?",
                                 (name, room)).fetchone()

    # --------------------------------------------------------------- import
    def hand_exists(self, hand_id: str, room: str) -> bool:
        return self.conn.execute("SELECT 1 FROM hands WHERE hand_id = ? AND room = ?",
                                 (hand_id, room)).fetchone() is not None

    def insert_hands(self, hands: Iterable[Hand], file_id: Optional[int] = None) -> int:
        """Insere un lot de mains (ignore les doublons). Retourne le nombre insere."""
        inserted = 0
        counter_cols = list(ALL_COUNTERS)
        fixed_cols = [c for c, _ in schema_mod.HAND_PLAYERS_FIXED]
        hp_sql = (f"INSERT OR IGNORE INTO hand_players ({','.join(fixed_cols + counter_cols)}) "
                  f"VALUES ({','.join('?' * (len(fixed_cols) + len(counter_cols)))})")
        totals_sql = ("UPDATE player_totals SET "
                      + ", ".join(f"{c} = {c} + ?" for c in counter_cols)
                      + " WHERE player_id = ?")
        totals: dict[int, list[float]] = {}
        last_seen: dict[int, str] = {}
        tables_seen: dict[tuple[str, str], str] = {}
        with self._write_lock:
            conn = self.conn
            for hand in hands:
                if self.hand_exists(hand.hand_id, hand.room):
                    continue
                hero_id = self.player_id(hand.hero, hand.room, True) if hand.hero else None
                cur = conn.execute(
                    """INSERT INTO hands(hand_id, room, played_at, played_ts, game, fmt, table_name,
                                         max_seats, nb_players, sb, bb, ante, currency, stake, board,
                                         pot, rake, tournament_id, hero_id, file_id, raw_text)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (hand.hand_id, hand.room, hand.played_at.isoformat(timespec="seconds"),
                     hand.played_at.timestamp(), hand.game.value, hand.table_format.value,
                     hand.table_name, hand.max_seats, hand.nb_players, float(hand.sb), float(hand.bb),
                     float(hand.ante), hand.currency, stake_label(hand), " ".join(hand.board),
                     float(hand.pot), float(hand.rake), hand.tournament_id, hero_id, file_id,
                     hand.raw_text),
                )
                db_hand_id = int(cur.lastrowid)
                counters = compute_hand_counters(hand)
                bb = float(hand.big_blind() or 1)
                rows = []
                for seat in hand.seats:
                    pid = self.player_id(seat.player, hand.room, seat.is_hero)
                    row = counters.get(seat.player, {})
                    values = [db_hand_id, pid, seat.seat_no, seat.position, float(seat.stack),
                              float(seat.stack) / bb if bb else 0.0, " ".join(seat.cards),
                              int(seat.is_hero), int(seat.showed), float(seat.net), float(seat.won)]
                    counters_row = [row.get(c, 0) for c in counter_cols]
                    values += counters_row
                    rows.append(values)
                    acc = totals.get(pid)
                    if acc is None:
                        totals[pid] = list(counters_row)
                    else:
                        for i, v in enumerate(counters_row):
                            acc[i] += v
                conn.executemany(hp_sql, rows)
                played = hand.played_at.isoformat(timespec="seconds")
                tables_seen[(hand.room, hand.table_name)] = played
                for seat in hand.seats:
                    pid = self.player_id(seat.player, hand.room)
                    if last_seen.get(pid, "") < played:
                        last_seen[pid] = played
                inserted += 1
            if totals:
                conn.executemany("INSERT OR IGNORE INTO player_totals(player_id) VALUES (?)",
                                 [(pid,) for pid in totals])
                conn.executemany(totals_sql, [acc + [pid] for pid, acc in totals.items()])
            if last_seen:
                conn.executemany("UPDATE players SET last_seen = ? WHERE id = ?",
                                 [(when, pid) for pid, when in last_seen.items()])
            if tables_seen:
                conn.executemany(
                    "INSERT INTO tables_seen(room, name, last_seen) VALUES (?,?,?) "
                    "ON CONFLICT(room, name) DO UPDATE SET last_seen = excluded.last_seen",
                    [(room, name, when) for (room, name), when in tables_seen.items()])
            conn.commit()
        return inserted

    # -------------------------------------------------------------- fichiers
    def file_state(self, path: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()

    def upsert_file(self, path: str, room: str, size: int, mtime: float, offset: int,
                    hands_count: int) -> int:
        with self._write_lock:
            self.conn.execute(
                """INSERT INTO files(path, room, size, mtime, offset, hands_count, imported_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                        offset=excluded.offset, room=excluded.room,
                        hands_count=files.hands_count + excluded.hands_count,
                        imported_at=excluded.imported_at""",
                (path, room, size, mtime, offset, hands_count,
                 datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()
        row = self.file_state(path)
        return int(row["id"]) if row else 0

    # ------------------------------------------------------------ agregation
    def aggregate(self, player_ids: Sequence[int] = (), flt: Optional[Filter] = None,
                  group_by: str = "") -> dict:
        """Somme les compteurs pour un ou plusieurs joueurs.

        `group_by` accepte une colonne SQL (ex: 'hp.position', 'h.stake') et
        retourne alors un dictionnaire {valeur: compteurs}.
        """
        flt = flt or Filter()
        if not group_by and flt.is_empty() and player_ids:
            return self._totals(player_ids)
        where, params = flt.where()
        if player_ids:
            where += f" AND hp.player_id IN ({','.join('?' * len(player_ids))})"
            params = params + list(player_ids)
        cols = ", ".join(f"SUM(hp.{c}) AS {c}" for c in ALL_COUNTERS)
        if group_by:
            sql = (f"SELECT {group_by} AS grp, {cols} FROM hand_players hp "
                   f"JOIN hands h ON h.id = hp.hand_id WHERE {where} GROUP BY grp")
            out = {}
            for row in self.conn.execute(sql, params):
                out[row["grp"]] = {c: row[c] or 0 for c in ALL_COUNTERS}
            return out
        sql = (f"SELECT {cols} FROM hand_players hp JOIN hands h ON h.id = hp.hand_id "
               f"WHERE {where}")
        row = self.conn.execute(sql, params).fetchone()
        return {c: (row[c] or 0) for c in ALL_COUNTERS} if row else {c: 0 for c in ALL_COUNTERS}

    def _totals(self, player_ids: Sequence[int]) -> dict:
        cols = ", ".join(f"SUM({c}) AS {c}" for c in ALL_COUNTERS)
        sql = (f"SELECT {cols} FROM player_totals "
               f"WHERE player_id IN ({','.join('?' * len(player_ids))})")
        row = self.conn.execute(sql, list(player_ids)).fetchone()
        return {c: (row[c] or 0) for c in ALL_COUNTERS} if row else {c: 0 for c in ALL_COUNTERS}

    def rebuild_totals(self) -> None:
        """Recalcule integralement la table de cumuls (maintenance)."""
        cols = ", ".join(ALL_COUNTERS)
        sums = ", ".join(f"SUM({c})" for c in ALL_COUNTERS)
        with self._write_lock:
            self.conn.execute("DELETE FROM player_totals")
            self.conn.execute(
                f"INSERT INTO player_totals(player_id, {cols}) "
                f"SELECT player_id, {sums} FROM hand_players GROUP BY player_id")
            self.conn.commit()

    def aggregate_many(self, names: Sequence[str], room: str = "",
                       flt: Optional[Filter] = None) -> dict[str, dict]:
        """Agrege les compteurs de plusieurs joueurs en une seule requete (HUD)."""
        if not names:
            return {}
        flt = flt or Filter()
        if flt.is_empty():
            cols = ", ".join(f"t.{c}" for c in ALL_COUNTERS)
            sql = (f"SELECT p.name AS name, {cols} FROM player_totals t "
                   f"JOIN players p ON p.id = t.player_id "
                   f"WHERE p.name IN ({','.join('?' * len(names))})")
            params = list(names)
            if room:
                sql += " AND p.room = ?"
                params.append(room)
            return {row["name"]: {c: (row[c] or 0) for c in ALL_COUNTERS}
                    for row in self.conn.execute(sql, params)}
        where, params = flt.where()
        placeholders = ",".join("?" * len(names))
        where += f" AND p.name IN ({placeholders})"
        params = params + list(names)
        if room:
            where += " AND p.room = ?"
            params.append(room)
        cols = ", ".join(f"SUM(hp.{c}) AS {c}" for c in ALL_COUNTERS)
        sql = (f"SELECT p.name AS name, {cols} FROM hand_players hp "
               f"JOIN hands h ON h.id = hp.hand_id JOIN players p ON p.id = hp.player_id "
               f"WHERE {where} GROUP BY p.name")
        out: dict[str, dict] = {}
        for row in self.conn.execute(sql, params):
            out[row["name"]] = {c: (row[c] or 0) for c in ALL_COUNTERS}
        return out

    # ------------------------------------------------------------- requetes
    def hands_of_player(self, player_id: int, flt: Optional[Filter] = None,
                        limit: int = 500, offset: int = 0) -> list[sqlite3.Row]:
        flt = flt or Filter()
        where, params = flt.where()
        sql = (f"SELECT h.*, hp.position, hp.cards, hp.net, hp.won, hp.is_hero "
               f"FROM hands h JOIN hand_players hp ON h.id = hp.hand_id "
               f"WHERE {where} AND hp.player_id = ? ORDER BY h.played_ts DESC LIMIT ? OFFSET ?")
        return list(self.conn.execute(sql, params + [player_id, limit, offset]))

    def hand_by_id(self, db_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM hands WHERE id = ?", (db_id,)).fetchone()

    def hand_players(self, db_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT hp.*, p.name FROM hand_players hp JOIN players p ON p.id = hp.player_id "
            "WHERE hp.hand_id = ? ORDER BY hp.seat_no", (db_id,)))

    def heroes(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM players WHERE is_hero = 1 ORDER BY name"))

    def bankroll_curve(self, player_id: int, flt: Optional[Filter] = None) -> list[tuple]:
        """Courbe cumulee (timestamp, gains, gains en bb) pour un joueur."""
        flt = flt or Filter()
        where, params = flt.where()
        sql = (f"SELECT h.played_ts, hp.net, hp.bb_net FROM hand_players hp "
               f"JOIN hands h ON h.id = hp.hand_id WHERE {where} AND hp.player_id = ? "
               f"ORDER BY h.played_ts")
        cum_money = 0.0
        cum_bb = 0.0
        out = []
        for i, row in enumerate(self.conn.execute(sql, params + [player_id]), start=1):
            cum_money += row["net"] or 0.0
            cum_bb += row["bb_net"] or 0.0
            out.append((i, row["played_ts"], cum_money, cum_bb))
        return out

    def distinct(self, column: str) -> list[str]:
        allowed = {"room", "stake", "fmt", "game", "table_name", "currency"}
        if column not in allowed:
            raise ValueError(f"colonne non autorisee: {column}")
        return [r[0] for r in self.conn.execute(
            f"SELECT DISTINCT {column} FROM hands WHERE {column} IS NOT NULL AND {column} <> '' "
            f"ORDER BY {column}")]

    def counts(self) -> dict:
        c = self.conn
        return {
            "hands": c.execute("SELECT COUNT(*) FROM hands").fetchone()[0],
            "players": c.execute("SELECT COUNT(*) FROM players").fetchone()[0],
            "files": c.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        }

    # ------------------------------------------------------- profils HUD
    def save_profile(self, name: str, payload: str) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO hud_profiles(name, payload) VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET payload = excluded.payload", (name, payload))
            self.conn.commit()

    def load_profiles(self) -> dict[str, str]:
        return {r["name"]: r["payload"] for r in self.conn.execute("SELECT * FROM hud_profiles")}
