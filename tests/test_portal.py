from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from ingles.bootstrap import bootstrap
from ingles.integrations import ConfigurableTestAuth, Identity, VerifiedMockarooMapping, Batch
from ingles.institutional_services import AuthService, AccessDenied, SyncService
from ingles.local_fixtures import LocalFixture
from ingles.portal_services import PortalService
from ingles.relational_storage import RelationalStore


class PortalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name) / 'portal.db')
        self.store = RelationalStore(self.path)
        bootstrap(self.store, 'admin.demo')
        self.now = 10
        self.auth = AuthService(self.store, ConfigurableTestAuth({'admin': ('fake', Identity('desarrollo', 'admin.demo')),
                                                                  'teacher': ('fake', Identity('desarrollo', 'docente.demo'))}),
                                session_seconds=30, clock=lambda: self.now)
        self.token = self.auth.login('admin', 'fake')
        self.portal = PortalService(self.store, self.auth)

    def test_expiration_logout_and_bootstrap(self):
        with self.assertRaises(ValueError):
            bootstrap(self.store, 'other')
        self.now = 40
        with self.assertRaises(AccessDenied):
            self.portal.periods(self.token)
        token = self.auth.login('admin', 'fake')
        self.auth.logout(token)
        with self.assertRaises(AccessDenied):
            self.auth.profile(token)

    def test_fixtures_permissions_and_persistence(self):
        self.portal.create_period(self.token, 'P1', date(2026, 1, 1), date(2026, 4, 30))
        sync = SyncService(self.store, self.auth, 'local_demo', 'desarrollo')
        sync.sync_students(self.token, LocalFixture('ALUMNOS'), 1)
        sync.sync_teachers(self.token, LocalFixture('MAESTROS'))
        self.assertEqual(len(self.portal.imported(self.token, 'students', 1)), 1)
        teacher = self.auth.login('teacher', 'fake')
        with self.assertRaises(AccessDenied):
            self.portal.imported(teacher, 'students', 1)
        with self.assertRaises(AccessDenied):
            self.portal.create_period(teacher, 'X', date.today(), date.today())
        self.assertEqual(self.portal.teacher_groups(teacher, 1), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0], 1)

    def test_verified_field_mapping_and_identity_is_explicit(self):
        class P:
            def fetch(self):
                return Batch([{'numero_empleado': 123, 'nombre': 'A', 'tipo_contratacion': 'PA'}])
        row = VerifiedMockarooMapping(P(), 'MAESTROS').fetch().records[0]
        self.assertIsNone(row['sujeto_identidad'])
        row = VerifiedMockarooMapping(P(), 'MAESTROS', {'123': 'verified-subject'}).fetch().records[0]
        self.assertEqual(row['sujeto_identidad'], 'verified-subject')
        class Students:
            def fetch(self):
                return Batch([{'matricula': 123, 'nombre': 'A', 'carrera': 'C', 'grupo_academico': 'G',
                               'edificio': '1', 'turno': 'M', 'estatus_escolar': 'activo'}])
        self.assertEqual(VerifiedMockarooMapping(Students(), 'ALUMNOS').fetch().records[0]['matricula'], '123')

    def test_teacher_only_sees_own_published_students(self):
        self.portal.create_period(self.token, 'P1', date(2026, 1, 1), date(2026, 4, 30))
        sync = SyncService(self.store, self.auth, 'local_demo', 'desarrollo')
        sync.sync_students(self.token, LocalFixture('ALUMNOS'), 1)
        sync.sync_teachers(self.token, LocalFixture('MAESTROS'))
        with self.store.connect() as db:
            db.execute("INSERT INTO block_versions(id,block_id,version) VALUES (1,1,1)")
            db.execute("INSERT INTO period_blocks(id,period_id,block_version_id) VALUES (1,1,1)")
            db.execute("INSERT INTO plans(id,period_id,origin,status,fingerprint,created_by,created_at) VALUES (1,1,'MANUAL','PUBLICADA','x',1,'now')")
            db.execute("INSERT INTO english_groups(id,plan_id,period_id,code,period_block_id,teacher_id) VALUES (1,1,1,'ING-1',1,1)")
            db.execute('INSERT INTO student_assignments(plan_id,group_id,student_id) VALUES (1,1,1)')
        teacher = self.auth.login('teacher', 'fake')
        self.assertEqual(self.portal.teacher_groups(teacher, 1)[0]['code'], 'ING-1')
        self.assertEqual(self.portal.teacher_students(teacher, 1)[0]['matricula'], 'DEMO001')
        with self.store.connect() as db:
            db.execute('UPDATE english_groups SET teacher_id=NULL WHERE id=1')
        self.assertEqual(self.portal.teacher_students(teacher, 1), [])

    def test_streamlit_login_navigation_logout(self):
        env = {'INGLES_RELATIONAL_DB_PATH': self.path,
               'INGLES_DEV_AUTH': '{"admin":{"password":"fake","subject":"admin.demo"},"docente":{"password":"fake2","subject":"docente.demo"}}'}
        with patch.dict(os.environ, env):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app_institucional.py'), default_timeout=30).run()
            self.assertFalse(app.exception)
            app.text_input[0].input('admin')
            app.text_input[1].input('fake')
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Panel administrativo' in x.value for x in app.subheader))
            app.radio[0].set_value('Periodos').run()
            self.assertFalse(app.exception)
            app.text_input[0].input('PERIODO-DEMO')
            next(b for b in app.button if b.label == 'Crear periodo').click().run()
            self.assertFalse(app.exception)
            app.radio[0].set_value('Sincronización').run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label == 'Sincronizar').click().run()
            self.assertFalse(app.exception)
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0], 1)
            next(r for r in app.radio if r.label == 'Datos').set_value('Maestros').run()
            next(b for b in app.button if b.label == 'Sincronizar').click().run()
            self.assertFalse(app.exception)
            for page in ('Alumnos', 'Docentes', 'Niveles', 'Bloques horarios', 'Configuración del algoritmo', 'Incidencias'):
                next(r for r in app.radio if r.label == 'Navegación').set_value(page).run()
                self.assertFalse(app.exception, page)
            next(b for b in app.button if b.label == 'Cerrar sesión').click().run()
            self.assertTrue(any(b.label == 'Iniciar sesión' for b in app.button))
            app.text_input[0].input('docente')
            app.text_input[1].input('fake2')
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio[0].options, ['Mi panel', 'Mis alumnos y grupos', 'Alumnos', 'Niveles', 'Incidencias'])
            for page in ('Alumnos', 'Niveles', 'Incidencias'):
                next(r for r in app.radio if r.label == 'Navegación').set_value(page).run()
                self.assertFalse(app.exception, page)


if __name__ == '__main__':
    unittest.main()
