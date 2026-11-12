"""Esquema relacional inicial; no reemplaza todavía el almacenamiento legado."""

from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from ingles.models import LevelDecision


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS periods (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
 start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PREPARACION' CHECK(status IN ('PREPARACION','ACTIVO','CERRADO')),
 CHECK(start_date <= end_date));
CREATE TABLE IF NOT EXISTS careers (
 id INTEGER PRIMARY KEY, provider TEXT NOT NULL, external_id TEXT NOT NULL,
 name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 UNIQUE(provider, external_id));
CREATE TABLE IF NOT EXISTS academic_groups (
 id INTEGER PRIMARY KEY, career_id INTEGER NOT NULL REFERENCES careers(id),
 provider TEXT NOT NULL, external_id TEXT NOT NULL, code TEXT NOT NULL,
 UNIQUE(provider, external_id));
CREATE TABLE IF NOT EXISTS students (
 id INTEGER PRIMARY KEY, provider TEXT NOT NULL, external_id TEXT NOT NULL,
 enrollment TEXT NOT NULL, name TEXT NOT NULL, building TEXT, shift TEXT,
 school_status TEXT NOT NULL, UNIQUE(provider, external_id), UNIQUE(provider, enrollment));
CREATE TABLE IF NOT EXISTS enrollments (
 id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id),
 period_id INTEGER NOT NULL REFERENCES periods(id),
 academic_group_id INTEGER NOT NULL REFERENCES academic_groups(id),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 UNIQUE(student_id, period_id));
CREATE TABLE IF NOT EXISTS enrollment_snapshots (
 enrollment_id INTEGER PRIMARY KEY REFERENCES enrollments(id),
 name TEXT NOT NULL, enrollment TEXT NOT NULL, career_name TEXT NOT NULL,
 group_code TEXT NOT NULL, building TEXT NOT NULL, shift TEXT NOT NULL,
 school_status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teachers (
 id INTEGER PRIMARY KEY, provider TEXT NOT NULL, external_id TEXT NOT NULL,
 name TEXT NOT NULL, employment_type TEXT NOT NULL CHECK(employment_type IN ('PA','PTC','OTRO')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), UNIQUE(provider, external_id));
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, identity_provider TEXT NOT NULL, subject TEXT NOT NULL,
 teacher_id INTEGER UNIQUE REFERENCES teachers(id),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), UNIQUE(identity_provider, subject));
CREATE TABLE IF NOT EXISTS user_roles (
 user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL CHECK(role IN ('SECRETARIA','DOCENTE')),
 PRIMARY KEY(user_id, role));
CREATE TABLE IF NOT EXISTS levels (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, position INTEGER NOT NULL UNIQUE,
 exempt INTEGER NOT NULL CHECK(exempt IN (0,1)));
CREATE TABLE IF NOT EXISTS level_decisions (
 id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id),
 target_period_id INTEGER NOT NULL REFERENCES periods(id), level_id INTEGER NOT NULL REFERENCES levels(id),
 actor_id INTEGER NOT NULL REFERENCES users(id), decided_at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS level_decisions_current ON level_decisions(student_id, target_period_id, id DESC);
CREATE TABLE IF NOT EXISTS teacher_period_rules (
 id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
 period_id INTEGER NOT NULL REFERENCES periods(id), participates INTEGER NOT NULL CHECK(participates IN (0,1)),
 max_hours INTEGER NOT NULL CHECK(max_hours >= 0), max_blocks INTEGER NOT NULL CHECK(max_blocks >= 0),
 UNIQUE(teacher_id, period_id));
CREATE TABLE IF NOT EXISTS time_slots (
 id INTEGER PRIMARY KEY, calendar_version TEXT NOT NULL, day INTEGER NOT NULL CHECK(day BETWEEN 1 AND 5),
 slot_number INTEGER NOT NULL CHECK(slot_number > 0), starts TEXT NOT NULL, ends TEXT NOT NULL,
 CHECK(starts < ends), UNIQUE(calendar_version, day, slot_number));
CREATE TABLE IF NOT EXISTS teacher_availability (
 rule_id INTEGER NOT NULL REFERENCES teacher_period_rules(id), slot_id INTEGER NOT NULL REFERENCES time_slots(id),
 PRIMARY KEY(rule_id, slot_id));
CREATE TABLE IF NOT EXISTS blocks (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS block_versions (
 id INTEGER PRIMARY KEY, block_id INTEGER NOT NULL REFERENCES blocks(id), version INTEGER NOT NULL CHECK(version > 0),
 UNIQUE(block_id, version));
CREATE TABLE IF NOT EXISTS block_slots (
 block_version_id INTEGER NOT NULL REFERENCES block_versions(id), slot_id INTEGER NOT NULL REFERENCES time_slots(id),
 PRIMARY KEY(block_version_id, slot_id));
CREATE TABLE IF NOT EXISTS period_blocks (
 id INTEGER PRIMARY KEY, period_id INTEGER NOT NULL REFERENCES periods(id),
 block_version_id INTEGER NOT NULL REFERENCES block_versions(id), active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 UNIQUE(period_id, block_version_id), UNIQUE(id, period_id));
CREATE TABLE IF NOT EXISTS settings (
 id INTEGER PRIMARY KEY, period_id INTEGER NOT NULL REFERENCES periods(id), version INTEGER NOT NULL,
 min_size INTEGER NOT NULL DEFAULT 8, target_size INTEGER NOT NULL DEFAULT 28, max_size INTEGER NOT NULL DEFAULT 35,
 solver_seconds INTEGER NOT NULL CHECK(solver_seconds > 0),
 CHECK(min_size >= 1 AND min_size <= target_size AND target_size <= max_size),
 UNIQUE(period_id, version), UNIQUE(id, period_id));
CREATE TABLE IF NOT EXISTS plans (
 id INTEGER PRIMARY KEY, period_id INTEGER NOT NULL REFERENCES periods(id),
 settings_id INTEGER, parent_id INTEGER, origin TEXT NOT NULL CHECK(origin IN ('ALGORITMO','MANUAL')),
 status TEXT NOT NULL CHECK(status IN ('PROPUESTA','PUBLICADA','SUSTITUIDA','DESCARTADA')),
 fingerprint TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 solver_version TEXT, solver_status TEXT, input_snapshot TEXT, metrics TEXT,
 UNIQUE(period_id, fingerprint), UNIQUE(id, period_id),
 FOREIGN KEY(settings_id, period_id) REFERENCES settings(id, period_id),
 FOREIGN KEY(parent_id, period_id) REFERENCES plans(id, period_id));
CREATE UNIQUE INDEX IF NOT EXISTS one_published_plan ON plans(period_id) WHERE status = 'PUBLICADA';
CREATE TABLE IF NOT EXISTS cohort_blocks (
 id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL, period_id INTEGER NOT NULL,
 academic_group_id INTEGER NOT NULL REFERENCES academic_groups(id), period_block_id INTEGER NOT NULL,
 UNIQUE(plan_id, academic_group_id), UNIQUE(id, plan_id),
 FOREIGN KEY(plan_id, period_id) REFERENCES plans(id, period_id),
 FOREIGN KEY(period_block_id, period_id) REFERENCES period_blocks(id, period_id));
CREATE TABLE IF NOT EXISTS english_groups (
 id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL, period_id INTEGER NOT NULL, code TEXT NOT NULL,
 period_block_id INTEGER NOT NULL, teacher_id INTEGER REFERENCES teachers(id),
 UNIQUE(plan_id, code), UNIQUE(id, plan_id),
 FOREIGN KEY(plan_id, period_id) REFERENCES plans(id, period_id),
 FOREIGN KEY(period_block_id, period_id) REFERENCES period_blocks(id, period_id));
CREATE TABLE IF NOT EXISTS english_group_levels (
 group_id INTEGER NOT NULL REFERENCES english_groups(id), level_id INTEGER NOT NULL REFERENCES levels(id),
 PRIMARY KEY(group_id, level_id));
CREATE TABLE IF NOT EXISTS student_assignments (
 plan_id INTEGER NOT NULL, group_id INTEGER NOT NULL, student_id INTEGER NOT NULL REFERENCES students(id),
 PRIMARY KEY(plan_id, student_id), FOREIGN KEY(group_id, plan_id) REFERENCES english_groups(id, plan_id));
CREATE TABLE IF NOT EXISTS plan_pending (
 plan_id INTEGER NOT NULL REFERENCES plans(id), student_id INTEGER NOT NULL REFERENCES students(id),
 category TEXT NOT NULL, detail TEXT, PRIMARY KEY(plan_id, student_id));
CREATE TABLE IF NOT EXISTS incidents (
 id INTEGER PRIMARY KEY, period_id INTEGER NOT NULL REFERENCES periods(id), student_id INTEGER NOT NULL REFERENCES students(id),
 teacher_id INTEGER NOT NULL REFERENCES teachers(id), current_level_id INTEGER NOT NULL REFERENCES levels(id),
 suggested_level_id INTEGER NOT NULL REFERENCES levels(id), reason TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ABIERTA','EN_REVISION','APROBADA','RECHAZADA','CANCELADA')),
 created_at TEXT NOT NULL, resolved_by INTEGER REFERENCES users(id), resolution TEXT, resolved_at TEXT,
 resulting_plan_id INTEGER REFERENCES plans(id));
CREATE TABLE IF NOT EXISTS history (
 id INTEGER PRIMARY KEY, period_id INTEGER REFERENCES periods(id), actor_id INTEGER REFERENCES users(id),
 entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, action TEXT NOT NULL,
 previous_value TEXT, new_value TEXT, reason TEXT, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_runs (
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, data_type TEXT NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, status TEXT NOT NULL CHECK(status IN ('EN_PROCESO','EXITOSA','PARCIAL','FALLIDA')),
 complete INTEGER NOT NULL DEFAULT 0 CHECK(complete IN (0,1)), details TEXT);
CREATE TABLE IF NOT EXISTS teacher_student_permissions (
 teacher_id INTEGER NOT NULL REFERENCES teachers(id), student_id INTEGER NOT NULL REFERENCES students(id),
 period_id INTEGER NOT NULL REFERENCES periods(id), granted_by INTEGER NOT NULL REFERENCES users(id),
 granted_at TEXT NOT NULL, PRIMARY KEY(teacher_id,student_id,period_id));
CREATE TABLE IF NOT EXISTS incident_context (
 incident_id INTEGER PRIMARY KEY REFERENCES incidents(id), academic_group TEXT NOT NULL,
 english_group TEXT,
 application_status TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK(application_status IN ('PENDIENTE','NO_APLICA','APLICADO')));
CREATE TABLE IF NOT EXISTS plan_events (
 id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id),
 actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
 reason TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_incidents (
 plan_id INTEGER NOT NULL REFERENCES plans(id), incident_id INTEGER NOT NULL REFERENCES incidents(id),
 student_id INTEGER NOT NULL REFERENCES students(id), old_level_id INTEGER NOT NULL REFERENCES levels(id),
 new_level_id INTEGER NOT NULL REFERENCES levels(id), PRIMARY KEY(plan_id,incident_id), UNIQUE(plan_id,student_id));
CREATE TABLE IF NOT EXISTS demo_scenarios (
 id TEXT PRIMARY KEY, period_id INTEGER NOT NULL REFERENCES periods(id), loaded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_report_meta (
 plan_id INTEGER PRIMARY KEY REFERENCES plans(id), captured_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_inactive_students (
 plan_id INTEGER NOT NULL REFERENCES plans(id), student_id INTEGER NOT NULL REFERENCES students(id),
 enrollment TEXT NOT NULL, name TEXT NOT NULL, career TEXT NOT NULL, academic_group TEXT NOT NULL,
 level TEXT, school_status TEXT NOT NULL, PRIMARY KEY(plan_id,student_id));
"""

LEVELS = ("PreBasic", "Basic 1", "Basic 2", "Basic 3", "Intermediate 1",
          "Intermediate 2", "Intermediate 3", "Intermediate 4", "Advance 1", "Advance 2")


class RelationalStore:
    """Nueva base, inicializada explícitamente y sin modificar datos anteriores."""

    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            legacy = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='revisions'").fetchone()
            if legacy:
                raise ValueError("Usa una base nueva: la base anterior debe conservarse intacta.")
            db.executescript(SCHEMA)
            columns = {row['name'] for row in db.execute('PRAGMA table_info(incident_context)')}
            if 'english_group' not in columns:
                db.execute('ALTER TABLE incident_context ADD COLUMN english_group TEXT')
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (1)")
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (2)")
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (3)")
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (4)")
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (5)")
            db.executemany("INSERT OR IGNORE INTO levels(id,name,position,exempt) VALUES (?,?,?,?)",
                           [(i, name, i, int(i > 8)) for i, name in enumerate(LEVELS, 1)])
            db.executemany("INSERT OR IGNORE INTO blocks(id,code,name) VALUES (?,?,?)",
                           [(i, f'B{i}', f'Bloque {i}') for i in range(1, 6)])

    def record_level_decision(self, decision: LevelDecision):
        """Añade una decisión sin sobrescribir las decisiones anteriores."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            cur = db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at,reason) VALUES (?,?,?,?,?,?)",
                             (decision.student_id, decision.target_period_id, decision.level_id,
                              decision.actor_id, now, decision.reason))
            return cur.lastrowid

    def current_level(self, student_id, period_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM level_decisions WHERE student_id=? AND target_period_id=? ORDER BY id DESC LIMIT 1",
                             (student_id, period_id)).fetchone()
            return dict(row) if row else None
