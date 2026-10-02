"""Product Interaction Ledger.

Append-only event store plus the derived views the Shop Owner Dashboard needs
(detected products, unconfirmed purchases, unaccounted/lost alerts).

SQLite by default so the demo runs with zero infrastructure; every query goes
through :class:`Ledger` so a Postgres/Supabase backend can be dropped in behind
the same API (see ``README`` -> *Swapping the store*).
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .interaction import EventType, InteractionEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    source        TEXT,
    started_at    REAL NOT NULL,
    ended_at      REAL,
    meta          TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id    TEXT PRIMARY KEY,
    product_name  TEXT NOT NULL,
    first_seen    REAL,
    last_seen     REAL,
    seen_count    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uid     TEXT UNIQUE,
    ts            REAL NOT NULL,
    recorded_at   REAL NOT NULL,
    session_id    TEXT,
    type          TEXT NOT NULL,
    product_id    TEXT,
    product_name  TEXT,
    track_id      INTEGER,
    hand_id       INTEGER,
    confidence    REAL,
    x1            REAL, y1 REAL, x2 REAL, y2 REAL,
    state         TEXT,
    state_from    TEXT,
    dwell_ms      INTEGER,
    meta          TEXT,
    resolved      INTEGER DEFAULT 0,
    resolution    TEXT,
    resolved_at   REAL,
    resolved_by   TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_product ON events(product_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
"""

CSV_COLUMNS = [
    "event_uid",
    "ts_iso",
    "session_id",
    "type",
    "product_id",
    "product_name",
    "track_id",
    "hand_id",
    "confidence",
    "x1",
    "y1",
    "x2",
    "y2",
    "state",
    "state_from",
    "dwell_ms",
    "resolved",
    "resolution",
    "resolved_by",
    "meta",
]


@dataclass
class LedgerStats:
    events: int
    picked_up: int
    put_back: int
    placed_in_basket: int
    checked_out: int
    touch: int
    lost: int
    unaccounted: int


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)) + f".{int((ts % 1) * 1000):03d}"


class Ledger:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- sessions
    def open_session(self, session_id: str, source: str, meta: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions(id, source, started_at, meta) VALUES (?,?,?,?)",
                (session_id, source, time.time(), json.dumps(meta or {})),
            )
            self._conn.commit()

    def close_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?", (time.time(), session_id)
            )
            self._conn.commit()

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------- products
    def register_products(self, sightings: Iterable[tuple[str, str, float]]) -> None:
        now = time.time()
        rows = [(pid, name, now, now, 1) for pid, name, _ in sightings]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO products(product_id, product_name, first_seen, last_seen, seen_count)
                VALUES (?,?,?,?,?)
                ON CONFLICT(product_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    seen_count = products.seen_count + 1,
                    product_name = excluded.product_name
                """,
                rows,
            )
            self._conn.commit()

    # ---------------------------------------------------------------- events
    def record_event(
        self,
        event: InteractionEvent,
        product_id: str | None = None,
    ) -> str:
        uid = uuid.uuid4().hex[:16]
        state_from = event.meta.get("state_from")
        meta = json.dumps(event.meta, default=str)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO events(
                    event_uid, ts, recorded_at, session_id, type, product_id, product_name,
                    track_id, hand_id, confidence, x1, y1, x2, y2, state, state_from,
                    dwell_ms, meta)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    uid,
                    event.ts,
                    time.time(),
                    event.session_id,
                    event.type.value,
                    product_id or event.product_id,
                    event.product_name,
                    event.track_id,
                    event.hand_id,
                    event.confidence,
                    event.bbox.x1,
                    event.bbox.y1,
                    event.bbox.x2,
                    event.bbox.y2,
                    event.state.value,
                    state_from,
                    event.dwell_ms,
                    meta,
                ),
            )
            self._conn.commit()
        return uid

    def resolve_event(self, event_uid: str, resolution: str, resolved_by: str = "owner") -> bool:
        with self._lock:
            cur = self._conn.execute(
                """UPDATE events SET resolved = 1, resolution = ?, resolved_at = ?,
                   resolved_by = ? WHERE event_uid = ? AND resolved = 0""",
                (resolution, time.time(), resolved_by, event_uid),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def resolve_open_events(self, product_id: str, track_id: int, resolution: str,
                            resolved_by: str = "owner") -> int:
        """Resolve every unresolved event of a (product, track) pair - used on checkout."""
        with self._lock:
            cur = self._conn.execute(
                """UPDATE events SET resolved = 1, resolution = ?, resolved_at = ?,
                   resolved_by = ? WHERE product_id = ? AND track_id = ? AND resolved = 0""",
                (resolution, time.time(), resolved_by, product_id, track_id),
            )
            self._conn.commit()
            return cur.rowcount

    def query_events(
        self,
        limit: int = 100,
        offset: int = 0,
        type_filter: str | None = None,
        product_id: str | None = None,
        session_id: str | None = None,
        resolved: bool | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if type_filter:
            clauses.append("type = ?")
            params.append(type_filter)
        if product_id:
            clauses.append("product_id = ?")
            params.append(product_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if resolved is not None:
            clauses.append("resolved = ?")
            params.append(1 if resolved else 0)
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM events {where} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", params
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def count_events(self, type_filter: str | None = None) -> int:
        with self._lock:
            if type_filter:
                row = self._conn.execute(
                    "SELECT COUNT(*) c FROM events WHERE type = ?", (type_filter,)
                ).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) c FROM events").fetchone()
        return int(row["c"])

    def stats(self) -> LedgerStats:
        with self._lock:
            rows = self._conn.execute(
                "SELECT type, COUNT(*) c FROM events GROUP BY type"
            ).fetchall()
        counts = {r["type"]: int(r["c"]) for r in rows}
        unaccounted = len(self.unaccounted(grace_seconds=0.0))
        return LedgerStats(
            events=sum(counts.values()),
            picked_up=counts.get(EventType.PICKED_UP.value, 0),
            put_back=counts.get(EventType.PUT_BACK.value, 0),
            placed_in_basket=counts.get(EventType.PLACED_IN_BASKET.value, 0),
            checked_out=counts.get(EventType.CHECKED_OUT.value, 0),
            touch=counts.get(EventType.TOUCH.value, 0),
            lost=counts.get(EventType.TRACK_LOST.value, 0),
            unaccounted=unaccounted,
        )

    # ------------------------------------------------------- derived views
    def open_pickups(self, limit: int = 200, session_id: str | None = None) -> list[dict[str, Any]]:
        """Products the owner still has to act on, whether or not they reached
        the basket.

        Two kinds of outstanding row, both sellable:
          * PICKED_UP with nothing after it - the product is IN_HAND (or the
            camera lost sight of it) and still needs a decision;
          * PLACED_IN_BASKET with no CHECKED_OUT - it reached the basket.

        Ordering uses the autoincrement id rather than the timestamp, because two
        events recorded in the same tick share a timestamp and a `ts >=` test
        would then match the wrong row.
        """
        session_clause = ""
        if session_id:
            session_clause = "AND e.session_id = ?"

        # Bindings must follow the placeholder order in the SQL below:
        #   1  PICKED_UP           (e.type, in-hand branch)
        #   2  PLACED_IN_BASKET    (the "resolved the pickup" list)
        #   3  PUT_BACK            ("            ")
        #   4  CHECKED_OUT         ("            ")
        #   5  TRACK_LOST          ("            ")
        #   6  PLACED_IN_BASKET    (e.type, in-basket branch)
        #   7  CHECKED_OUT         (resolved the basket)
        #   8  [session_id]
        #   9  limit
        params: list[Any] = [
            EventType.PICKED_UP.value,
            EventType.PLACED_IN_BASKET.value,
            EventType.PUT_BACK.value,
            EventType.CHECKED_OUT.value,
            EventType.TRACK_LOST.value,
            EventType.PLACED_IN_BASKET.value,
            EventType.CHECKED_OUT.value,
        ]
        if session_id:
            params.append(session_id)

        sql = f"""
        SELECT e.* FROM events e
        WHERE (
                (e.type = ?
                 AND NOT EXISTS (
                     SELECT 1 FROM events x
                     WHERE x.product_id = e.product_id
                       AND x.track_id = e.track_id
                       AND x.session_id IS e.session_id
                       AND x.id > e.id
                       AND x.type IN (?, ?, ?, ?)
                 ))
             OR (e.type = ?
                 AND NOT EXISTS (
                     SELECT 1 FROM events x
                     WHERE x.product_id = e.product_id
                       AND x.track_id = e.track_id
                       AND x.session_id IS e.session_id
                       AND x.id > e.id
                       AND x.type = ?
                 ))
              )
          {session_clause}
        ORDER BY e.ts ASC
        LIMIT ?
        """
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def basket_holds(self) -> list[dict[str, Any]]:
        """Products that reached IN_BASKET and were never checked out."""
        sql = """
        SELECT e.* FROM events e
        WHERE e.type = ?
          AND e.resolved = 0
          AND e.id = (SELECT MAX(id) FROM events x
                      WHERE x.product_id = e.product_id AND x.session_id IS e.session_id)
        ORDER BY e.ts ASC
        """
        with self._lock:
            rows = self._conn.execute(sql, (EventType.PLACED_IN_BASKET.value,)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def unaccounted(self, grace_seconds: float, session_id: str | None = None) -> list[dict[str, Any]]:
        """Picked-up products that have been gone from the shelf for `grace_seconds`
        without ever being placed in the basket or checked out. These are the
        "appears to have been taken but not accounted for" alerts."""
        cutoff = time.time() - max(0.0, grace_seconds)
        params: list[Any] = [EventType.PICKED_UP.value, cutoff]
        session_clause = ""
        if session_id:
            session_clause = "AND e.session_id = ?"
            params.append(session_id)

        sql = f"""
        SELECT e.* FROM events e
        WHERE e.type = ?
          AND e.ts <= ?
          {session_clause}
AND NOT EXISTS (
              SELECT 1 FROM events x
              WHERE x.product_id = e.product_id
                AND x.track_id = e.track_id
                AND x.session_id IS e.session_id
                AND x.id > e.id
                AND x.type IN (?, ?, ?, ?)
          )
        ORDER BY e.ts DESC
        """
        params.extend(
            [
                EventType.PLACED_IN_BASKET.value,
                EventType.PUT_BACK.value,
                EventType.CHECKED_OUT.value,
                EventType.TRACK_LOST.value,
            ]
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def alerts(self, grace_seconds: float, session_id: str | None = None) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for ev in self.unaccounted(grace_seconds, session_id):
            age = time.time() - ev["ts"]
            alerts.append(
                {
                    "kind": "UNACCOUNTED",
                    "severity": "high",
                    "event_uid": ev["event_uid"],
                    "product_id": ev["product_id"],
                    "product_name": ev["product_name"],
                    "track_id": ev["track_id"],
                    "session_id": ev["session_id"],
                    "ts": ev["ts"],
                    "ts_iso": ev["ts_iso"],
                    "age_s": round(age, 1),
                    "message": (
                        f"{ev['product_name']} was picked up "
                        f"{round(age / 60, 1)} min ago and is not in a basket or a sale."
                    ),
                }
            )
        with self._lock:
            lost_rows = self._conn.execute(
                "SELECT * FROM events WHERE type = ? AND resolved = 0 ORDER BY ts DESC LIMIT 50",
                (EventType.TRACK_LOST.value,),
            ).fetchall()
        for row in lost_rows:
            ev = self._row_to_event(row)
            age = time.time() - ev["ts"]
            alerts.append(
                {
                    "kind": "TRACK_LOST",
                    "severity": "medium",
                    "event_uid": ev["event_uid"],
                    "product_id": ev["product_id"],
                    "product_name": ev["product_name"],
                    "track_id": ev["track_id"],
                    "session_id": ev["session_id"],
                    "ts": ev["ts"],
                    "ts_iso": ev["ts_iso"],
                    "age_s": round(age, 1),
                    "message": (
                        f"{ev['product_name']} stopped being tracked after "
                        f"{round(age, 1)}s - review whether it is still on the shelf."
                    ),
                }
            )
        alerts.sort(key=lambda a: a["ts"], reverse=True)
        return alerts

    def purchased(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM events WHERE type = ?
                   ORDER BY ts DESC LIMIT ?""",
                (EventType.CHECKED_OUT.value, limit),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def product_catalog(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM events e
                         WHERE e.product_id = p.product_id AND e.type = ?) AS picked_up_count,
                       (SELECT COUNT(*) FROM events e
                         WHERE e.product_id = p.product_id AND e.type = ?) AS purchased_count,
                       (SELECT MAX(e.ts) FROM events e
                         WHERE e.product_id = p.product_id AND e.type = ?) AS last_pickup
                  FROM products p
                 ORDER BY p.last_seen DESC
                """,
                (
                    EventType.PICKED_UP.value,
                    EventType.CHECKED_OUT.value,
                    EventType.PICKED_UP.value,
                ),
            ).fetchall()
        return [dict(r) for r in rows]

    def checkout(
        self,
        product_id: str,
        product_name: str,
        track_id: int,
        session_id: str | None,
        hand_id: int | None = None,
        note: str = "confirmed by owner",
    ) -> dict[str, Any]:
        """Record a CHECKED_OUT event - the owner's reconciliation action."""
        now = time.time()
        uid = uuid.uuid4().hex[:16]
        with self._lock:
            self._conn.execute(
                """INSERT INTO events(
                       event_uid, ts, recorded_at, session_id, type, product_id, product_name,
                       track_id, hand_id, confidence, state, meta, resolved, resolution,
                       resolved_at, resolved_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uid,
                    now,
                    now,
                    session_id,
                    EventType.CHECKED_OUT.value,
                    product_id,
                    product_name,
                    track_id,
                    hand_id,
                    1.0,
                    "CHECKED_OUT",
                    json.dumps({"note": note}),
                    1,
                    note,
                    now,
                    "owner",
                ),
            )
            self._conn.execute(
                """UPDATE events SET resolved = 1, resolution = 'CHECKED_OUT',
                   resolved_at = ?, resolved_by = 'owner'
                   WHERE product_id = ? AND session_id IS ? AND resolved = 0""",
                (now, product_id, session_id),
            )
            self._conn.commit()
        return {
            "event_uid": uid,
            "type": EventType.CHECKED_OUT.value,
            "product_id": product_id,
            "product_name": product_name,
            "track_id": track_id,
            "ts": now,
            "ts_iso": _iso(now),
        }

    # ---------------------------------------------------------------- export
    def export_csv(self, limit: int = 10000, **filters: Any) -> str:
        rows = self.query_events(limit=limit, **filters)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()

    # ----------------------------------------------------------------- utils
    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        meta: dict[str, Any] = {}
        if data.get("meta"):
            try:
                meta = json.loads(data["meta"])
            except (TypeError, ValueError):
                meta = {}
        data["meta"] = meta
        data["ts_iso"] = _iso(data["ts"])
        data.pop("id", None)
        return data