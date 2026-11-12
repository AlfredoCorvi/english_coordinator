import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ingles.integrations import Batch, ConfigurableTestAuth, Identity, IntegrationError, MappedProvider, provider_from_environment
from ingles.institutional_services import AccessDenied, AuthService, SyncService
from ingles.models import LevelDecision
from ingles.relational_storage import RelationalStore


class Provider:
    def __init__(self, rows, complete=True):
        self.batch = Batch(rows, complete)

    def fetch(self):
        return self.batch


class Broken:
    def fetch(self):
        raise OSError('https://example.invalid/?key=secret')


def student(**changes):
    return dict({'id_externo': 's1', 'matricula': '001', 'nombre': 'Ana', 'carrera_id': 'c1',
                 'carrera': 'Sistemas', 'grupo_id': 'g1', 'grupo': 'DSM-31', 'edificio': '1',
                 'turno': 'matutino', 'estatus': 'activo'}, **changes)


def teacher(ident='t1', **changes):
    return dict({'id_externo': ident, 'nombre': 'Docente', 'tipo_contratacion': 'PA',
                 'sujeto_identidad': ident}, **changes)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = RelationalStore(Path(tmp.name) / 'new.db')
        self.store.initialize()
        with self.store.connect() as db:
            db.execute("INSERT INTO periods(id,code,start_date,end_date) VALUES (1,'P1','2026-01-01','2026-04-30'),(2,'P2','2026-05-01','2026-08-31')")
            db.execute("INSERT INTO users(id,identity_provider,subject) VALUES (1,'auth','admin'),(2,'auth','norole'),(3,'auth','inactive')")
            db.execute("UPDATE users SET active=0 WHERE id=3")
            db.execute("INSERT INTO user_roles VALUES (1,'SECRETARIA'),(3,'SECRETARIA')")
        self.auth = AuthService(self.store, ConfigurableTestAuth({
            'admin': ('fake', Identity('auth', 'admin')),
            'inactive': ('fake', Identity('auth', 'inactive')),
            'norole': ('fake', Identity('auth', 'norole')),
            'teacher': ('fake', Identity('auth', 't1')),
            'student': ('fake', Identity('auth', 's1')),
        }))
        self.session = self.auth.login('admin', 'fake')
        self.sync = SyncService(self.store, self.auth, 'school', 'auth')

    def test_students_update_level_and_period_snapshot(self):
        self.sync.sync_students(self.session, Provider([student()]), 1)
        self.store.record_level_decision(LevelDecision(1, 2, 2, 1))
        self.sync.sync_students(self.session, Provider([student(nombre='Nueva', estatus='inactivo')]), 2)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0], 1)
            snapshots = db.execute('SELECT name,school_status FROM enrollment_snapshots ORDER BY enrollment_id').fetchall()
            self.assertEqual([tuple(r) for r in snapshots], [('Ana', 'activo'), ('Nueva', 'inactivo')])
            self.assertEqual(db.execute('SELECT active FROM enrollments WHERE period_id=2').fetchone()[0], 0)
        self.assertEqual(self.store.current_level(1, 2)['level_id'], 2)

    def test_invalid_duplicates_rollback_and_logged(self):
        with self.assertRaises(IntegrationError):
            self.sync.sync_students(self.session, Provider([student(), student()]), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT status FROM sync_runs').fetchone()[0], 'FALLIDA')

    def test_teacher_complete_partial_empty_and_connection_failure(self):
        self.sync.sync_teachers(self.session, Provider([teacher(), teacher('t2')]))
        self.sync.sync_teachers(self.session, Provider([teacher()], False))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM teachers WHERE active=1').fetchone()[0], 2)
        for provider in (Provider([]), Broken(), Provider([teacher(), teacher()])):
            with self.assertRaises(IntegrationError):
                self.sync.sync_teachers(self.session, provider)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM teachers WHERE active=1').fetchone()[0], 2)
            self.assertNotIn('secret', str([tuple(r) for r in db.execute('SELECT details FROM sync_runs')]))
        self.sync.sync_teachers(self.session, Provider([teacher()]))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT active FROM teachers WHERE external_id='t2'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM user_roles WHERE role='DOCENTE'").fetchone()[0], 2)

    def test_auth_and_role_checked_on_every_operation(self):
        self.sync.sync_teachers(self.session, Provider([teacher()]))
        doc = self.auth.login('teacher', 'fake')
        self.auth.authorize(doc, {'DOCENTE'})
        with self.assertRaises(AccessDenied):
            self.sync.sync_teachers(doc, Provider([teacher()]))
        for username, password in [('admin', 'bad'), ('norole', 'fake'), ('inactive', 'fake'), ('student', 'fake')]:
            with self.assertRaises(AccessDenied):
                self.auth.login(username, password)
        with self.store.connect() as db:
            db.execute('UPDATE teachers SET active=0')
        with self.assertRaises(AccessDenied):
            self.auth.authorize(doc, {'DOCENTE'})
        with self.assertRaises(AccessDenied):
            self.auth.login('teacher', 'fake')

    def test_mapping_and_bare_boolean_auth_rejected(self):
        mapped = MappedProvider(Provider([{'matricula_api': '001'}], False), {'matricula': 'matricula_api'})
        self.assertEqual(mapped.fetch(), Batch([{'matricula': '001'}], False))
        auth = AuthService(self.store, ConfigurableTestAuth({'x': ('fake', True)}))
        with self.assertRaises(AccessDenied):
            auth.login('x', 'fake')

    def test_environment_configuration_and_http_failure_sanitized(self):
        settings = {'INGLES_ALUMNOS_URL': 'https://example.invalid/?key=fake-secret',
                    'INGLES_ALUMNOS_FIELDS': '{"matricula":"number"}'}
        with patch.dict('os.environ', settings, clear=True):
            provider = provider_from_environment('ALUMNOS')
            with patch('ingles.integrations.urlopen', side_effect=OSError('fake-secret')):
                with self.assertRaises(IntegrationError) as raised:
                    provider.fetch()
            self.assertNotIn('fake-secret', str(raised.exception))

    def test_identity_collision_rolls_back_entire_batch(self):
        with self.assertRaises(IntegrationError):
            self.sync.sync_teachers(self.session, Provider([teacher(), teacher('t2', sujeto_identidad='t1')]))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM teachers').fetchone()[0], 0)

    def test_complete_http_snapshot_requires_matching_count(self):
        from io import BytesIO
        settings = {'INGLES_MAESTROS_URL': 'https://example.invalid/',
                    'INGLES_MAESTROS_FIELDS': '{"id_externo":"id"}',
                    'INGLES_MAESTROS_COMPLETE': 'true', 'INGLES_MAESTROS_EXPECTED_COUNT': '2'}
        with patch.dict('os.environ', settings, clear=True):
            provider = provider_from_environment('MAESTROS')
            with patch('ingles.integrations.urlopen', return_value=BytesIO(b'[{"id":"1"}]')):
                with self.assertRaises(IntegrationError):
                    provider.fetch()

    def test_synchronization_preserves_level_and_historical_group(self):
        self.sync.sync_students(self.session,Provider([student()]),1)
        self.sync.sync_teachers(self.session,Provider([teacher(),teacher('t2')]))
        self.store.record_level_decision(LevelDecision(1,1,2,1,'Decisión histórica'))
        with self.store.connect() as db:
            db.execute('INSERT INTO block_versions(id,block_id,version) VALUES (1,1,1)')
            db.execute('INSERT INTO period_blocks(id,period_id,block_version_id) VALUES (1,1,1)')
            db.execute("INSERT INTO plans(id,period_id,origin,status,fingerprint,created_by,created_at) VALUES (1,1,'MANUAL','SUSTITUIDA','historico',1,'now')")
            db.execute("INSERT INTO english_groups(id,plan_id,period_id,code,period_block_id,teacher_id) VALUES (1,1,1,'ING-1',1,1)")
            db.execute('INSERT INTO student_assignments(plan_id,group_id,student_id) VALUES (1,1,1)')
        self.sync.sync_students(self.session,Provider([student(nombre='Nombre actualizado')]),1)
        self.sync.sync_teachers(self.session,Provider([teacher('t2')]))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT active FROM teachers WHERE id=1').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT teacher_id FROM english_groups WHERE id=1').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT student_id FROM student_assignments WHERE plan_id=1').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM level_decisions').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(self.store.current_level(1,1)['level_id'],2)


if __name__ == '__main__':
    unittest.main()
