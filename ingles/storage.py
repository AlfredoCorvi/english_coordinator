from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from ingles.domain import DEFAULT_SETTINGS, empty_bundle, period_count, validate_settings


class ConcurrentEdit(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL,
                    note TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, revision INTEGER NOT NULL,
                    created TEXT NOT NULL, note TEXT NOT NULL, payload TEXT NOT NULL,
                    FOREIGN KEY(revision) REFERENCES revisions(id));
            ''')
            # Preserve the previous catalogs/plans and invalidate their revision
            # when upgrading from the formerly optional shared-block rule.
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute("SELECT payload FROM revisions ORDER BY id DESC LIMIT 1").fetchone()
            if latest:
                bundle = json.loads(latest["payload"])
                changes = []
                if "cohort_block" in bundle["settings"]:
                    bundle["settings"].pop("cohort_block")
                    changes.append("Bloque común obligatorio por grupo de carrera")
                if "break_start" not in bundle["settings"] or "break_end" not in bundle["settings"]:
                    for key in ("period_minutes", "break_start", "break_end"):
                        bundle["settings"][key] = DEFAULT_SETTINGS[key]
                    changes.append("Periodos de 45 minutos y receso de 11:30 a 11:55")
                if "end_time" not in bundle["settings"]:
                    bundle["settings"]["end_time"] = DEFAULT_SETTINGS["end_time"]
                    changes.append("Fin de jornada configurable: 15:45")
                if "transfer_periods" in bundle["settings"]:
                    bundle["settings"].pop("transfer_periods")
                    changes.append("Retirada la separación obligatoria entre edificios")
                if not validate_settings(bundle["settings"]):
                    count = period_count(bundle["settings"])
                    if bundle["settings"].get("periods_per_day") != count:
                        bundle["settings"]["periods_per_day"] = count
                        changes.append("Periodos calculados con la jornada completa")
                for teacher in bundle["teachers"]:
                    if "matricula_docente" not in teacher:
                        teacher["matricula_docente"] = teacher["ID"]
                        if "Matrículas docentes incorporadas" not in changes:
                            changes.append("Matrículas docentes incorporadas")
                if changes:
                    db.execute("INSERT INTO revisions(created, note, payload) VALUES (?, ?, ?)",
                               (datetime.now(timezone.utc).isoformat(), "; ".join(changes),
                                json.dumps(bundle, ensure_ascii=False)))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def load(self):
        with self.connect() as db:
            row = db.execute("SELECT id, payload FROM revisions ORDER BY id DESC LIMIT 1").fetchone()
        return (json.loads(row["payload"]), row["id"]) if row else (empty_bundle(), 0)

    def save(self, bundle, expected_revision, note):
        bundle = deepcopy(bundle)
        bundle["settings"].pop("cohort_block", None)
        bundle["settings"].pop("transfer_periods", None)
        if not validate_settings(bundle["settings"]):
            bundle["settings"]["periods_per_day"] = period_count(bundle["settings"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actual = db.execute("SELECT COALESCE(MAX(id), 0) FROM revisions").fetchone()[0]
            if actual != expected_revision:
                raise ConcurrentEdit("Otra sesión cambió los datos. Recarga la página antes de guardar.")
            cur = db.execute("INSERT INTO revisions(created, note, payload) VALUES (?, ?, ?)",
                             (datetime.now(timezone.utc).isoformat(), note, json.dumps(bundle, ensure_ascii=False)))
            return cur.lastrowid

    def save_plan(self, result, revision, note):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actual = db.execute("SELECT COALESCE(MAX(id), 0) FROM revisions").fetchone()[0]
            if actual != revision:
                raise ConcurrentEdit("Los datos cambiaron durante la generación. Genera de nuevo con los datos actuales.")
            cur = db.execute("INSERT INTO plans(revision, created, note, payload) VALUES (?, ?, ?, ?)",
                             (revision, datetime.now(timezone.utc).isoformat(), note, json.dumps(result, ensure_ascii=False)))
            return cur.lastrowid

    def plans(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id, revision, created, note FROM plans ORDER BY id DESC")]

    def get_plan(self, plan_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise ValueError("No existe la versión solicitada.")
        return {**dict(row), "payload": json.loads(row["payload"])}
