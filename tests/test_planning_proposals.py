from pathlib import Path
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from ingles.bootstrap import bootstrap
from ingles.integrations import ConfigurableTestAuth, Identity
from ingles.institutional_services import AuthService, AccessDenied
from ingles.planning_service import PlanningService, DuplicateProposal, StalePlanningData, proposal_fingerprint
from ingles.relational_planning import load_snapshot
from ingles.relational_scheduler import solve_snapshot
from ingles.relational_storage import RelationalStore
from ingles.version_service import VersionService


class ProposalTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store=RelationalStore(Path(tmp.name)/'planning.db'); bootstrap(self.store,'admin')
        self.auth=AuthService(self.store,ConfigurableTestAuth({'admin':('fake',Identity('desarrollo','admin'))}))
        self.session=self.auth.login('admin','fake'); self.service=PlanningService(self.store,self.auth)
        with self.store.connect() as db:
            db.execute("INSERT INTO periods(id,code,start_date,end_date) VALUES (1,'P1','2026-01-01','2026-04-30')")
            db.execute("INSERT INTO careers(id,provider,external_id,name) VALUES (1,'p','c','Carrera')")
            db.execute("INSERT INTO academic_groups(id,career_id,provider,external_id,code) VALUES (1,1,'p','g','G')")
            for i in range(1,10):
                db.execute("INSERT INTO students(id,provider,external_id,enrollment,name,school_status) VALUES (?,'p',?,?,?,'activo')",(i,str(i),str(i),'Alumno '+str(i)))
                db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id) VALUES (?,1,1)',(i,))
                if i<9:
                    db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (?,1,2,1,'now')",(i,))
            db.execute("INSERT INTO teachers(id,provider,external_id,name,employment_type) VALUES (1,'p','t','Docente','PA')")
            db.execute('INSERT INTO teacher_period_rules(id,teacher_id,period_id,participates,max_hours,max_blocks) VALUES (1,1,1,1,26,4)')
            db.execute('INSERT INTO block_versions(id,block_id,version) VALUES (1,1,1)')
            db.execute('INSERT INTO period_blocks(id,period_id,block_version_id) VALUES (1,1,1)')
            for day,number in ((1,1),(1,2),(2,1),(2,2),(3,1),(3,2),(4,1)):
                sid=day*10+number; starts,ends=(('08:30','09:15') if number==1 else ('09:15','10:00'))
                db.execute("INSERT INTO time_slots(id,calendar_version,day,slot_number,starts,ends) VALUES (?,'test',?,?,?,?)",(sid,day,number,starts,ends))
                db.execute('INSERT INTO block_slots VALUES (1,?)',(sid,)); db.execute('INSERT INTO teacher_availability VALUES (1,?)',(sid,))

    def test_save_review_duplicate_and_historical_snapshot(self):
        overview=self.service.overview(self.session,1)
        self.assertEqual((overview['active'],overview['eligible'],overview['missing_level']),(9,8,1))
        out=self.service.generate_and_save(self.session,1); plan_id=out['plan_id']
        plan=self.service.proposal(self.session,plan_id)
        self.assertEqual(len(plan['groups'][0]['students']),8)
        self.assertEqual(len(plan['pending']),1)
        self.assertEqual(len(self.service.proposals(self.session,1)),1)
        self.assertEqual(self.service.generate_and_save(self.session,1)['result']['status'],'INFEASIBLE')
        with self.store.connect() as db:
            db.execute("UPDATE students SET name='Modificado' WHERE id=1")
            self.assertEqual(db.execute('SELECT count(*) FROM cohort_blocks').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        plan=self.service.proposal(self.session,plan_id)
        self.assertIn('Alumno 1',{s['name'] for s in plan['groups'][0]['students']})

    def test_stale_input_and_denied_session(self):
        with self.assertRaises(AccessDenied): self.service.generate_and_save('wrong',1)
        def solve_then_edit(snapshot, **kwargs):
            result=solve_snapshot(snapshot)
            with self.store.connect() as db: db.execute("UPDATE students SET name='Cambio' WHERE id=1")
            return result
        with patch('ingles.planning_service.solve_relational',side_effect=solve_then_edit):
            with self.assertRaises(StalePlanningData): self.service.generate_and_save(self.session,1)
        self.assertEqual(self.service.proposals(self.session,1),[])

    def test_generation_page_saves_and_displays_result(self):
        env={'INGLES_RELATIONAL_DB_PATH':str(self.store.path),
             'INGLES_DEV_AUTH':'{"admin":{"password":"fake","subject":"admin"}}'}
        with patch.dict(os.environ,env):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app_institucional.py'),default_timeout=30).run()
            app.text_input[0].input('admin'); app.text_input[1].input('fake')
            next(b for b in app.button if b.label=='Iniciar sesión').click().run()
            next(r for r in app.radio if r.label=='Navegación').set_value('Generación de grupos').run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label=='Generar y guardar propuesta').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('guardada' in msg.value for msg in app.success))
            self.assertEqual(len(self.service.proposals(self.session,1)),1)
            next(r for r in app.radio if r.label=='Navegación').set_value('Grupos de inglés').run()
            self.assertFalse(app.exception)
            next(c for c in app.checkbox if c.label.startswith('Confirmo la publicación parcial')).check()
            next(c for c in app.checkbox if c.label.startswith('Confirmo que deseo publicar')).check()
            next(b for b in app.button if b.label=='Publicar propuesta').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('publicada' in msg.value for msg in app.success))
            next(r for r in app.radio if r.label=='Navegación').set_value('Historial y versiones').run()
            self.assertFalse(app.exception)

    def test_manual_edit_via_portal_creates_new_version(self):
        self.add_second_teacher()
        initial=self.service.generate_and_save(self.session,1)['plan_id']
        current=self.service.proposal(self.session,initial)['groups'][0]['teacher_id']
        env={'INGLES_RELATIONAL_DB_PATH':str(self.store.path),
             'INGLES_DEV_AUTH':'{"admin":{"password":"fake","subject":"admin"}}'}
        with patch.dict(os.environ,env):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app_institucional.py'),default_timeout=30).run()
            app.text_input[0].input('admin'); app.text_input[1].input('fake')
            next(b for b in app.button if b.label=='Iniciar sesión').click().run()
            next(r for r in app.radio if r.label=='Navegación').set_value('Grupos de inglés').run()
            self.assertFalse(app.exception)
            next(s for s in app.selectbox if s.label=='Nuevo docente').set_value(2 if current==1 else 1)
            next(t for t in app.text_input if t.label=='Motivo del cambio').input('Cambio validado')
            next(b for b in app.button if b.label=='Validar y crear versión derivada').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('derivada' in msg.value for msg in app.success))
            self.assertEqual(len(self.service.proposals(self.session,1)),2)

    def add_second_teacher(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO teachers(id,provider,external_id,name,employment_type) VALUES (2,'p','t2','Docente 2','PTC')")
            db.execute('INSERT INTO teacher_period_rules(id,teacher_id,period_id,participates,max_hours,max_blocks) VALUES (2,2,1,1,35,5)')
            db.execute('INSERT INTO teacher_availability SELECT 2,slot_id FROM teacher_availability WHERE rule_id=1')

    def test_alternatives_compare_manual_and_publication(self):
        self.add_second_teacher()
        first=self.service.generate_and_save(self.session,1)['plan_id']
        second=self.service.generate_and_save(self.session,1)['plan_id']
        self.assertNotEqual(first,second)
        versions=VersionService(self.store,self.auth)
        self.assertTrue(versions.compare(self.session,first,second))
        with self.assertRaises(ValueError): versions.publish(self.session,first,confirmed=True,expected_official_id=None)
        versions.publish(self.session,first,confirmed=True,confirm_partial=True,reason='Parcial aceptada',expected_official_id=None)
        with self.assertRaises(ValueError): versions.publish(self.session,second,confirmed=False,confirm_partial=True,expected_official_id=first)
        versions.publish(self.session,second,confirmed=True,confirm_partial=True,expected_official_id=first)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM plans WHERE id=?',(first,)).fetchone()[0],'SUSTITUIDA')
            self.assertEqual(db.execute("SELECT count(*) FROM plans WHERE status='PUBLICADA'").fetchone()[0],1)
        self.assertEqual(len(self.service.proposal(self.session,first)['groups'][0]['students']),8)
        self.assertTrue(any(e['action']=='PUBLICACION' for e in versions.history(self.session,1)))

    def test_manual_invalid_change_does_not_write(self):
        self.add_second_teacher()
        first=self.service.generate_and_save(self.session,1)['plan_id']
        plan=self.service.proposal(self.session,first); group=plan['groups'][0]
        versions=VersionService(self.store,self.auth)
        with self.assertRaises(ValueError):
            versions.modify(self.session,first,kind='docente',group=group['code'],value=999,reason='Prueba')
        self.assertEqual(len(self.service.proposals(self.session,1)),1)
        target=1 if group['teacher_id']==2 else 2
        second=versions.modify(self.session,first,kind='docente',group=group['code'],value=target,reason='Disponibilidad')
        self.assertNotEqual(first,second)
        self.assertTrue(versions.compare(self.session,first,second))
        with self.assertRaises(AccessDenied): versions.publish('bad',second,confirmed=True,confirm_partial=True,expected_official_id=None)

    def test_equivalence_ignores_group_names_and_duplicate_block_version_ids(self):
        with self.store.connect() as db:
            db.execute('BEGIN')
            snapshot=load_snapshot(db,1)
        result=solve_snapshot(snapshot)
        from copy import deepcopy
        other=deepcopy(result); other['groups'][0]['id']='OTRO'
        for a in other['assignments']: a['group']='OTRO'
        self.assertEqual(proposal_fingerprint(result,snapshot),proposal_fingerprint(other,snapshot))
        other_snapshot=deepcopy(snapshot); other_snapshot['blocks'][0]['id']=999
        other['groups'][0]['block']=999
        self.assertEqual(proposal_fingerprint(result,snapshot),proposal_fingerprint(other,other_snapshot))

    def test_stale_publication_preserves_previous_official_version(self):
        self.add_second_teacher()
        first=self.service.generate_and_save(self.session,1)['plan_id']
        second=self.service.generate_and_save(self.session,1)['plan_id']
        versions=VersionService(self.store,self.auth)
        versions.publish(self.session,first,confirmed=True,confirm_partial=True,expected_official_id=None)
        with self.store.connect() as db: db.execute('UPDATE teacher_period_rules SET max_hours=21 WHERE teacher_id=1')
        with self.assertRaises(StalePlanningData): versions.publish(self.session,second,confirmed=True,confirm_partial=True,expected_official_id=first)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT id FROM plans WHERE status='PUBLICADA'").fetchone()[0],first)
            self.assertEqual(db.execute('SELECT status FROM plans WHERE id=?',(second,)).fetchone()[0],'PROPUESTA')

    def test_reaudit_rejects_corrupted_proposal_before_publication(self):
        plan=self.service.generate_and_save(self.session,1)['plan_id']
        with self.store.connect() as db:
            db.execute('DELETE FROM student_assignments WHERE plan_id=? AND student_id=1',(plan,))
        with self.assertRaisesRegex(ValueError,'CUPO|COBERTURA'):
            VersionService(self.store,self.auth).publish(self.session,plan,confirmed=True,confirm_partial=True,expected_official_id=None)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM plans WHERE status='PUBLICADA'").fetchone()[0],0)

    def test_publication_rejects_inconsistent_common_block_record(self):
        plan=self.service.generate_and_save(self.session,1)['plan_id']
        with self.store.connect() as db:
            db.execute('DELETE FROM cohort_blocks WHERE plan_id=?',(plan,))
        with self.assertRaisesRegex(ValueError,'bloques comunes'):
            VersionService(self.store,self.auth).publish(self.session,plan,confirmed=True,confirm_partial=True,expected_official_id=None)

    def test_concurrent_publication_is_atomic(self):
        plan_id=self.service.generate_and_save(self.session,1)['plan_id']
        versions=VersionService(self.store,self.auth); barrier=Barrier(2)
        def publish():
            barrier.wait()
            try:
                versions.publish(self.session,plan_id,confirmed=True,confirm_partial=True,expected_official_id=None)
                return 'ok'
            except ValueError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:publish(),range(2)))
        self.assertEqual(sorted(results),['ok','rejected'])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM plans WHERE status='PUBLICADA'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM plan_events WHERE action='PUBLICACION'").fetchone()[0],1)

    def test_two_users_cannot_silently_replace_an_unseen_publication(self):
        self.add_second_teacher()
        first=self.service.generate_and_save(self.session,1)['plan_id']
        second=self.service.generate_and_save(self.session,1)['plan_id']
        versions=VersionService(self.store,self.auth); barrier=Barrier(2)
        def publish(plan):
            barrier.wait()
            try:
                versions.publish(self.session,plan,confirmed=True,confirm_partial=True,expected_official_id=None)
                return 'ok'
            except StalePlanningData:
                return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(publish,[first,second]))
        self.assertEqual(sorted(results),['ok','stale'])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM plans WHERE status='PUBLICADA'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM plan_events WHERE action='PUBLICACION'").fetchone()[0],1)

    def test_teacher_sees_only_official_organization_and_no_admin_versions(self):
        from ingles.portal_services import PortalService
        with self.store.connect() as db:
            db.execute("INSERT INTO users(id,identity_provider,subject,teacher_id) VALUES (2,'desarrollo','docente',1)")
            db.execute("INSERT INTO user_roles(user_id,role) VALUES (2,'DOCENTE')")
        auth=AuthService(self.store,ConfigurableTestAuth({'d':('fake',Identity('desarrollo','docente'))}))
        token=auth.login('d','fake'); portal=PortalService(self.store,auth)
        plan_id=self.service.generate_and_save(self.session,1)['plan_id']
        self.assertEqual(portal.teacher_groups(token,1),[])
        with self.assertRaises(AccessDenied): PlanningService(self.store,auth).proposal(token,plan_id)
        with self.assertRaises(AccessDenied): VersionService(self.store,auth).history(token,1)
        VersionService(self.store,self.auth).publish(self.session,plan_id,confirmed=True,confirm_partial=True,expected_official_id=None)
        self.assertEqual(len(portal.teacher_groups(token,1)),1)
        self.assertEqual(len(portal.teacher_students(token,1)),8)

    def test_alternatives_distinguish_real_student_partitions(self):
        self.add_second_teacher()
        with self.store.connect() as db:
            db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (9,1,2,1,'now')")
            for i in range(10,17):
                db.execute("INSERT INTO students(id,provider,external_id,enrollment,name,school_status) VALUES (?,'p',?,?,?,'activo')",(i,str(i),str(i),'Alumno '+str(i)))
                db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id) VALUES (?,1,1)',(i,))
                db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (?,1,2,1,'now')",(i,))
        ids=[self.service.generate_and_save(self.session,1)['plan_id'] for _ in range(3)]
        self.assertTrue(all(ids))
        versions=VersionService(self.store,self.auth)
        for first in range(3):
            for second in range(first+1,3): self.assertTrue(versions.compare(self.session,ids[first],ids[second]))

    def test_incident_remains_pending_until_version_is_published(self):
        self.add_second_teacher()
        with self.store.connect() as db:
            db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (9,1,2,1,'now')")
            for i in range(10,18):
                db.execute("INSERT INTO students(id,provider,external_id,enrollment,name,school_status) VALUES (?,'p',?,?,?,'activo')",(i,str(i),str(i),'Alumno '+str(i)))
                db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id) VALUES (?,1,1)',(i,))
                db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (?,1,3,1,'now')",(i,))
            db.execute("INSERT INTO incidents(id,period_id,student_id,teacher_id,current_level_id,suggested_level_id,reason,status,created_at) VALUES (1,1,1,1,2,3,'Cambio','APROBADA','now')")
            db.execute("INSERT INTO incident_context(incident_id,academic_group,application_status) VALUES (1,'G','PENDIENTE')")
        first=self.service.generate_and_save(self.session,1)['plan_id']
        versions=VersionService(self.store,self.auth)
        versions.publish(self.session,first,confirmed=True,expected_official_id=None)
        groups=self.service.proposal(self.session,first)['groups']
        destination=next(g['code'] for g in groups if any(s['id']==10 for s in g['students']))
        derived=versions.stage_incident(self.session,first,1,destination,'Cambio autorizado')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT application_status FROM incident_context WHERE incident_id=1').fetchone()[0],'PENDIENTE')
            self.assertEqual(db.execute('SELECT level_id FROM level_decisions WHERE student_id=1 ORDER BY id DESC').fetchone()[0],2)
        versions.publish(self.session,derived,confirmed=True,expected_official_id=first)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT application_status FROM incident_context WHERE incident_id=1').fetchone()[0],'APLICADO')
            self.assertEqual(db.execute('SELECT level_id FROM level_decisions WHERE student_id=1 ORDER BY id DESC').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT count(*) FROM student_assignments WHERE plan_id=?',(first,)).fetchone()[0],17)

    def test_manual_edits_reject_capacity_overlap_and_cohort_conflicts(self):
        self.add_second_teacher()
        with self.store.connect() as db:
            db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (9,1,2,1,'now')")
            for i in range(10,18):
                db.execute("INSERT INTO students(id,provider,external_id,enrollment,name,school_status) VALUES (?,'p',?,?,?,'activo')",(i,str(i),str(i),'Alumno '+str(i)))
                db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id) VALUES (?,1,1)',(i,))
                db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (?,1,3,1,'now')",(i,))
            db.execute('INSERT INTO block_versions(id,block_id,version) VALUES (2,2,1)')
            db.execute('INSERT INTO period_blocks(id,period_id,block_version_id) VALUES (2,1,2)')
            db.execute('INSERT INTO block_slots SELECT 2,slot_id FROM block_slots WHERE block_version_id=1')
        first=self.service.generate_and_save(self.session,1)['plan_id']
        groups=self.service.proposal(self.session,first)['groups']
        small=next(g for g in groups if len(g['students'])==8)
        large=next(g for g in groups if len(g['students'])==9)
        versions=VersionService(self.store,self.auth)
        with self.assertRaisesRegex(ValueError,'CUPO'):
            versions.modify(self.session,first,kind='alumno',group=large['code'],student=small['students'][0]['id'],reason='Prueba')
        with self.assertRaisesRegex(ValueError,'EMPALME'):
            versions.modify(self.session,first,kind='docente',group=small['code'],value=large['teacher_id'],reason='Prueba')
        alternate=1 if small['period_block_id']==2 else 2
        with self.assertRaisesRegex(ValueError,'BLOQUE_COMUN'):
            versions.modify(self.session,first,kind='bloque',group=small['code'],value=alternate,reason='Prueba')
        self.assertEqual(len(self.service.proposals(self.session,1)),1)

    def test_incident_to_exemption_removes_student_only_on_publication(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (9,1,2,1,'now')")
            db.execute("INSERT INTO incidents(id,period_id,student_id,teacher_id,current_level_id,suggested_level_id,reason,status,created_at) VALUES (1,1,1,1,2,9,'Exención','APROBADA','now')")
            db.execute("INSERT INTO incident_context(incident_id,academic_group,application_status) VALUES (1,'G','PENDIENTE')")
        original=self.service.generate_and_save(self.session,1)['plan_id']
        versions=VersionService(self.store,self.auth)
        versions.publish(self.session,original,confirmed=True,expected_official_id=None)
        derived=versions.stage_incident(self.session,original,1,None,'Exención aprobada')
        self.assertEqual(len(self.service.proposal(self.session,derived)['groups'][0]['students']),8)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT level_id FROM level_decisions WHERE student_id=1 ORDER BY id DESC').fetchone()[0],2)
        versions.publish(self.session,derived,confirmed=True,expected_official_id=original)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT level_id FROM level_decisions WHERE student_id=1 ORDER BY id DESC').fetchone()[0],9)
            self.assertEqual(db.execute('SELECT count(*) FROM student_assignments WHERE plan_id=? AND student_id=1',(derived,)).fetchone()[0],0)


if __name__=='__main__': unittest.main()
