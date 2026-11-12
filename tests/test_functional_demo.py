"""Recorrido funcional con datos ficticios, interfaz Streamlit y SQLite temporal."""
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import load_workbook
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from ingles.bootstrap import bootstrap
from ingles.institutional_reports import InstitutionalReports
from ingles.institutional_services import AuthService
from ingles.integrations import ConfigurableTestAuth, Identity
from ingles.planning_service import PlanningService, proposal_fingerprint
from ingles.relational_scheduler import overlap
from ingles.relational_storage import RelationalStore
from ingles.version_service import VersionService, _read
from ingles.portal_services import PortalService


APP=str(Path(__file__).resolve().parents[1]/'app_institucional.py')


def button(app,label): return next(b for b in app.button if b.label==label)
def navigation(app,page):
    next(r for r in app.radio if r.label=='Navegación').set_value(page).run(timeout=120)


class FullDemoFlow(unittest.TestCase):
    def test_full_fictitious_flow_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'demo.sqlite3'); store=RelationalStore(path); bootstrap(store,'secretaria.demo')
            credentials={'secretaria':{'password':'ficticia','subject':'secretaria.demo'}}
            for i in range(1,13):
                credentials[f'docente{i:02}']={'password':'ficticia','subject':'docente.demo' if i==1 else f'docente.demo.{i:02}'}
            env={'INGLES_RELATIONAL_DB_PATH':path,'INGLES_DEMO_DB_PATH':path,'INGLES_DEMO_MODE':'1','INGLES_DEV_AUTH':json.dumps(credentials)}
            with patch.dict(os.environ,env):
                app=AppTest.from_file(APP,default_timeout=120).run()
                app.text_input[0].input('secretaria'); app.text_input[1].input('ficticia'); button(app,'Iniciar sesión').click().run()
                self.assertFalse(app.exception)
                button(app,'Cargar escenario de demostración').click().run()
                self.assertFalse(app.exception)
                with store.connect() as db:
                    period=db.execute("SELECT id FROM periods WHERE code='DEMO-SEP-DIC-2026'").fetchone()[0]
                    next_period=db.execute("SELECT id FROM periods WHERE code='DEMO-ENE-ABR-2027'").fetchone()[0]
                    self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0],200)
                provider=ConfigurableTestAuth({'a':('ficticia',Identity('desarrollo','secretaria.demo'))})
                auth=AuthService(store,provider); admin=auth.login('a','ficticia')
                planning=PlanningService(store,auth); versions=VersionService(store,auth)
                navigation(app,'Generación de grupos')
                next(s for s in app.selectbox if s.label=='Cuatrimestre a organizar').set_value(period).run()
                button(app,'Generar y guardar propuesta').click().run(timeout=120)
                self.assertFalse(app.exception)
                first=planning.proposals(admin,period)[0]['id']
                first_plan=planning.proposal(admin,first)
                self.assertEqual(sum(len(g['students']) for g in first_plan['groups']),158)
                self.assertEqual(len(first_plan['pending']),12)
                self.assertTrue(any(len(g['levels'])==2 for g in first_plan['groups']))
                self.assertTrue(any(len(g['students'])<25 for g in first_plan['groups']))
                self.assertTrue(any(len({s['career'] for s in g['students']})>1 for g in first_plan['groups']))
                button(app,'Generar y guardar propuesta').click().run(timeout=120)
                self.assertFalse(app.exception)
                options=planning.proposals(admin,period)
                self.assertGreaterEqual(len(options),2,'No se encontró una segunda propuesta dentro del tiempo configurado.')
                second=options[0]['id']; self.assertTrue(versions.compare(admin,first,second))
                print('Escenario ficticio: 200 alumnos, 158 elegibles; primera y segunda solución:',first_plan['metrics']['status'],planning.proposal(admin,second)['metrics']['status'],flush=True)
                # Locate a teacher change that is valid and differs from stored versions.
                plan=planning.proposal(admin,second)
                blocks={b['id']:b for b in plan['blocks']}
                with store.connect() as db:
                    _,snap,raw,_=_read(db,second)
                    fingerprints={r[0] for r in db.execute('SELECT fingerprint FROM plans WHERE period_id=?',(period,))}
                selected=None
                for g in plan['groups']:
                    for t in plan['teachers']:
                        assigned=[other for other in plan['groups'] if other['teacher_id']==t['id'] and other['code']!=g['code']]
                        b=blocks[g['period_block_id']]
                        if t['id']==g['teacher_id'] or t['max_hours']<7*(len(assigned)+1) or t['max_blocks']<len(assigned)+1:
                            continue
                        if not {s['id'] for s in b['slots']}<=set(t['availability']) or any(overlap(b['slots'],blocks[x['period_block_id']]['slots']) for x in assigned):
                            continue
                        from copy import deepcopy
                        candidate=deepcopy(raw); next(x for x in candidate['groups'] if x['id']==g['code'])['teacher']=t['id']
                        if proposal_fingerprint(candidate,snap) not in fingerprints:
                            selected=(g['code'],t['id']); break
                    if selected: break
                self.assertIsNotNone(selected,'No se encontró un cambio docente válido para el escenario.')
                navigation(app,'Grupos de inglés')
                next(s for s in app.selectbox if s.label=='Cuatrimestre').set_value(period).run()
                next(s for s in app.selectbox if s.label=='Versión').set_value(second).run()
                next(s for s in app.selectbox if s.label=='Grupo').set_value(selected[0]).run()
                next(s for s in app.selectbox if s.label=='Nuevo docente').set_value(selected[1])
                next(x for x in app.text_input if x.label=='Motivo del cambio').input('Prueba ficticia')
                button(app,'Validar y crear versión derivada').click().run()
                self.assertFalse(app.exception)
                derived=planning.proposals(admin,period)[0]['id']; self.assertNotEqual(derived,second)
                navigation(app,'Historial y versiones')
                next(s for s in app.selectbox if s.label=='Cuatrimestre').set_value(period).run()
                self.assertFalse(app.exception)
                navigation(app,'Grupos de inglés')
                next(s for s in app.selectbox if s.label=='Cuatrimestre').set_value(period).run()
                next(s for s in app.selectbox if s.label=='Versión').set_value(derived).run()
                next(c for c in app.checkbox if c.label.startswith('Confirmo la publicación parcial')).check()
                next(c for c in app.checkbox if c.label.startswith('Confirmo que deseo publicar')).check()
                button(app,'Publicar propuesta').click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any('publicada' in msg.value for msg in app.success))
                with store.connect() as db:
                    assigned_teacher=db.execute('SELECT teacher_id FROM english_groups WHERE plan_id=? LIMIT 1',(derived,)).fetchone()[0]
                    subject=db.execute('SELECT subject FROM users WHERE teacher_id=?',(assigned_teacher,)).fetchone()[0]
                username=next(u for u,c in credentials.items() if c['subject']==subject)
                button(app,'Cerrar sesión').click().run()
                app.text_input[0].input(username); app.text_input[1].input('ficticia'); button(app,'Iniciar sesión').click().run()
                navigation(app,'Mis alumnos y grupos')
                next(s for s in app.selectbox if s.label=='Periodo').set_value(period).run()
                self.assertFalse(app.exception)
                teacher_auth=AuthService(store,ConfigurableTestAuth({username:('ficticia',Identity('desarrollo',subject))}))
                teacher_session=teacher_auth.login(username,'ficticia')
                self.assertTrue(PortalService(store,teacher_auth).teacher_groups(teacher_session,period))
                self.assertTrue(PortalService(store,teacher_auth).teacher_students(teacher_session,period))
                navigation(app,'Alumnos')
                next(s for s in app.selectbox if s.label=='Cuatrimestre actual').set_value(period).run()
                next(s for s in app.selectbox if s.label=='Consultar próximo nivel para').set_value(next_period).run()
                selected_student=next(s for s in app.selectbox if s.label=='Alumno autorizado').value
                button(app,'Guardar próximo nivel').click().run()
                self.assertFalse(app.exception)
                with store.connect() as db:
                    self.assertIsNotNone(db.execute('SELECT id FROM level_decisions WHERE student_id=? AND target_period_id=?',(selected_student,next_period)).fetchone())
                    current_level=db.execute('SELECT level_id FROM level_decisions WHERE student_id=? AND target_period_id=? ORDER BY id DESC LIMIT 1',(selected_student,period)).fetchone()[0]
                navigation(app,'Incidencias')
                next(s for s in app.selectbox if s.label=='Cuatrimestre actual').set_value(period).run()
                next(s for s in app.selectbox if s.label=='Alumno autorizado').set_value(selected_student).run()
                next(s for s in app.selectbox if s.label=='Nivel solicitado').set_value(min(current_level+1,9))
                app.text_area[0].input('Solicitud de prueba ficticia')
                button(app,'Enviar incidencia').click().run()
                self.assertFalse(app.exception)
                button(app,'Cerrar sesión').click().run()
                app.text_input[0].input('secretaria'); app.text_input[1].input('ficticia'); button(app,'Iniciar sesión').click().run()
                navigation(app,'Incidencias')
                next(s for s in app.selectbox if s.label=='Cuatrimestre actual').set_value(period).run()
                next(x for x in app.text_input if x.label=='Resolución').input('Revisada en prueba ficticia')
                button(app,'Guardar resolución').click().run()
                self.assertFalse(app.exception)
                with store.connect() as db:
                    self.assertEqual(db.execute('SELECT status FROM incidents ORDER BY id DESC LIMIT 1').fetchone()[0],'APROBADA')
                    self.assertEqual(db.execute('SELECT application_status FROM incident_context ORDER BY incident_id DESC LIMIT 1').fetchone()[0],'PENDIENTE')
                navigation(app,'Reportes')
                next(s for s in app.selectbox if s.label=='Periodo del reporte').set_value(period).run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.get('download_button')),2)
                reports=InstitutionalReports(store,auth)
                self.assertEqual(len(reports.collect(admin,derived,'alumnos_academico')['rows']),200)
                xlsx=load_workbook(BytesIO(reports.excel(admin,derived,'alumnos_ingles')))
                pdf=PdfReader(BytesIO(reports.pdf(admin,derived,'alumnos_ingles')))
                self.assertIn('PUBLICADA',xlsx.active['A3'].value)
                self.assertIn('PUBLICADA',' '.join(p.extract_text() for p in pdf.pages))
                # A new connection and a new app session read the same saved state.
                reopened=RelationalStore(path); reopened.initialize()
                with reopened.connect() as db:
                    self.assertEqual(db.execute('SELECT status FROM plans WHERE id=?',(derived,)).fetchone()[0],'PUBLICADA')
                    self.assertEqual(db.execute('SELECT count(*) FROM students').fetchone()[0],200)
                restarted=AppTest.from_file(APP,default_timeout=120).run()
                restarted.text_input[0].input('secretaria'); restarted.text_input[1].input('ficticia'); button(restarted,'Iniciar sesión').click().run()
                self.assertFalse(restarted.exception)
                self.assertTrue(any('Panel administrativo' in s.value for s in restarted.subheader))
                print('Recorrido ficticio: edición, publicación parcial, consulta docente, próximo nivel, incidencia, Excel y PDF verificados tras reiniciar.',flush=True)


if __name__=='__main__': unittest.main()
