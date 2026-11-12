from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from openpyxl import load_workbook
from pypdf import PdfReader

from ingles.bootstrap import bootstrap
from ingles.demo_scenario import DemoService
from ingles.institutional_reports import InstitutionalReports, REPORTS
from ingles.integrations import ConfigurableTestAuth, Identity, MockarooProvider, IntegrationError, provider_from_environment
from ingles.institutional_services import AuthService, AccessDenied, SyncService
from ingles.planning_service import PlanningService
from ingles.relational_storage import RelationalStore
from ingles.version_service import VersionService


class DemoTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path=str(Path(tmp.name)/'demo.sqlite3'); self.store=RelationalStore(self.path)
        bootstrap(self.store,'admin')
        self.auth=AuthService(self.store,ConfigurableTestAuth({'a':('fake',Identity('desarrollo','admin'))}))
        self.token=self.auth.login('a','fake')
        self.env=patch.dict(os.environ,{'INGLES_DEMO_MODE':'1','INGLES_DEMO_DB_PATH':self.path}); self.env.start(); self.addCleanup(self.env.stop)

    def test_demo_is_isolated_idempotent_and_complete(self):
        demo=DemoService(self.store,self.auth)
        self.assertTrue(demo.load(self.token)['created'])
        self.assertFalse(demo.load(self.token)['created'])
        with self.store.connect() as db:
            for table,expected in [('students',200),('teachers',12),('careers',4),('academic_groups',10),('period_blocks',5)]:
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],expected)
            self.assertEqual(db.execute('SELECT count(*) FROM enrollments WHERE active=0').fetchone()[0],10)
            self.assertEqual(db.execute('SELECT count(*) FROM time_slots WHERE calendar_version != ?',('DEMO-FICTICIO',)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM level_decisions WHERE target_period_id=1 AND level_id=6').fetchone()[0],7)
            self.assertEqual(db.execute('SELECT count(*) FROM level_decisions WHERE target_period_id=1 AND level_id=7').fetchone()[0],5)
            self.assertGreaterEqual(db.execute('SELECT count(DISTINCT max_hours) FROM teacher_period_rules').fetchone()[0],2)
            self.assertGreaterEqual(db.execute('''SELECT count(*) FROM teacher_period_rules r
                WHERE NOT EXISTS (SELECT 1 FROM teacher_availability a WHERE a.rule_id=r.id)''').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        counts=PlanningService(self.store,self.auth).overview(self.token,1)
        self.assertEqual((counts['active'],counts['eligible'],counts['exempt'],counts['missing_level']),(190,158,20,12))
        with self.assertRaises(AccessDenied): demo.load('invalid')
        with self.assertRaisesRegex(ValueError,'base institucional separada'):
            SyncService(self.store,self.auth,'mockaroo','desarrollo').sync_students(self.token,object(),1)

    def test_refuses_existing_academic_data_and_disabled_mode(self):
        with patch.dict(os.environ,{'INGLES_DEMO_MODE':'0'}):
            with self.assertRaises(ValueError): DemoService(self.store,self.auth).load(self.token)
        with self.store.connect() as db:
            db.execute("INSERT INTO periods(code,start_date,end_date) VALUES ('REAL','2026-01-01','2026-04-30')")
        with self.assertRaises(ValueError): DemoService(self.store,self.auth).load(self.token)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0],0)


class ReportTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store=RelationalStore(Path(tmp.name)/'reports.db'); bootstrap(self.store,'admin')
        self.auth=AuthService(self.store,ConfigurableTestAuth({'a':('fake',Identity('desarrollo','admin'))}))
        self.token=self.auth.login('a','fake')
        with self.store.connect() as db:
            db.execute("INSERT INTO periods(id,code,start_date,end_date) VALUES (1,'PERIODO-FICTICIO','2026-01-01','2026-04-30')")
            db.execute("INSERT INTO careers(id,provider,external_id,name) VALUES (1,'p','c','Carrera')")
            db.execute("INSERT INTO academic_groups(id,career_id,provider,external_id,code) VALUES (1,1,'p','g','G')")
            for i in range(1,11):
                name='=1+1' if i==1 else f'Alumno {i}'
                db.execute("INSERT INTO students(id,provider,external_id,enrollment,name,school_status) VALUES (?,'p',?,?,?,'activo')",(i,str(i),f'00{i}',name))
                db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id,active) VALUES (?,1,1,?)',(i,int(i!=10)))
                if i<9: db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (?,1,2,1,'now')",(i,))
            db.execute("INSERT INTO teachers(id,provider,external_id,name,employment_type) VALUES (1,'p','t','Docente','PA')")
            db.execute("INSERT INTO teachers(id,provider,external_id,name,employment_type) VALUES (2,'p','t2','Docente 2','PTC')")
            db.execute('INSERT INTO teacher_period_rules(id,teacher_id,period_id,participates,max_hours,max_blocks) VALUES (1,1,1,1,26,4)')
            db.execute('INSERT INTO teacher_period_rules(id,teacher_id,period_id,participates,max_hours,max_blocks) VALUES (2,2,1,1,35,5)')
            db.execute('INSERT INTO block_versions(id,block_id,version) VALUES (1,1,1)')
            db.execute('INSERT INTO period_blocks(id,period_id,block_version_id) VALUES (1,1,1)')
            for day,n in ((1,1),(1,2),(2,1),(2,2),(3,1),(3,2),(4,1)):
                sid=day*10+n; a,b=(('08:30','09:15') if n==1 else ('09:15','10:00'))
                db.execute("INSERT INTO time_slots(id,calendar_version,day,slot_number,starts,ends) VALUES (?,'x',?,?,?,?)",(sid,day,n,a,b))
                db.execute('INSERT INTO block_slots VALUES (1,?)',(sid,));db.execute('INSERT INTO teacher_availability VALUES (1,?)',(sid,));db.execute('INSERT INTO teacher_availability VALUES (2,?)',(sid,))
        self.pid=PlanningService(self.store,self.auth).generate_and_save(self.token,1)['plan_id']
        self.reports=InstitutionalReports(self.store,self.auth)

    def test_each_report_downloads_as_excel_and_pdf(self):
        for kind in REPORTS:
            with self.subTest(kind=kind):
                book=load_workbook(BytesIO(self.reports.excel(self.token,self.pid,kind)))
                sheet=book.active
                self.assertIn('PERIODO-FICTICIO',sheet['A2'].value)
                self.assertIn('PROPUESTA',sheet['A3'].value)
                pdf=PdfReader(BytesIO(self.reports.pdf(self.token,self.pid,kind)))
                text=' '.join(p.extract_text() for p in pdf.pages)
                self.assertIn('PERIODO-FICTICIO',text)
                self.assertIn('PROPUESTA',text)
        book=load_workbook(BytesIO(self.reports.excel(self.token,self.pid,'alumnos_ingles')))
        values=[c for row in book.active.iter_rows() for c in row if c.value=='=1+1']
        self.assertEqual(len(values),1); self.assertEqual(values[0].data_type,'s')
        self.assertEqual(len(self.reports.collect(self.token,self.pid,'pendientes')['rows']),1)
        self.assertEqual(len(self.reports.collect(self.token,self.pid,'alumnos_ingles')['rows']),8)
        self.assertEqual(len(self.reports.collect(self.token,self.pid,'grupos_bloque')['rows']),1)
        self.assertEqual(sum(row[2] for row in self.reports.collect(self.token,self.pid,'carga_docente')['rows']),1)
        self.assertTrue(any('pendientes' in str(row).lower() for row in self.reports.collect(self.token,self.pid,'conflictos')['rows']))
        academic=self.reports.collect(self.token,self.pid,'alumnos_academico')
        self.assertEqual(len(academic['rows']),10)
        self.assertEqual(sum(row[-1]=='Inactivo' for row in academic['rows']),1)

    def test_report_authorization_and_historical_snapshot(self):
        with self.assertRaises(AccessDenied): self.reports.excel('bad',self.pid,'resumen')
        with self.store.connect() as db: db.execute("UPDATE students SET name='Nuevo' WHERE id=2")
        rows=self.reports.collect(self.token,self.pid,'alumnos_ingles')['rows']
        self.assertIn('Alumno 2',[row[3] for row in rows])
        with self.store.connect() as db: db.execute("UPDATE students SET name='Inactivo cambiado' WHERE id=10")
        academic=self.reports.collect(self.token,self.pid,'alumnos_academico')
        self.assertIn('Alumno 10',[row[3] for row in academic['rows']])

    def test_derived_version_preserves_inactive_snapshot(self):
        plan=PlanningService(self.store,self.auth).proposal(self.token,self.pid)
        group=plan['groups'][0]; target=1 if group['teacher_id']==2 else 2
        derived=VersionService(self.store,self.auth).modify(self.token,self.pid,kind='docente',group=group['code'],value=target,reason='Prueba')
        with self.store.connect() as db: db.execute("UPDATE students SET name='Cambio posterior' WHERE id=10")
        academic=self.reports.collect(self.token,derived,'alumnos_academico')
        self.assertIn('Alumno 10',[row[3] for row in academic['rows']])
        self.assertEqual(sum(row[-1]=='Inactivo' for row in academic['rows']),1)

    def test_old_version_without_inactive_snapshot_is_identified(self):
        with self.store.connect() as db:
            db.execute('DROP TABLE plan_inactive_students')
            db.execute('DROP TABLE plan_report_meta')
        self.store.initialize()
        report=self.reports.collect(self.token,self.pid,'alumnos_academico')
        self.assertIn('no conserva',report['scope'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM plans WHERE id=?',(self.pid,)).fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_missing_configuration_names_variable(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'INGLES_ALUMNOS_URL'): provider_from_environment('ALUMNOS')
            with self.assertRaisesRegex(ValueError,'INGLES_MAESTROS_URL'): provider_from_environment('MAESTROS')

    def test_mockaroo_http_error_never_exposes_key(self):
        provider=MockarooProvider('https://example.invalid/?key=secret-fake')
        error=HTTPError('https://example.invalid/?key=secret-fake',403,'forbidden',None,None)
        with patch('ingles.integrations.urlopen',side_effect=error):
            with self.assertRaises(IntegrationError) as raised: provider.fetch()
        self.assertIn('401/403',str(raised.exception))
        self.assertNotIn('secret-fake',str(raised.exception))

    def test_teacher_cannot_export_administrative_reports(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO users(id,identity_provider,subject,teacher_id) VALUES (2,'desarrollo','docente',1)")
            db.execute("INSERT INTO user_roles VALUES (2,'DOCENTE')")
        auth=AuthService(self.store,ConfigurableTestAuth({'d':('fake',Identity('desarrollo','docente'))}))
        token=auth.login('d','fake')
        with self.assertRaises(AccessDenied): InstitutionalReports(self.store,auth).pdf(token,self.pid,'resumen')


if __name__=='__main__': unittest.main()
