from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ingles.academic_services import AcademicService
from ingles.bootstrap import bootstrap
from ingles.integrations import ConfigurableTestAuth, Identity
from ingles.institutional_services import AccessDenied, AuthService, SyncService
from ingles.local_fixtures import LocalFixture
from ingles.portal_services import PortalService
from ingles.relational_storage import RelationalStore


class AcademicTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store=RelationalStore(Path(tmp.name)/'academic.db'); bootstrap(self.store,'admin')
        provider=ConfigurableTestAuth({'a':('x',Identity('desarrollo','admin')),'t':('x',Identity('desarrollo','docente.demo'))})
        self.auth=AuthService(self.store,provider); self.admin=self.auth.login('a','x')
        self.portal=PortalService(self.store,self.auth); self.s=AcademicService(self.store,self.auth)
        self.portal.create_period(self.admin,'P1',date(2026,1,1),date(2026,4,30))
        self.portal.create_period(self.admin,'P2',date(2026,5,1),date(2026,8,31))
        sync=SyncService(self.store,self.auth,'local_demo','desarrollo')
        sync.sync_students(self.admin,LocalFixture('ALUMNOS'),1); sync.sync_teachers(self.admin,LocalFixture('MAESTROS'))
        self.teacher=self.auth.login('t','x')

    def test_next_level_requires_permission_and_keeps_history(self):
        self.s.set_level(self.admin,1,1,1,2,initial=True)
        with self.assertRaises(AccessDenied): self.s.set_level(self.teacher,1,1,2,3)
        self.s.grant(self.admin,1,1,1)
        self.s.set_level(self.teacher,1,1,2,3,'avanza')
        self.s.set_level(self.teacher,1,1,2,2,'repite')
        self.assertEqual(self.s.students(self.teacher,1,2)[0]['proximo_nivel'],'Basic 1')
        self.assertEqual(len(self.s.level_history(self.teacher,1,1)),3)
        self.s.grant(self.admin,1,1,1,False)
        with self.assertRaises(AccessDenied): self.s.level_history(self.teacher,1,1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM english_groups').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM history WHERE entity_type='nivel'").fetchone()[0],3)

    def test_blocks_and_teacher_limits(self):
        for day,start,end in [(1,'08:30','09:15'),(1,'09:15','10:00'),(2,'08:30','09:15'),(2,'09:15','10:00'),(3,'08:30','09:15'),(3,'09:15','10:00'),(4,'08:30','09:15')]:
            self.s.add_slot(self.admin,day,start,end)
        with self.assertRaises(ValueError): self.s.add_slot(self.admin,1,'11:10','11:55')
        with self.assertRaises(ValueError): self.s.add_slot(self.admin,1,'08:45','09:30')
        ids=[r['id'] for r in self.s.slots(self.admin)]
        with self.assertRaises(ValueError): self.s.save_block(self.admin,1,1,ids[:6],True)
        self.s.save_block(self.admin,1,1,ids,True)
        self.s.save_block(self.admin,1,1,ids,False)
        self.assertEqual(self.s.blocks(self.admin,1)[0]['version'],2)
        with self.assertRaises(ValueError): self.s.set_teacher_rules(self.admin,1,1,True,28,5,ids)
        with self.assertRaises(AccessDenied): self.s.set_teacher_rules(self.teacher,1,1,True,28,4,ids)
        self.s.set_teacher_rules(self.admin,1,1,True,26,4,ids)
        self.assertEqual(self.s.teachers(self.admin,1)[0]['max_horas'],26)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM block_versions').fetchone()[0],2)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_incident_approval_and_rejection_do_not_modify_level(self):
        self.s.set_level(self.admin,1,1,1,2,initial=True); self.s.grant(self.admin,1,1,1)
        self.s.create_incident(self.teacher,1,1,3,'Solicitud')
        with self.store.connect() as db:
            db.execute('INSERT INTO block_versions(id,block_id,version) VALUES (1,1,1)')
            db.execute('INSERT INTO period_blocks(id,period_id,block_version_id) VALUES (1,1,1)')
            db.execute("INSERT INTO plans(id,period_id,origin,status,fingerprint,created_by,created_at) VALUES (1,1,'MANUAL','PUBLICADA','a',1,'now')")
            db.execute("INSERT INTO english_groups(id,plan_id,period_id,code,period_block_id,teacher_id) VALUES (1,1,1,'G1',1,1)")
            db.execute('INSERT INTO student_assignments(plan_id,group_id,student_id) VALUES (1,1,1)')
        self.s.resolve_incident(self.admin,1,True,'Aceptar')
        self.assertEqual(self.s.incidents(self.admin,1)[0]['aplicacion'],'PENDIENTE')
        self.s.create_incident(self.teacher,1,1,3,'Otra solicitud')
        self.s.resolve_incident(self.admin,2,False,'No procede')
        self.assertEqual(self.s.incidents(self.admin,1)[0]['estado'],'RECHAZADA')
        self.assertEqual(self.store.current_level(1,1)['level_id'],2)
        with self.assertRaises(ValueError): self.s.resolve_incident(self.admin,1,True,'Otra vez')
        with self.assertRaises(AccessDenied): self.s.resolve_incident(self.teacher,2,True,'x')

    def test_approval_without_published_group_applies_level(self):
        self.s.set_level(self.admin,1,1,1,2,initial=True); self.s.grant(self.admin,1,1,1)
        self.s.create_incident(self.teacher,1,1,3,'Solicitud')
        self.s.resolve_incident(self.admin,1,True,'Aceptado')
        self.assertEqual(self.s.incidents(self.admin,1)[0]['aplicacion'],'APLICADO')
        self.assertEqual(self.store.current_level(1,1)['level_id'],3)

    def test_reinitializing_previous_relational_schema_preserves_data(self):
        self.s.set_level(self.admin,1,1,1,2,initial=True)
        with self.store.connect() as db:
            db.execute('DROP TABLE incident_context')
            db.execute('DROP TABLE teacher_student_permissions')
        self.store.initialize()
        self.assertEqual(self.store.current_level(1,1)['level_id'],2)
        self.s.grant(self.admin,1,1,1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_algorithm_settings_and_manual_block_catalog_permissions(self):
        with self.assertRaises(AccessDenied): self.s.set_settings(self.teacher,1,8,28,35,20)
        with self.assertRaises(ValueError): self.s.set_settings(self.admin,1,7,28,35,20)
        self.assertEqual(self.s.set_settings(self.admin,1,8,28,35,20),1)
        self.assertEqual(self.s.set_settings(self.admin,1,9,27,34,30),2)
        self.assertEqual(self.s.settings(self.admin,1)['version'],2)
        with self.assertRaises(AccessDenied): self.s.create_block(self.teacher,'B6','Nuevo')
        self.s.create_block(self.admin,'B6','Bloque adicional')
        self.assertEqual(len(self.s.blocks(self.admin,1)),6)
        with self.assertRaises(ValueError): self.s.create_block(self.admin,'B6','Duplicado')

    def test_teacher_remaining_hours_and_weekly_availability(self):
        with self.assertRaises(AccessDenied): self.s.teacher_load(self.teacher,1,1)
        for day,start,end in [(1,'08:30','09:15'),(1,'09:15','10:00'),(2,'08:30','09:15'),(2,'09:15','10:00'),(3,'08:30','09:15'),(3,'09:15','10:00'),(4,'08:30','09:15'),(5,'08:30','09:15')]:
            self.s.add_slot(self.admin,day,start,end)
        ids=[r['id'] for r in self.s.slots(self.admin)]
        self.s.set_teacher_rules(self.admin,1,1,True,26,4,ids)
        self.s.save_block(self.admin,1,1,ids[:7],True)
        with self.store.connect() as db:
            db.execute("INSERT INTO plans(id,period_id,origin,status,fingerprint,created_by,created_at) VALUES (1,1,'MANUAL','PUBLICADA','load',1,'now')")
            block=db.execute('SELECT id FROM period_blocks WHERE period_id=1').fetchone()[0]
            db.execute("INSERT INTO english_groups(plan_id,period_id,code,period_block_id,teacher_id) VALUES (1,1,'ING-1',?,1)",(block,))
        load=self.s.teacher_load(self.admin,1,1)
        self.assertEqual((load['remaining_hours'],load['remaining_blocks']),(19,3))
        self.assertEqual(len(load['groups']),1)
        self.assertEqual(len(load['remaining']),1)


if __name__=='__main__': unittest.main()
