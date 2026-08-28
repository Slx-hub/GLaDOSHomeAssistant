"""5-minute power history, recorded from the FRITZ!Box statistics buffer.

Why the box buffer and not our own MQTT stream: the box keeps its own 1-hour
ring of 10s power samples, so polling it every 30 minutes gives 2x overlap and
recovers data recorded while this service was down. The MQTT path only ever
sees what happened to be transmitted while we were running.

Resolution reality check: on battery the device transmits every 120s and the
box fills the buffer by repeating the last value (blocks of 12). A 5-minute
bucket therefore averages 2-3 real measurements during power saving, and 30
during 10s mode. Either way it is finer than the bucket, so the average is
sound -- see README, "Transmit rate".

NOTE: reading the stats endpoint is also what holds the device in 10s mode
(see KeepAwake), so each history poll wakes it for ~2 minutes.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from common import jlog

BUCKET_S = 300          # 5 minutes
BUFFER_SPAN_S = 3600    # the box keeps 1 hour of 10s power samples
STATS_UNIT_W = 0.01     # getbasicdevicestats power is in 0.01 W -- NOT the mW
                        # the devicelist <power> element uses. Easy trap.

SCHEMA = """
CREATE TABLE IF NOT EXISTS power_5min (
    ts    INTEGER PRIMARY KEY,   -- unix epoch (UTC), start of the 5-minute bucket
    watt  REAL    NOT NULL,      -- mean power over the bucket
    n     INTEGER NOT NULL       -- 10s samples averaged (30 = complete bucket)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(db_path: str, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                               check_same_thread=False)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.executescript(SCHEMA)
        # WAL so the read-only web process never blocks the recorder.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


# ---- parsing -------------------------------------------------------------

def parse_power_stats(xml_text: str) -> Tuple[List[Tuple[int, float]], int]:
    """-> ([(unix_ts, watt), ...] oldest first, grid_seconds)

    The AHA stats array is newest-first: sample i was measured at
    datatime - i*grid. A 0 is treated as "no data", not as 0 W: the box
    demonstrably pads unreported series with zeros (the voltage array of the
    Energy 250 is all zeros) and a whole-house meter never actually reads 0.
    """
    root = ET.fromstring(xml_text)
    stats = root.find("power/stats")
    if stats is None or not (stats.text or "").strip():
        return [], BUCKET_S
    grid = int(stats.get("grid") or 10)
    datatime = int(stats.get("datatime") or 0)
    if datatime <= 0:
        return [], grid
    out: List[Tuple[int, float]] = []
    for i, raw in enumerate((stats.text or "").split(",")):
        raw = raw.strip()
        if raw in ("", "-"):
            continue
        try:
            v = int(raw)
        except ValueError:
            continue
        if v == 0:
            continue
        out.append((datatime - i * grid, v * STATS_UNIT_W))
    out.reverse()
    return out, grid


def bucket_samples(samples: Iterable[Tuple[int, float]]) -> Dict[int, Tuple[float, int]]:
    """Average samples into 5-minute buckets -> {bucket_ts: (mean_watt, n)}"""
    acc: Dict[int, List[float]] = {}
    for ts, watt in samples:
        acc.setdefault((ts // BUCKET_S) * BUCKET_S, []).append(watt)
    return {b: (sum(v) / len(v), len(v)) for b, v in acc.items()}


def upsert_buckets(conn: sqlite3.Connection,
                   buckets: Dict[int, Tuple[float, int]]) -> Tuple[int, int]:
    """Insert/refresh buckets. A bucket is only overwritten by one built from
    strictly MORE samples, so re-reading a partial trailing bucket can never
    degrade a complete one, and an unchanged re-read is not counted as a write
    (which keeps 'written' meaningful as a "did we gain data" signal).
    -> (rows_written, rows_unchanged)"""
    if not buckets:
        return 0, 0
    rows = [(b, w, n) for b, (w, n) in sorted(buckets.items())]
    before = conn.total_changes
    conn.executemany(
        """INSERT INTO power_5min (ts, watt, n) VALUES (?, ?, ?)
           ON CONFLICT(ts) DO UPDATE SET watt=excluded.watt, n=excluded.n
             WHERE excluded.n > power_5min.n""", rows)
    conn.commit()
    written = conn.total_changes - before
    return written, len(rows) - written


# ---- recorder ------------------------------------------------------------

class HistoryRecorder:
    """Polls the box statistics buffer on a slow timer and stores 5-minute means.

    Rides on the main poll loop like KeepAwake -- the loop ticks far more often
    than this cadence, so no extra thread is needed.
    """

    def __init__(self, cfg: dict):
        self.enabled = bool(cfg["enabled"])
        self.interval_s = float(cfg["interval_s"])
        self.retry_s = float(cfg["retry_s"])
        self.db_path = cfg["db_path"]
        # Monotonic deadline. 0.0 => the first tick after start is always due,
        # so a reboot resumes collection immediately instead of waiting out the
        # interval. The pi reboots nightly; the box buffer covers an hour, so
        # polling at once on startup means a short outage loses nothing.
        self._next_poll = 0.0
        self.notifier = None          # set by main(); optional
        self._conn: Optional[sqlite3.Connection] = None
        self.polls = 0
        self.rows_written = 0
        self.last_error: Optional[str] = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect(self.db_path)
        return self._conn

    def _note_success(self, conn) -> Optional[float]:
        """Persist the wall-clock time of this success; return the gap since the
        previous one (None on a fresh database). Wall clock, not monotonic, so
        it survives the reboot -- that is the whole point of storing it."""
        now_wall = time.time()
        row = conn.execute("SELECT value FROM meta WHERE key='last_success_ts'").fetchone()
        gap = None
        if row is not None:
            try:
                gap = now_wall - float(row["value"])
            except (TypeError, ValueError):
                gap = None
        conn.execute("""INSERT INTO meta (key, value) VALUES ('last_success_ts', ?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                     (str(now_wall),))
        conn.commit()
        return gap

    def tick(self, source) -> bool:
        if not self.enabled or not hasattr(source, "fetch_basic_stats"):
            return False
        now = time.monotonic()
        if now < self._next_poll:
            return False
        try:
            xml_text = source.fetch_basic_stats()
            samples, _ = parse_power_stats(xml_text)
            buckets = bucket_samples(samples)
            conn = self._db()
            written, unchanged = upsert_buckets(conn, buckets)
            gap = self._note_success(conn)
            # Only a SUCCESS consumes the full interval. A failure retries
            # soon: after a reboot the box can be briefly unreachable while
            # the network comes up, and burning 30 min on that could push the
            # next read past the 1-hour buffer and lose data permanently.
            self._next_poll = now + self.interval_s
            self.polls += 1
            self.rows_written += written
            self.last_error = None
            fields = {"samples": len(samples), "buckets": len(buckets),
                      "written": written, "unchanged": unchanged}
            if gap is not None:
                fields["since_last_success_s"] = round(gap)
            jlog(logging.INFO, "history_recorded", **fields)
            if gap is not None and gap > BUFFER_SPAN_S:
                jlog(logging.WARNING, "history_gap", since_last_success_s=round(gap),
                     buffer_s=BUFFER_SPAN_S,
                     detail="offline longer than the box buffer — that data is gone")
                if self.notifier is not None:
                    # A one-shot event, not a state: the data is already lost,
                    # so there is nothing to "recover" from later.
                    self.notifier.event(
                        "meter: history gap — data lost",
                        f"no successful history poll for {round(gap/60)} min, but the "
                        f"box only buffers {BUFFER_SPAN_S//60} min.\n"
                        f"That stretch is gone for good.",
                        tags="warning")
        except Exception as e:
            # History is a side channel; never let it break the measurement path.
            self._next_poll = now + self.retry_s
            self.last_error = f"{type(e).__name__}: {e}"
            jlog(logging.WARNING, "history_failed", error=self.last_error,
                 retry_s=self.retry_s)
        return True

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---- queries (used by the web UI) ---------------------------------------

def day_bounds_utc(date_str: str, tz) -> Tuple[int, int]:
    """Local calendar day -> [start, end) unix range. Days are local, because
    that is how a human clicks through them; storage stays UTC."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def series(conn, start_ts: int, end_ts: int) -> List[dict]:
    cur = conn.execute(
        "SELECT ts, watt, n FROM power_5min WHERE ts >= ? AND ts < ? ORDER BY ts",
        (start_ts, end_ts))
    return [{"ts": r["ts"], "watt": round(r["watt"], 1), "n": r["n"]} for r in cur]


def summary(conn, start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> dict:
    where, args = "", []
    if start_ts is not None and end_ts is not None:
        where, args = "WHERE ts >= ? AND ts < ?", [start_ts, end_ts]
    row = conn.execute(f"""
        SELECT COUNT(*) AS buckets, AVG(watt) AS avg_w, MIN(watt) AS min_w,
               MAX(watt) AS max_w, MIN(ts) AS first_ts, MAX(ts) AS last_ts
        FROM power_5min {where}""", args).fetchone()
    buckets = row["buckets"] or 0
    return {
        "buckets": buckets,
        "avg_w": round(row["avg_w"], 1) if row["avg_w"] is not None else None,
        "min_w": round(row["min_w"], 1) if row["min_w"] is not None else None,
        "max_w": round(row["max_w"], 1) if row["max_w"] is not None else None,
        "first_ts": row["first_ts"],
        "last_ts": row["last_ts"],
        # Each bucket is BUCKET_S of dwell time, so mean power -> energy directly.
        "kwh": round((row["avg_w"] or 0) * buckets * BUCKET_S / 3_600_000.0, 3),
        "covered_h": round(buckets * BUCKET_S / 3600.0, 2),
    }


def days_with_data(conn, tz) -> List[dict]:
    """One row per local calendar day that has data."""
    cur = conn.execute("SELECT ts, watt FROM power_5min ORDER BY ts")
    agg: Dict[str, List[float]] = {}
    for r in cur:
        day = datetime.fromtimestamp(r["ts"], tz).strftime("%Y-%m-%d")
        agg.setdefault(day, []).append(r["watt"])
    return [{"date": d, "buckets": len(v), "avg_w": round(sum(v) / len(v), 1),
             "kwh": round(sum(v) * BUCKET_S / 3_600_000.0, 3)}
            for d, v in sorted(agg.items())]
