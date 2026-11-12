import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from ingles.models import LevelDecision
from ingles.relational_storage import RelationalStore


class RelationalStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'new.sqlite3'
        self.store = RelationalStore(self.path)
        self.store.initialize()

    def seed(self, db):
        db.execute("INSERT INTO periods(id,code,start_date,end_date) VALUES (1,'actual','2026-09-01','2026-12-31'),(2,'siguiente','2027-01-01','2027-04-30')")
        db.execute("INSERT INTO students(id,provider,external_id,enrollment,name,school_status) VALUES (1,'api','s1','0001','Ana','ACTIVO')")
        db.execute("INSERT INTO users(id,identity_provider,subject) VALUES (1,'auth','docente')")

    def test_seed_is_idempotent_and_has_no_invented_schedules(self):
        self.store.initialize()
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM blocks').fetchone()[0], 5)
            self.assertEqual(db.execute('SELECT count(*) FROM levels WHERE exempt=1').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM time_slots').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM block_versions').fetchone()[0], 0)

    def test_next_level_is_available_before_groups_and_preserves_history(self):
        with self.store.connect() as db:
            self.seed(db)
        self.store.record_level_decision(LevelDecision(1, 2, 3, 1, 'Inicial'))
        self.store.record_level_decision(LevelDecision(1, 2, 4, 1, 'Corrección'))
        self.assertEqual(self.store.current_level(1, 2)['level_id'], 4)
        self.assertIsNone(self.store.current_level(1, 1))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM level_decisions').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM english_groups').fetchone()[0], 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_level_decision(LevelDecision(1, 2, 99, 1))

    def test_one_publication_and_plan_period_integrity(self):
        with self.store.connect() as db:
            self.seed(db)
            db.execute("INSERT INTO plans(id,period_id,origin,status,fingerprint,created_by,created_at) VALUES (1,1,'ALGORITMO','PUBLICADA','a',1,'now')")
            db.execute("INSERT INTO plans(id,period_id,origin,status,fingerprint,created_by,created_at) VALUES (2,1,'ALGORITMO','PROPUESTA','b',1,'now')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE plans SET status='PUBLICADA' WHERE id=2")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO plans(period_id,parent_id,origin,status,fingerprint,created_by,created_at) VALUES (2,1,'MANUAL','PROPUESTA','c',1,'now')")
            self.assertEqual(db.execute('SELECT status FROM plans WHERE id=1').fetchone()[0], 'PUBLICADA')

    def test_rejects_legacy_database_without_changes(self):
        path = Path(self.tmp.name) / 'old.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute('CREATE TABLE revisions (id INTEGER PRIMARY KEY)')
        with self.assertRaises(ValueError):
            RelationalStore(path).initialize()
        with closing(sqlite3.connect(path)) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='levels'").fetchone())


if __name__ == '__main__':
    unittest.main()
