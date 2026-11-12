from copy import deepcopy
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingles.bootstrap import bootstrap
from ingles.integrations import ConfigurableTestAuth, Identity
from ingles.institutional_services import AuthService, AccessDenied
from ingles.planning_service import PlanningService
from ingles.relational_audit import audit_snapshot
from ingles.relational_planning import ConfigurationError, load_snapshot
from ingles.relational_scheduler import solve_snapshot
from ingles.relational_storage import RelationalStore


def sample(counts, *, teacher_count=2, block_count=1):
    times=[('08:30','09:15'),('09:15','10:00'),('10:00','10:45'),('10:45','11:30'),
           ('11:55','12:40'),('12:40','13:25'),('13:25','14:10'),('14:10','14:55')]
    blocks=[]
    for b in range(block_count):
        slots=[]
        for d in range(1,6):
            for hour in ([2*b,2*b+1] if d<=2 else [2*b]):
                a,z=times[hour]; slots.append({'id':d*100+hour,'day':d,'starts':a,'ends':z})
        blocks.append({'id':b+1,'name':f'B{b+1}','slots':slots})
    available=[s['id'] for block in blocks for s in block['slots']]
    levels={i:{'id':i,'name':str(i),'position':i,'exempt':int(i>8)} for i in range(1,11)}
    students=[]
    for cohort,level,count in counts:
        for _ in range(count): students.append({'id':len(students)+1,'cohort':cohort,'level':level,'level_position':level,'exempt':int(level>8) if level else None})
    teachers=[{'id':i+1,'name':'T','employment_type':'PA','max_hours':28,'max_blocks':4,'availability':available} for i in range(teacher_count)]
    return {'period_id':1,'settings':{'min_size':8,'max_size':35,'target_size':28,'solver_seconds':20},
            'students':students,'teachers':teachers,'levels':levels,'blocks':blocks}


class SchedulerTests(unittest.TestCase):
    def solved(self, data):
        result=solve_snapshot(data)
        self.assertIn(result['status'],('OPTIMAL','FEASIBLE'))
        self.assertFalse(audit_snapshot(data,result))
        return result

    def test_balanced_examples(self):
        for n,expected in ((50,25),(60,30),(68,34)):
            with self.subTest(n=n):
                result=self.solved(sample([(1,2,n)]))
                sizes=[sum(a['group']==g['id'] for a in result['assignments']) for g in result['groups']]
                self.assertEqual(sorted(sizes),[expected,expected]); self.assertFalse(result['pending'])

    def test_single_level_before_multilevel_and_coverage(self):
        data=sample([(1,5,15),(2,6,10)])
        result=self.solved(data)
        self.assertEqual(len(result['groups']),2)
        self.assertTrue(all(len(g['levels'])==1 for g in result['groups']))
        data['teachers']=data['teachers'][:1]
        result=self.solved(data)
        self.assertEqual(len(result['assignments']),25)
        self.assertEqual(len(result['groups'][0]['levels']),2)

    def test_common_block_exemption_and_pending(self):
        data=sample([(1,2,9),(1,3,9),(2,9,3),(3,None,2)],block_count=2)
        result=self.solved(data)
        self.assertEqual(len(result['groups']),2)
        self.assertEqual(len({g['block'] for g in result['groups']}),1)
        self.assertEqual(len(result['exempt']),3)
        self.assertEqual(len([x for x in result['pending'] if x['reason']=='SIN_NIVEL']),2)
        altered=deepcopy(result); altered['assignments'].append(dict(altered['assignments'][0]))
        self.assertIn('DUPLICADOS',{x['rule'] for x in audit_snapshot(data,altered)})

    def test_partial_and_overlap(self):
        data=sample([(1,2,40)],teacher_count=1)
        result=self.solved(data)
        self.assertEqual(len(result['assignments']),35)
        self.assertEqual(len(result['pending']),5)
        self.assertIn('parcial',result['message'])
        tampered=deepcopy(result)
        tampered['groups'].append(dict(tampered['groups'][0],id='OTRO'))
        tampered['assignments'][-8:]=[dict(a,group='OTRO') for a in tampered['assignments'][-8:]]
        self.assertIn('EMPALME',{x['rule'] for x in audit_snapshot(data,tampered)})

    def test_teacher_pa_26_hours(self):
        data=sample([(1,2,28),(2,2,28),(3,2,28),(4,2,28)],teacher_count=1,block_count=4)
        data['teachers'][0]['max_hours']=26
        data['settings']['solver_seconds']=15
        result=self.solved(data)
        self.assertLessEqual(len(result['groups']),3)
        self.assertGreater(len(result['pending']),0)

    def test_no_resources_and_bad_block(self):
        data=sample([(1,2,9)],teacher_count=0)
        result=solve_snapshot(data)
        self.assertEqual(result['status'],'NO_ASSIGNMENTS')
        self.assertEqual(len(result['pending']),9)
        self.assertFalse(audit_snapshot(data,result))
        data['blocks'][0]['slots'].pop()
        self.assertIn('HORARIO',{x['rule'] for x in audit_snapshot(data,result)})

    def test_companions_remain_together_when_possible(self):
        data=sample([(1,2,12),(2,2,20),(3,2,18)])
        result=self.solved(data)
        for cohort in (1,2,3):
            ids={s['id'] for s in data['students'] if s['cohort']==cohort}
            self.assertEqual(len({a['group'] for a in result['assignments'] if a['student'] in ids}),1)

    def test_auditor_detects_level_mismatch_and_unavailable_teacher(self):
        data=sample([(1,2,8),(2,4,8)])
        result=self.solved(data)
        bad=deepcopy(result)
        bad['assignments'][-1]['group']=bad['assignments'][0]['group']
        rules={x['rule'] for x in audit_snapshot(data,bad)}
        self.assertIn('NIVELES',rules)
        unavailable=deepcopy(data); unavailable['teachers'][0]['availability']=[]
        self.assertIn('DISPONIBILIDAD',{x['rule'] for x in audit_snapshot(unavailable,result)})

    def test_time_limit_without_solution_is_not_reported_infeasible(self):
        data=sample([(1,2,9)])
        data['settings']['solver_seconds']=1
        with patch('ingles.relational_scheduler.time.monotonic',side_effect=[0,2,2]):
            result=solve_snapshot(data)
        self.assertEqual(result['status'],'TIMEOUT')
        self.assertFalse(result['groups'])


class DatabaseServiceTests(unittest.TestCase):
    def test_reads_database_and_does_not_write_or_bypass_permissions(self):
        with tempfile.TemporaryDirectory() as path:
            store=RelationalStore(Path(path)/'test.sqlite3'); bootstrap(store,'admin')
            auth=AuthService(store,ConfigurableTestAuth({'a':('x',Identity('desarrollo','admin'))}))
            token=auth.login('a','x')
            with store.connect() as db:
                db.execute("INSERT INTO periods(id,code,start_date,end_date) VALUES (1,'P','2026-01-01','2026-04-30')")
            service=PlanningService(store,auth)
            with self.assertRaises(AccessDenied): service.generate('invalid',1)
            with self.assertRaises(ConfigurationError): service.generate(token,1)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM plans').fetchone()[0],0)

    def test_generation_uses_latest_relational_levels_and_leaves_database_unchanged(self):
        with tempfile.TemporaryDirectory() as path:
            store=RelationalStore(Path(path)/'test.sqlite3'); bootstrap(store,'admin')
            auth=AuthService(store,ConfigurableTestAuth({'a':('x',Identity('desarrollo','admin'))}))
            token=auth.login('a','x')
            block=sample([(1,2,1)])['blocks'][0]
            with store.connect() as db:
                db.execute("INSERT INTO periods(id,code,start_date,end_date) VALUES (1,'P','2026-01-01','2026-04-30')")
                db.execute("INSERT INTO careers(id,provider,external_id,name) VALUES (1,'p','c','Carrera')")
                db.execute("INSERT INTO academic_groups(id,career_id,provider,external_id,code) VALUES (1,1,'p','g','G')")
                for i in range(1,13):
                    db.execute("INSERT INTO students(id,provider,external_id,enrollment,name,school_status) VALUES (?,'p',?,?,?,'activo')",(i,str(i),str(i),'A'))
                    db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id,active) VALUES (?,1,1,?)',(i,int(i!=12)))
                    if i<=10:
                        db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at) VALUES (?,1,?,1,'now')",(i,9 if i==10 else 2))
                db.execute("INSERT INTO teachers(id,provider,external_id,name,employment_type) VALUES (1,'p','t','T','PA')")
                db.execute('INSERT INTO teacher_period_rules(id,teacher_id,period_id,participates,max_hours,max_blocks) VALUES (1,1,1,1,26,4)')
                db.execute('INSERT INTO block_versions(id,block_id,version) VALUES (1,1,1)')
                db.execute('INSERT INTO period_blocks(id,period_id,block_version_id) VALUES (1,1,1)')
                for index,s in enumerate(block['slots']):
                    db.execute("INSERT INTO time_slots(id,calendar_version,day,slot_number,starts,ends) VALUES (?,'test',?,?,?,?)",(s['id'],s['day'],index+1,s['starts'],s['ends']))
                    db.execute('INSERT INTO block_slots VALUES (1,?)',(s['id'],))
                    db.execute('INSERT INTO teacher_availability VALUES (1,?)',(s['id'],))
            result=PlanningService(store,auth).generate(token,1)
            self.assertEqual(len(result['assignments']),9)
            self.assertEqual(result['exempt'],[10])
            self.assertEqual(result['pending'],[{'student':11,'reason':'SIN_NIVEL'}])
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM plans').fetchone()[0],0)


if __name__=='__main__': unittest.main()
