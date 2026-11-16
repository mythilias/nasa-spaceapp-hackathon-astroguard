# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""SQLite persistence (stdlib sqlite3). Seeds 14 days of synthetic check-in history on first run."""
from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY, crew_id TEXT, ts REAL, systolic REAL, diastolic REAL, glucose REAL,
  body_temp REAL, sleep_hours REAL, mood INTEGER, symptoms TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS tasks_done (id INTEGER PRIMARY KEY, crew_id TEXT, day TEXT, task_id TEXT, ts REAL,
  UNIQUE(crew_id, day, task_id));
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, ts REAL, viewer TEXT, viewer_role TEXT,
  subject TEXT, level TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS prefs (crew_id TEXT PRIMARY KEY, share_mood_cmo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, ts REAL, from_user TEXT, to_crew TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS readings (id INTEGER PRIMARY KEY, device_id TEXT, crew_id TEXT, metric TEXT,
  value REAL, ts REAL, received_ts REAL, UNIQUE(device_id, metric, ts));
CREATE TABLE IF NOT EXISTS emergencies (id INTEGER PRIMARY KEY, ts REAL, patient TEXT, protocol TEXT,
  started_by TEXT, state TEXT, resolved_ts REAL, steps_done TEXT DEFAULT '[]');
"""

# per-crew synthetic profiles for seeding: (sys, dia, glucose, temp, sleep, mood) plus a trend
PROFILES = {
    "CDR": dict(sys=118, dia=76, glu=92, temp=36.8, sleep=6.8, mood=4, trend={}),
    "PLT": dict(sys=124, dia=80, glu=98, temp=36.9, sleep=6.4, mood=4, trend={"sys": 1.0}),          # BP creeping up
    "MS1": dict(sys=112, dia=72, glu=88, temp=36.7, sleep=7.2, mood=4, trend={"sleep": -0.12, "mood": -0.1}),  # sleep & mood sliding
    "MS2": dict(sys=116, dia=75, glu=95, temp=36.8, sleep=6.9, mood=5, trend={}),
}


class DB:
    REPLICATED_INCREMENTAL = ("checkins", "tasks_done", "audit", "readings")   # append-only: send rows with id > cursor
    REPLICATED_FULL = ("prefs", "notes", "emergencies")            # small / mutable: send whole table

    def __init__(self, path: Path, seed: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            for ddl in ("ALTER TABLE prefs ADD COLUMN share_vitals_cmo INTEGER DEFAULT 0",   # migrations
                        "ALTER TABLE emergencies ADD COLUMN briefing TEXT",
                        "ALTER TABLE emergencies ADD COLUMN briefing_by TEXT"):
                try:
                    self.conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass
            self.conn.commit()
        if seed and not self.q("SELECT 1 FROM checkins LIMIT 1"):
            self.seed()

    # ---- replication (onboard = source of truth, ground = replica) -------------
    def rows_since(self, table, last_id):
        return self.q(f"SELECT * FROM {table} WHERE id > ? ORDER BY id", (last_id,))

    def all_rows(self, table):
        return self.q(f"SELECT * FROM {table}")

    def upsert(self, table, rows):
        if not rows:
            return
        cols = list(rows[0].keys())
        sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        with self.lock:
            self.conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
            self.conn.commit()

    def replace_all(self, table, rows):
        with self.lock:
            self.conn.execute(f"DELETE FROM {table}")
            self.conn.commit()
        self.upsert(table, rows)

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    # ---- seeding --------------------------------------------------------------
    def seed(self):
        rng = random.Random(11)
        today = date.today()
        rows, tasks = [], []
        for cid, p in PROFILES.items():
            t = p["trend"]
            for d in range(14, 0, -1):
                if cid == "MS1" and d in (3, 6):  # missed check-ins, so a broken streak to show
                    continue
                k = 14 - d
                ts = datetime.combine(today - timedelta(days=d), datetime.min.time()).timestamp() + 8 * 3600 + rng.randint(0, 1800)
                rows.append((cid, ts,
                             round(p["sys"] + t.get("sys", 0) * k + rng.gauss(0, 3)),
                             round(p["dia"] + t.get("sys", 0) * 0.5 * k + rng.gauss(0, 2)),
                             round(p["glu"] + rng.gauss(0, 6)),
                             round(p["temp"] + rng.gauss(0, 0.15), 1),
                             round(max(3.5, p["sleep"] + t.get("sleep", 0) * k + rng.gauss(0, 0.3)), 1),
                             int(min(5, max(1, round(p["mood"] + t.get("mood", 0) * k + rng.gauss(0, 0.4))))),
                             "", ""))
                day = (today - timedelta(days=d)).isoformat()
                for task in ("checkin", "exercise", "hydration", "mood_pm", "sleep_prep"):
                    if rng.random() < (0.9 if cid != "MS1" else 0.6) or task == "checkin":
                        tasks.append((cid, day, task, ts))
        with self.lock:
            self.conn.executemany("INSERT INTO checkins (crew_id, ts, systolic, diastolic, glucose, body_temp, sleep_hours, mood, symptoms, note) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self.conn.executemany("INSERT OR IGNORE INTO tasks_done (crew_id, day, task_id, ts) VALUES (?,?,?,?)", tasks)
            self.conn.executemany("INSERT OR IGNORE INTO prefs (crew_id, share_mood_cmo) VALUES (?, 0)", [(c,) for c in PROFILES])
            self.conn.execute("INSERT INTO notes (ts, from_user, to_crew, text) VALUES (?,?,?,?)",
                              (time.time() - 86400, "SURG", "MS1",
                               "Your sleep has been trending down this week. Let's talk at your next private conference. Try the earlier lights-out window in Routine."))
            self.conn.commit()

    # ---- helpers ----------------------------------------------------------------
    def checkins(self, cid, days=14):
        since = time.time() - days * 86400 - 3600
        return self.q("SELECT * FROM checkins WHERE crew_id=? AND ts>=? ORDER BY ts", (cid, since))

    def insert_readings(self, rows) -> int:
        """rows: (device_id, crew_id, metric, value, ts, received_ts). Duplicates are ignored. Returns new rows."""
        if not rows:
            return 0
        with self.lock:
            before = self.conn.total_changes
            self.conn.executemany("INSERT OR IGNORE INTO readings (device_id, crew_id, metric, value, ts, received_ts) "
                                  "VALUES (?,?,?,?,?,?)", rows)
            self.conn.commit()
            return self.conn.total_changes - before

    def devices_for(self, cid):
        return self.q("SELECT device_id, COUNT(*) AS readings, MAX(ts) AS last_reading, MAX(received_ts) AS last_sync "
                      "FROM readings WHERE crew_id=? GROUP BY device_id", (cid,))

    def add_checkin(self, cid, data: dict, ts: float | None = None, routine_credit: bool = True):
        cols = ["systolic", "diastolic", "glucose", "body_temp", "sleep_hours", "mood", "symptoms", "note"]
        vals = [data.get(c) for c in cols]
        rid = self.x(f"INSERT INTO checkins (crew_id, ts, {', '.join(cols)}) VALUES (?,?,{','.join('?' * len(cols))})",
                     [cid, ts or time.time(), *vals])
        if not routine_credit:
            return rid
        self.task_done(cid, "checkin")
        if data.get("mood") is not None and datetime.now().hour >= 17:
            self.task_done(cid, "mood_pm")
        return rid

    def task_done(self, cid, task_id):
        self.x("INSERT OR IGNORE INTO tasks_done (crew_id, day, task_id, ts) VALUES (?,?,?,?)",
               (cid, date.today().isoformat(), task_id, time.time()))

    def tasks_today(self, cid):
        return {r["task_id"] for r in self.q("SELECT task_id FROM tasks_done WHERE crew_id=? AND day=?", (cid, date.today().isoformat()))}

    def task_days(self, cid):
        return self.q("SELECT day, task_id FROM tasks_done WHERE crew_id=?", (cid,))

    def share_mood(self, cid) -> bool:
        r = self.q("SELECT share_mood_cmo FROM prefs WHERE crew_id=?", (cid,))
        return bool(r and r[0]["share_mood_cmo"])

    def share_vitals(self, cid) -> bool:
        r = self.q("SELECT share_vitals_cmo FROM prefs WHERE crew_id=?", (cid,))
        return bool(r and r[0]["share_vitals_cmo"])

    def set_share_vitals(self, cid, on: bool):
        self.x("INSERT INTO prefs (crew_id, share_vitals_cmo) VALUES (?,?) ON CONFLICT(crew_id) DO UPDATE SET share_vitals_cmo=excluded.share_vitals_cmo",
               (cid, int(on)))

    def set_share_mood(self, cid, on: bool):
        self.x("INSERT INTO prefs (crew_id, share_mood_cmo) VALUES (?,?) ON CONFLICT(crew_id) DO UPDATE SET share_mood_cmo=excluded.share_mood_cmo",
               (cid, int(on)))

    def audit(self, viewer, role, subject, level, reason):
        self.x("INSERT INTO audit (ts, viewer, viewer_role, subject, level, reason) VALUES (?,?,?,?,?,?)",
               (time.time(), viewer, role, subject, level, reason))

    def audit_for(self, subject, limit=30):
        return self.q("SELECT * FROM audit WHERE subject=? ORDER BY ts DESC LIMIT ?", (subject, limit))

    def notes_for(self, cid):
        return self.q("SELECT * FROM notes WHERE to_crew=? ORDER BY ts DESC LIMIT 10", (cid,))

    def add_note(self, from_user, to_crew, text):
        return self.x("INSERT INTO notes (ts, from_user, to_crew, text) VALUES (?,?,?,?)", (time.time(), from_user, to_crew, text))

    def active_emergencies(self):
        rows = self.q("SELECT * FROM emergencies WHERE state='active' ORDER BY ts DESC")
        for r in rows:
            r["steps_done"] = json.loads(r["steps_done"] or "[]")
        return rows

    def start_emergency(self, patient, protocol, by):
        return self.x("INSERT INTO emergencies (ts, patient, protocol, started_by, state) VALUES (?,?,?,?, 'active')",
                      (time.time(), patient, protocol, by))

    def set_briefing(self, eid, text, by):
        self.x("UPDATE emergencies SET briefing=?, briefing_by=? WHERE id=?", (text, by, eid))

    def update_emergency(self, eid, steps_done=None, resolve=False):
        if steps_done is not None:
            self.x("UPDATE emergencies SET steps_done=? WHERE id=?", (json.dumps(steps_done), eid))
        if resolve:
            self.x("UPDATE emergencies SET state='resolved', resolved_ts=? WHERE id=?", (time.time(), eid))
