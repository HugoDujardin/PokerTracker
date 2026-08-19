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
    tournament_ids: Sequence[str] = ()
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_players: Optional[int] = None
    max_players: Optional[int] = None
    hero_only: bool = False
    last_n_hands: Optional[int] = None
    #: 'real' (defaut) exclut l'argent fictif, 'play' ne garde que lui,
    #: 'all' ne filtre pas
    money: str = "real"

    def is_empty(self) -> bool:
        """Aucun critere du tout."""
        return not self.games and self.uses_totals()

    def uses_totals(self) -> bool:
        """Vrai si les cumuls precalcules suffisent a repondre.

        Les cumuls sont stockes par joueur *et par variante*: un filtre sur
        la variante (exclure l'Omaha, par exemple) reste donc sur le chemin
        rapide utilise par le HUD.
        """
        return self.money == "real" and not any(
            (self.rooms, self.formats, self.stakes, self.positions, self.tables,
             self.tournament_ids, self.date_from, self.date_to, self.min_players,
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
        inlist("h.tournament_id", self.tournament_ids)
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
        if self.money == "real":
            clauses.append("h.real_money = 1")
        elif self.money == "play":
            clauses.append("h.real_money = 0")
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
        self._totals_need_rebuild = False
        self.migrate()
        if self._totals_need_rebuild:
            self.rebuild_totals()
            self._totals_need_rebuild = False

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
            hands_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(hands)")}
            if "imported_at" not in hands_cols:
                self.conn.execute("ALTER TABLE hands ADD COLUMN imported_at TEXT")
            if "real_money" not in hands_cols:
                self.conn.execute("ALTER TABLE hands ADD COLUMN real_money INTEGER DEFAULT 1")
            tour_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(tournaments)")}
            if tour_cols and "real_money" not in tour_cols:
                self.conn.execute(
                    "ALTER TABLE tournaments ADD COLUMN real_money INTEGER DEFAULT 1")
            existing = {r[1] for r in self.conn.execute("PRAGMA table_info(hand_players)")}
            for col in COUNTERS:
                if col not in existing:
                    self.conn.execute(f"ALTER TABLE hand_players ADD COLUMN {col} INTEGER DEFAULT 0")
            for col in FLOAT_COUNTERS:
                if col not in existing:
                    self.conn.execute(f"ALTER TABLE hand_players ADD COLUMN {col} REAL DEFAULT 0")
            totals_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(player_totals)")}
            if totals_cols and "game" not in totals_cols:
                # ancienne table (tous jeux confondus): on la reconstruit
                self.conn.execute("DROP TABLE player_totals")
                self.conn.executescript(schema_mod.player_totals_ddl())
                self._totals_need_rebuild = True
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
                      + " WHERE player_id = ? AND game = ?")
        totals: dict[tuple[int, str], list[float]] = {}
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
                                         pot, rake, tournament_id, real_money, hero_id, file_id,
                                         imported_at, raw_text)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (hand.hand_id, hand.room, hand.played_at.isoformat(timespec="seconds"),
                     hand.played_at.timestamp(), hand.game.value, hand.table_format.value,
                     hand.table_name, hand.max_seats, hand.nb_players, float(hand.sb), float(hand.bb),
                     float(hand.ante), hand.currency, stake_label(hand), " ".join(hand.board),
                     float(hand.pot), float(hand.rake), hand.tournament_id,
                     int(hand.real_money), hero_id, file_id,
                     datetime.now().isoformat(timespec="seconds"), hand.raw_text),
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
                    if hand.real_money:
                        # les cumuls precalcules (utilises par le HUD et les
                        # ecrans sans filtre) ne comptent que l'argent reel,
                        # et restent separes par variante
                        key = (pid, hand.game.value)
                        acc = totals.get(key)
                        if acc is None:
                            totals[key] = list(counters_row)
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
                conn.executemany(
                    "INSERT OR IGNORE INTO player_totals(player_id, game) VALUES (?,?)",
                    list(totals))
                conn.executemany(totals_sql,
                                 [acc + [pid, game] for (pid, game), acc in totals.items()])
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
        if not group_by and flt.uses_totals() and player_ids:
            return self._totals(player_ids, flt.games)
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

    def _totals(self, player_ids: Sequence[int], games: Sequence[str] = ()) -> dict:
        cols = ", ".join(f"SUM({c}) AS {c}" for c in ALL_COUNTERS)
        sql = (f"SELECT {cols} FROM player_totals "
               f"WHERE player_id IN ({','.join('?' * len(player_ids))})")
        params = list(player_ids)
        if games:
            sql += f" AND game IN ({','.join('?' * len(games))})"
            params += list(games)
        row = self.conn.execute(sql, params).fetchone()
        return {c: (row[c] or 0) for c in ALL_COUNTERS} if row else {c: 0 for c in ALL_COUNTERS}

    def rebuild_counters(self, progress=None, batch: int = 500) -> int:
        """Recalcule tous les compteurs a partir du texte des mains stockees.

        Utile apres une mise a jour du moteur de statistiques (ajout d'un
        compteur, calcul de l'EV sur une base existante).
        """
        from ..parsers import registry

        total = self.conn.execute("SELECT COUNT(*) FROM hands").fetchone()[0]
        counter_cols = list(ALL_COUNTERS)
        update_sql = ("UPDATE hand_players SET " + ", ".join(f"{c} = ?" for c in counter_cols)
                      + " WHERE hand_id = ? AND player_id = ?")
        done = 0
        offset = 0
        while True:
            rows = list(self.conn.execute(
                "SELECT id, room, raw_text FROM hands ORDER BY id LIMIT ? OFFSET ?",
                (batch, offset)))
            if not rows:
                break
            offset += len(rows)
            updates = []
            for row in rows:
                hands = list(registry.parse_text(row["raw_text"] or ""))
                if not hands:
                    continue
                counters = compute_hand_counters(hands[0])
                for player, values in counters.items():
                    pid = self.player_id(player, row["room"])
                    updates.append([values.get(c, 0) for c in counter_cols] + [row["id"], pid])
                done += 1
            with self._write_lock:
                self.conn.executemany(update_sql, updates)
                self.conn.commit()
            if progress:
                progress(done, total)
        self.rebuild_totals()
        return done

    def rebuild_totals(self) -> None:
        """Recalcule integralement la table de cumuls (maintenance)."""
        cols = ", ".join(ALL_COUNTERS)
        sums = ", ".join(f"SUM(hp.{c})" for c in ALL_COUNTERS)
        with self._write_lock:
            self.conn.execute("DELETE FROM player_totals")
            self.conn.execute(
                f"INSERT INTO player_totals(player_id, game, {cols}) "
                f"SELECT hp.player_id, h.game, {sums} FROM hand_players hp "
                f"JOIN hands h ON h.id = hp.hand_id WHERE h.real_money = 1 "
                f"GROUP BY hp.player_id, h.game")
            self.conn.commit()

    def aggregate_many(self, names: Sequence[str], room: str = "",
                       flt: Optional[Filter] = None) -> dict[str, dict]:
        """Agrege les compteurs de plusieurs joueurs en une seule requete (HUD)."""
        if not names:
            return {}
        flt = flt or Filter()
        if flt.uses_totals():
            cols = ", ".join(f"SUM(t.{c}) AS {c}" for c in ALL_COUNTERS)
            sql = (f"SELECT p.name AS name, {cols} FROM player_totals t "
                   f"JOIN players p ON p.id = t.player_id "
                   f"WHERE p.name IN ({','.join('?' * len(names))})")
            params = list(names)
            if room:
                sql += " AND p.room = ?"
                params.append(room)
            if flt.games:
                sql += f" AND t.game IN ({','.join('?' * len(flt.games))})"
                params += list(flt.games)
            sql += " GROUP BY p.name"
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

    def tournament_hands(self, room: str, tournament_id: str,
                         player_id: Optional[int] = None) -> list[sqlite3.Row]:
        """Mains d'un tournoi, de la plus ancienne a la plus recente."""
        if player_id is None:
            return list(self.conn.execute(
                "SELECT * FROM hands WHERE room = ? AND tournament_id = ? ORDER BY played_ts",
                (room, tournament_id)))
        return list(self.conn.execute(
            "SELECT h.*, hp.position, hp.cards, hp.net, hp.bb_net, hp.stack_bb "
            "FROM hands h JOIN hand_players hp ON hp.hand_id = h.id "
            "WHERE h.room = ? AND h.tournament_id = ? AND hp.player_id = ? "
            "ORDER BY h.played_ts", (room, tournament_id, player_id)))

    def tournament_by_id(self, db_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            f"SELECT t.*, {self.HANDS_SUBQUERY} AS hands_played FROM tournaments t WHERE t.id = ?",
            (db_id,)).fetchone()

    def last_tournament(self, flt: Optional[Filter] = None) -> Optional[sqlite3.Row]:
        rows = self.tournaments(flt, limit=1)
        return rows[0] if rows else None

    def hand_by_id(self, db_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM hands WHERE id = ?", (db_id,)).fetchone()

    def hand_players(self, db_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT hp.*, p.name FROM hand_players hp JOIN players p ON p.id = hp.player_id "
            "WHERE hp.hand_id = ? ORDER BY hp.seat_no", (db_id,)))

    def recent_table_hands(self, limit: int = 12, max_age_hours: float = 0) -> list[sqlite3.Row]:
        """Derniere main connue de chaque table, la plus recente d'abord.

        Sert a reconstruire l'etat des tables au demarrage: le HUD peut
        s'afficher immediatement, sans attendre la fin de la main suivante.
        """
        params: list = []
        age = ""
        if max_age_hours:
            age = "WHERE played_ts >= ?"
            params.append(datetime.now().timestamp() - max_age_hours * 3600)
        sql = (f"SELECT h.* FROM hands h JOIN ("
               f"  SELECT room, table_name, MAX(played_ts) AS ts FROM hands {age} "
               f"  GROUP BY room, table_name) m "
               f"ON h.room = m.room AND h.table_name = m.table_name AND h.played_ts = m.ts "
               f"ORDER BY h.played_ts DESC LIMIT ?")
        return list(self.conn.execute(sql, params + [limit]))

    def heroes(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM players WHERE is_hero = 1 ORDER BY name"))

    def bankroll_curve(self, player_id: int, flt: Optional[Filter] = None) -> list[tuple]:
        """Courbe cumulee d'un joueur.

        Retourne (numero de main, horodatage, gains, gains en bb, gains
        ajustes a l'equite, gains ajustes en bb).
        """
        flt = flt or Filter()
        where, params = flt.where()
        sql = (f"SELECT h.played_ts, hp.net, hp.bb_net, hp.ev_net, hp.ev_bb FROM hand_players hp "
               f"JOIN hands h ON h.id = hp.hand_id WHERE {where} AND hp.player_id = ? "
               f"ORDER BY h.played_ts")
        cum_money = cum_bb = cum_ev = cum_ev_bb = 0.0
        out = []
        for i, row in enumerate(self.conn.execute(sql, params + [player_id]), start=1):
            cum_money += row["net"] or 0.0
            cum_bb += row["bb_net"] or 0.0
            cum_ev += row["ev_net"] or 0.0
            cum_ev_bb += row["ev_bb"] or 0.0
            out.append((i, row["played_ts"], cum_money, cum_bb, cum_ev, cum_ev_bb))
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

    # ---------------------------------------------------------- tournois
    def insert_tournaments(self, results, bubble_ratio: float = 0.15) -> int:
        """Enregistre des resumes de tournoi (ignore ceux deja connus).

        `bubble_ratio` est la part du champ payee, utilisee pour estimer la
        bulle quand le resume ne precise pas le nombre de places payees.
        """
        inserted = 0
        with self._write_lock:
            for r in results:
                cost = float(r.cost)
                won = float(r.won)
                paid = max(1, round(r.entrants * bubble_ratio)) if r.entrants else 0
                bubble = bool(paid and not r.itm and r.finish_place
                              and paid < r.finish_place <= paid * 1.10 + 1)
                started = r.started_at
                cur = self.conn.execute(
                    """INSERT OR IGNORE INTO tournaments(
                           room, tournament_id, name, fmt, buyin, fee, bounty_buyin, currency,
                           started_at, started_ts, entrants, finish_place, prize, bounty_won,
                           cost, won, profit, itm, bubble, paid_places, real_money,
                           imported_at, raw_text)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.room, r.tournament_id, r.name, r.fmt, float(r.buyin), float(r.fee),
                     float(r.bounty_buyin), r.currency,
                     started.isoformat(timespec="seconds") if started else None,
                     started.timestamp() if started else 0.0,
                     r.entrants, r.finish_place, float(r.prize), float(r.bounty_won),
                     cost, won, won - cost, int(r.itm), int(bubble), paid,
                     int(getattr(r, "real_money", True)),
                     datetime.now().isoformat(timespec="seconds"), r.raw_text))
                if cur.rowcount:
                    inserted += 1
            self.conn.commit()
        return inserted

    #: nombre de mains jouees dans le tournoi, calcule a la lecture
    HANDS_SUBQUERY = ("(SELECT COUNT(*) FROM hands h WHERE h.tournament_id = t.tournament_id "
                      "AND h.room = t.room)")

    #: les tournois en argent fictif sont exclus du bilan financier par defaut

    def tournaments(self, flt: Optional[Filter] = None, limit: int = 2000) -> list[sqlite3.Row]:
        where, params = self._tournament_where(flt)
        return list(self.conn.execute(
            f"SELECT t.*, {self.HANDS_SUBQUERY} AS hands_played FROM tournaments t "
            f"WHERE {where} ORDER BY t.started_ts DESC LIMIT ?", params + [limit]))

    @staticmethod
    def _tournament_where(flt: Optional[Filter]) -> tuple[str, list]:
        flt = flt or Filter()
        clauses: list[str] = []
        params: list = []
        if flt.rooms:
            clauses.append(f"room IN ({','.join('?' * len(flt.rooms))})")
            params.extend(flt.rooms)
        if flt.formats:
            clauses.append(f"fmt IN ({','.join('?' * len(flt.formats))})")
            params.extend(flt.formats)
        if flt.date_from:
            clauses.append("started_ts >= ?")
            params.append(flt.date_from.timestamp())
        if flt.date_to:
            clauses.append("started_ts <= ?")
            params.append(flt.date_to.timestamp())
        if flt.money == "real":
            clauses.append("real_money = 1")
        elif flt.money == "play":
            clauses.append("real_money = 0")
        return (" AND ".join(clauses) if clauses else "1=1"), params

    def tournament_stats(self, flt: Optional[Filter] = None) -> dict:
        """Bilan financier des tournois: inscriptions, ITM, bulles, ROI..."""
        where, params = self._tournament_where(flt)
        row = self.conn.execute(
            f"""SELECT COUNT(*) AS entries, SUM(cost) AS cost, SUM(won) AS won,
                       SUM(profit) AS profit, SUM(itm) AS itm, SUM(bubble) AS bubbles,
                       AVG(buyin + fee + bounty_buyin) AS avg_buyin,
                       MAX(profit) AS best, MIN(profit) AS worst,
                       SUM(CASE WHEN finish_place = 1 THEN 1 ELSE 0 END) AS wins,
                       AVG(CASE WHEN entrants > 0 THEN 100.0 * finish_place / entrants END)
                           AS avg_place_pct,
                       SUM({self.HANDS_SUBQUERY}) AS hands
                FROM tournaments t WHERE {where}""", params).fetchone()
        entries = row["entries"] or 0
        cost = row["cost"] or 0.0
        return {
            "entries": entries,
            "cost": cost,
            "won": row["won"] or 0.0,
            "profit": row["profit"] or 0.0,
            "itm": row["itm"] or 0,
            "itm_pct": 100.0 * (row["itm"] or 0) / entries if entries else 0.0,
            "bubbles": row["bubbles"] or 0,
            "bubble_pct": 100.0 * (row["bubbles"] or 0) / entries if entries else 0.0,
            "roi": 100.0 * (row["profit"] or 0.0) / cost if cost else 0.0,
            "avg_buyin": row["avg_buyin"] or 0.0,
            "best": row["best"] or 0.0,
            "worst": row["worst"] or 0.0,
            "wins": row["wins"] or 0,
            "avg_place_pct": row["avg_place_pct"] or 0.0,
            "hands": row["hands"] or 0,
        }

    def tournament_curve(self, flt: Optional[Filter] = None) -> list[tuple]:
        """Courbe cumulee du profit en tournoi (numero, horodatage, profit)."""
        where, params = self._tournament_where(flt)
        cumul = 0.0
        out = []
        for i, row in enumerate(self.conn.execute(
                f"SELECT started_ts, profit FROM tournaments WHERE {where} ORDER BY started_ts",
                params), start=1):
            cumul += row["profit"] or 0.0
            out.append((i, row["started_ts"], cumul, cumul))
        return out

    def tournament_groups(self, column: str, flt: Optional[Filter] = None) -> dict:
        allowed = {"fmt", "room", "currency"}
        if column not in allowed:
            raise ValueError(f"colonne non autorisee: {column}")
        where, params = self._tournament_where(flt)
        out = {}
        for row in self.conn.execute(
                f"""SELECT {column} AS grp, COUNT(*) AS entries, SUM(cost) AS cost,
                           SUM(profit) AS profit, SUM(itm) AS itm, SUM(bubble) AS bubbles
                    FROM tournaments WHERE {where} GROUP BY grp""", params):
            entries = row["entries"] or 0
            cost = row["cost"] or 0.0
            out[row["grp"] or "-"] = {
                "entries": entries, "cost": cost, "profit": row["profit"] or 0.0,
                "itm": row["itm"] or 0,
                "itm_pct": 100.0 * (row["itm"] or 0) / entries if entries else 0.0,
                "bubbles": row["bubbles"] or 0,
                "roi": 100.0 * (row["profit"] or 0.0) / cost if cost else 0.0,
            }
        return out

    # ---------------------------------------------------------- bankroll
    def add_bankroll_entry(self, kind: str, amount: float, note: str = "",
                           when: Optional[datetime] = None, currency: str = "EUR") -> int:
        when = when or datetime.now()
        with self._write_lock:
            cur = self.conn.execute(
                "INSERT INTO bankroll_entries(date, ts, kind, amount, currency, note) "
                "VALUES (?,?,?,?,?,?)",
                (when.isoformat(timespec="seconds"), when.timestamp(), kind, float(amount),
                 currency, note))
            self.conn.commit()
        return int(cur.lastrowid)

    def bankroll_entries(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM bankroll_entries ORDER BY ts DESC"))

    def delete_bankroll_entry(self, entry_id: int) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM bankroll_entries WHERE id = ?", (entry_id,))
            self.conn.commit()

    def bankroll_summary(self, hero_id: Optional[int] = None) -> dict:
        """Etat de la bankroll: mouvements + resultats cash + resultats tournois."""
        movements = self.conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind = 'retrait' THEN -amount ELSE amount END), 0) "
            "FROM bankroll_entries").fetchone()[0] or 0.0
        cash = 0.0
        if hero_id:
            cash = self.conn.execute(
                "SELECT COALESCE(SUM(hp.net), 0) FROM hand_players hp "
                "JOIN hands h ON h.id = hp.hand_id "
                "WHERE hp.player_id = ? AND h.fmt = 'cash' AND h.real_money = 1",
                (hero_id,)).fetchone()[0] or 0.0
        tournaments = self.conn.execute(
            "SELECT COALESCE(SUM(profit), 0) FROM tournaments "
            "WHERE real_money = 1").fetchone()[0] or 0.0
        return {
            "movements": movements,
            "cash": cash,
            "tournaments": tournaments,
            "total": movements + cash + tournaments,
        }

    def bankroll_timeline(self, hero_id: Optional[int] = None) -> list[tuple]:
        """Evolution de la bankroll dans le temps (mouvements, cash, tournois)."""
        events: list[tuple[float, float]] = []
        for row in self.conn.execute("SELECT ts, kind, amount FROM bankroll_entries"):
            amount = -row["amount"] if row["kind"] == "retrait" else row["amount"]
            events.append((row["ts"], amount))
        for row in self.conn.execute(
                "SELECT started_ts, profit FROM tournaments WHERE real_money = 1"):
            events.append((row["started_ts"] or 0.0, row["profit"] or 0.0))
        if hero_id:
            for row in self.conn.execute(
                    "SELECT h.played_ts, hp.net FROM hand_players hp "
                    "JOIN hands h ON h.id = hp.hand_id "
                    "WHERE hp.player_id = ? AND h.fmt = 'cash' AND h.real_money = 1",
                    (hero_id,)):
                events.append((row["played_ts"], row["net"] or 0.0))
        events.sort(key=lambda e: e[0])
        cumul = 0.0
        out = []
        for i, (ts, amount) in enumerate(events, start=1):
            cumul += amount
            out.append((i, ts, cumul, cumul))
        return out

    # ------------------------------------------------------- profils HUD
    def save_profile(self, name: str, payload: str) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO hud_profiles(name, payload) VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET payload = excluded.payload", (name, payload))
            self.conn.commit()

    def load_profiles(self) -> dict[str, str]:
        return {r["name"]: r["payload"] for r in self.conn.execute("SELECT * FROM hud_profiles")}
