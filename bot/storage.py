import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def display_time(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%d/%m/%Y a las %H:%M")


class Store:
    def __init__(self, path: Path, timezone: str, hours: tuple[str, ...], ttl: int = 24):
        self.path, self.zone, self.hours, self.ttl = path, ZoneInfo(timezone), hours, ttl
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    owner TEXT PRIMARY KEY, history TEXT NOT NULL DEFAULT '[]',
                    pending TEXT, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS slots (id TEXT PRIMARY KEY, starts_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bookings (
                    owner TEXT PRIMARY KEY, slot_id TEXT UNIQUE NOT NULL REFERENCES slots(id),
                    service TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, result TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, recipient TEXT, body TEXT,
                    response TEXT, status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_owner_created ON jobs(owner, created);
            """)
        os.chmod(path, 0o600)
        self.maintain()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def now(self):
        return datetime.now(self.zone)

    def maintain(self):
        now = self.now()
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE updated < ?", (time.time() - self.ttl * 3600,))
            db.execute(
                "DELETE FROM bookings WHERE slot_id IN (SELECT id FROM slots WHERE starts_at < ?)",
                (now.isoformat(),),
            )
            db.execute("DELETE FROM slots WHERE starts_at < ?", (now.isoformat(),))
            db.execute("DELETE FROM actions WHERE created < ?", (time.time() - 7 * 86400,))
            db.execute("DELETE FROM jobs WHERE created < ?", (time.time() - 7 * 86400,))
            db.execute(
                "UPDATE jobs SET status='failed', recipient=NULL, body=NULL, response=NULL "
                "WHERE status='pending' AND created < ?",
                (time.time() - 23 * 3600,),
            )
            for day in range(8):
                date = now + timedelta(days=day)
                if date.weekday() >= 5:
                    continue
                for hour in self.hours:
                    h, m = map(int, hour.split(":"))
                    start = date.replace(hour=h, minute=m, second=0, microsecond=0)
                    if start > now:
                        slot_id = start.strftime("%Y%m%d-%H%M")
                        db.execute(
                            "INSERT OR IGNORE INTO slots VALUES (?, ?)",
                            (slot_id, start.isoformat()),
                        )

    def available(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id, starts_at FROM slots WHERE starts_at > ? "
                    "AND id NOT IN (SELECT slot_id FROM bookings) ORDER BY starts_at LIMIT 18",
                    (self.now().isoformat(),),
                )
            ]

    def bookings(self, owner: str):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT slot_id, starts_at, service FROM bookings JOIN slots ON slots.id=slot_id "
                    "WHERE owner=? AND starts_at > ?",
                    (owner, self.now().isoformat()),
                )
            ]

    def session(self, owner: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE owner=? AND updated > ?",
                (owner, time.time() - self.ttl * 3600),
            ).fetchone()
            if not row:
                return [], None
            pending = json.loads(row["pending"]) if row["pending"] else None
            if pending and pending["expires"] < time.time():
                pending = None
            return json.loads(row["history"]), pending

    def save_history(self, owner: str, history: list):
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions(owner, history, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(owner) DO UPDATE SET history=excluded.history, updated=excluded.updated",
                (owner, json.dumps(history[-12:], ensure_ascii=False), time.time()),
            )

    def propose(self, owner: str, slot_id: str, service: str):
        slots = {s["id"]: s for s in self.available()}
        if self.bookings(owner):
            return {
                "error": "Ya tienes una cita. Consulta tu cita o escribe CANCELAR CITA primero."
            }
        if slot_id not in slots:
            return {"error": "Horario no disponible. Consulta los horarios de nuevo."}
        pending = {
            "slot_id": slot_id,
            "service": service,
            "starts_at": slots[slot_id]["starts_at"],
            "expires": time.time() + 600,
        }
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions(owner, pending, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(owner) DO UPDATE SET pending=excluded.pending, updated=excluded.updated",
                (owner, json.dumps(pending), time.time()),
            )
        return {"proposal": pending, "instruction": "Escribe CONFIRMAR para reservar o DESCARTAR."}

    def command(self, owner: str, event: str, command: str) -> str:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT result FROM actions WHERE id=?", (event,)).fetchone()
            if previous:
                return previous["result"]
            if command == "confirmar":
                row = db.execute("SELECT pending FROM sessions WHERE owner=?", (owner,)).fetchone()
                pending = json.loads(row["pending"]) if row and row["pending"] else None
                slot = db.execute(
                    "SELECT starts_at FROM slots WHERE id=? AND starts_at > ?",
                    (pending["slot_id"] if pending else "", self.now().isoformat()),
                ).fetchone()
                if not pending or pending["expires"] < time.time() or not slot:
                    result = "No hay una propuesta vigente. Pide horarios para preparar tu cita."
                else:
                    try:
                        db.execute(
                            "INSERT INTO bookings VALUES (?, ?, ?)",
                            (owner, pending["slot_id"], pending["service"]),
                        )
                        result = (
                            f"Cita confirmada: {pending['service'].replace('_', ' + ')} · "
                            f"{display_time(slot['starts_at'])} "
                            f"({self.zone.key}). Escribe MI CITA para consultarla."
                        )
                    except sqlite3.IntegrityError:
                        result = "No pude reservar: el horario se ocupó o ya tienes una cita. Consulta tu cita u otros horarios."
                db.execute("UPDATE sessions SET pending=NULL WHERE owner=?", (owner,))
            elif command == "cancelar cita":
                deleted = db.execute("DELETE FROM bookings WHERE owner=?", (owner,)).rowcount
                db.execute("UPDATE sessions SET pending=NULL WHERE owner=?", (owner,))
                result = "Tu cita quedó cancelada." if deleted else "No tienes una cita activa."
            elif command == "olvidar":
                db.execute("DELETE FROM sessions WHERE owner=?", (owner,))
                result = "Borré tu memoria y propuesta. Tu cita confirmada se conserva; puedes cancelarla con CANCELAR CITA."
            else:
                db.execute("UPDATE sessions SET pending=NULL WHERE owner=?", (owner,))
                result = "Propuesta descartada. Puedes pedir otros horarios."
            db.execute("INSERT INTO actions VALUES (?, ?, ?)", (event, result, time.time()))
            return result

    def enqueue(self, event: str, owner: str, recipient: str, body: str, limit: int):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE id=?", (event,)).fetchone():
                return "duplicate"
            count = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE owner=? AND created>?", (owner, time.time() - 60)
            ).fetchone()[0]
            if count >= limit:
                return "rate_limited"
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status='pending'").fetchone()[0] >= 200:
                return "full"
            db.execute(
                "INSERT INTO jobs(id, owner, recipient, body, created) VALUES (?, ?, ?, ?, ?)",
                (event, owner, recipient, body, time.time()),
            )
            return "queued"

    def next_job(self):
        with self.connect() as db:
            row = db.execute(
                "SELECT j.* FROM jobs j WHERE j.status='pending' AND j.next_try<=? "
                "AND NOT EXISTS (SELECT 1 FROM jobs earlier WHERE earlier.owner=j.owner "
                "AND earlier.status='pending' AND earlier.rowid < j.rowid) "
                "ORDER BY j.rowid LIMIT 1",
                (time.time(),),
            ).fetchone()
            return dict(row) if row else None

    def save_response(self, event: str, response: str):
        with self.connect() as db:
            db.execute("UPDATE jobs SET response=? WHERE id=?", (response, event))

    def complete(self, event: str):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status='done', recipient=NULL, body=NULL, response=NULL WHERE id=?",
                (event,),
            )

    def retry(self, event: str, attempts: int):
        with self.connect() as db:
            if attempts >= 3:
                db.execute(
                    "UPDATE jobs SET status='failed', attempts=?, recipient=NULL, body=NULL, "
                    "response=NULL WHERE id=?",
                    (attempts, event),
                )
            else:
                db.execute(
                    "UPDATE jobs SET attempts=?, next_try=? WHERE id=?",
                    (attempts, time.time() + 5 * 2**attempts, event),
                )

    def counts(self):
        with self.connect() as db:
            return {
                r["status"]: r["n"]
                for r in db.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status")
            }
