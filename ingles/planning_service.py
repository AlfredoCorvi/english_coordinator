"""Generación y persistencia transaccional de propuestas académicas."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json

from ingles.relational_planning import load_snapshot, valid_block
from ingles.scheduler import solve_relational
from ingles.relational_audit import audit_snapshot


class StalePlanningData(ValueError):
    pass


class DuplicateProposal(ValueError):
    pass


def _canonical(value):
    def normalize(item):
        if isinstance(item,dict): return {str(k):normalize(v) for k,v in item.items()}
        if isinstance(item,list): return [normalize(v) for v in item]
        return item
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def block_identity(snapshot, block_id):
    block=next((b for b in snapshot['blocks'] if b['id']==block_id),None)
    if block is None: return {'unavailable_block_id':block_id}
    return {'institutional_id':block.get('institutional_id',block_id),
            'slots':sorted((s['day'],s['starts'],s['ends']) for s in block['slots'])}


def proposal_fingerprint(result, snapshot):
    """Las etiquetas ING no identifican una organización académica."""
    members=defaultdict(list)
    for assignment in result['assignments']:
        members[assignment['group']].append(assignment['student'])
    groups=sorted([{'block':block_identity(snapshot,g['block']), 'teacher':g['teacher'],
                    'students':sorted(members[g['id']])} for g in result['groups']], key=_canonical)
    return hashlib.sha256(_canonical(groups).encode('utf-8')).hexdigest()


class PlanningService:
    def __init__(self, store, auth):
        self.store, self.auth = store, auth

    def generate(self, session, period_id):
        self.auth.authorize(session, {'SECRETARIA'})
        with self.store.connect() as db:
            db.execute('BEGIN')
            snapshot=load_snapshot(db,period_id)
        result=solve_relational(snapshot)
        self.auth.authorize(session, {'SECRETARIA'})
        if result['status'] in ('OPTIMAL','FEASIBLE','NO_ASSIGNMENTS'):
            issues=audit_snapshot(snapshot,result)
            if issues:
                raise ValueError('La propuesta no pasó la auditoría independiente: '+', '.join(i['rule'] for i in issues))
        return result

    def overview(self, session, period_id):
        self.auth.authorize(session, {'SECRETARIA'})
        with self.store.connect() as db:
            period=db.execute('SELECT id,code,status FROM periods WHERE id=?',(period_id,)).fetchone()
            if not period:
                raise ValueError('El cuatrimestre no existe.')
            students=[dict(r) for r in db.execute('''SELECT e.student_id,COALESCE(x.name,s.name) AS name,
                COALESCE(x.enrollment,s.enrollment) AS enrollment,l.exempt,l.id AS level
                FROM enrollments e JOIN students s ON s.id=e.student_id
                LEFT JOIN enrollment_snapshots x ON x.enrollment_id=e.id
                LEFT JOIN level_decisions d ON d.id=(SELECT id FROM level_decisions
                WHERE student_id=e.student_id AND target_period_id=e.period_id ORDER BY id DESC LIMIT 1)
                LEFT JOIN levels l ON l.id=d.level_id WHERE e.period_id=? AND e.active=1''',(period_id,))]
            teachers=[dict(r) for r in db.execute('''SELECT t.id,t.name,t.employment_type,r.id AS rule_id,r.max_hours,r.max_blocks,
                (SELECT count(*) FROM teacher_availability a WHERE a.rule_id=r.id) AS intervals
                FROM teachers t JOIN teacher_period_rules r ON r.teacher_id=t.id
                WHERE t.active=1 AND r.participates=1 AND r.period_id=? ORDER BY t.name''',(period_id,))]
            blocks=[dict(r) for r in db.execute('''SELECT pb.id,b.name,count(bs.slot_id) AS intervals
                FROM period_blocks pb JOIN block_versions bv ON bv.id=pb.block_version_id
                JOIN blocks b ON b.id=bv.block_id LEFT JOIN block_slots bs ON bs.block_version_id=bv.id
                WHERE pb.period_id=? AND pb.active=1 GROUP BY pb.id,b.name ORDER BY pb.id''',(period_id,))]
            block_slots={}
            for block in blocks:
                slots=[dict(r) for r in db.execute('''SELECT t.id,t.day,t.starts,t.ends FROM period_blocks pb
                    JOIN block_slots bs ON bs.block_version_id=pb.block_version_id JOIN time_slots t ON t.id=bs.slot_id WHERE pb.id=?''',(block['id'],))]
                block['valid']=valid_block(slots)
                block_slots[block['id']]={s['id'] for s in slots}
            for teacher in teachers:
                availability={r[0] for r in db.execute('SELECT slot_id FROM teacher_availability WHERE rule_id=?',(teacher['rule_id'],))}
                capable=teacher['employment_type'] in ('PA','PTC') and teacher['max_hours']>=7 and teacher['max_blocks']>=1
                teacher['compatible_blocks']=sum(capable and b['valid'] and block_slots[b['id']]<=availability for b in blocks)
            total=db.execute('SELECT count(*) FROM enrollments WHERE period_id=?',(period_id,)).fetchone()[0]
            return {'period':dict(period),'active':len(students),
                    'total':total,
                    'eligible':sum(s['level'] is not None and not s['exempt'] for s in students),
                    'missing_level':sum(s['level'] is None for s in students),
                    'exempt':sum(s['level'] is not None and s['exempt'] for s in students),
                    'missing_students':[s for s in students if s['level'] is None],
                    'exempt_students':[s for s in students if s['level'] is not None and s['exempt']],
                    'teachers':teachers,'blocks':blocks}

    def generate_and_save(self, session, period_id):
        actor=self.auth.authorize(session, {'SECRETARIA'})
        with self.store.connect() as db:
            db.execute('BEGIN')
            period=db.execute('SELECT status FROM periods WHERE id=?',(period_id,)).fetchone()
            if not period or period['status']=='CERRADO':
                raise ValueError('El cuatrimestre no existe o está cerrado.')
            snapshot=load_snapshot(db,period_id)
            prior=[]
            minimum_coverage=0
            for plan in db.execute('SELECT id,input_snapshot FROM plans WHERE period_id=? ORDER BY id',(period_id,)).fetchall():
                groups=[]
                old_snapshot=json.loads(plan['input_snapshot']) if plan['input_snapshot'] else None
                for g in db.execute('SELECT id,period_block_id,teacher_id FROM english_groups WHERE plan_id=?',(plan['id'],)).fetchall():
                    prior_block=g['period_block_id']
                    if old_snapshot:
                        old_key=block_identity(old_snapshot,prior_block)
                        prior_block=next((b['id'] for b in snapshot['blocks'] if block_identity(snapshot,b['id'])==old_key),prior_block)
                    groups.append({'block':prior_block,'teacher':g['teacher_id'],
                                   'students':[r[0] for r in db.execute('SELECT student_id FROM student_assignments WHERE plan_id=? AND group_id=?',(plan['id'],g['id']))]})
                prior.append(groups)
                if plan['input_snapshot'] and _canonical(json.loads(plan['input_snapshot']))==_canonical(snapshot):
                    minimum_coverage=max(minimum_coverage,sum(len(g['students']) for g in groups))
        result=solve_relational(snapshot,excluded=prior,minimum_coverage=minimum_coverage)
        self.auth.authorize(session, {'SECRETARIA'})
        if result['status'] not in ('OPTIMAL','FEASIBLE','NO_ASSIGNMENTS'):
            return {'plan_id':None,'result':result}
        issues=audit_snapshot(snapshot,result)
        if issues:
            raise ValueError('La propuesta no pasó la auditoría independiente: '+', '.join(i['rule'] for i in issues))
        fingerprint=proposal_fingerprint(result,snapshot)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.auth.authorize(session, {'SECRETARIA'})
            if db.execute('SELECT status FROM periods WHERE id=?',(period_id,)).fetchone()['status']=='CERRADO':
                raise StalePlanningData('El cuatrimestre se cerró durante la generación.')
            if _canonical(load_snapshot(db,period_id))!=_canonical(snapshot):
                raise StalePlanningData('Los datos cambiaron durante la generación; vuelve a generar la propuesta.')
            if db.execute('SELECT 1 FROM plans WHERE period_id=? AND fingerprint=?',(period_id,fingerprint)).fetchone():
                raise DuplicateProposal('La organización generada coincide con una propuesta anterior; no se guardó otra copia.')
            metrics={'status':result['status'],'message':result['message'],'proven_stages':result['proven_stages'],
                     'seconds':result['seconds'],'exempt':result['exempt'], 'warnings':[], 'conflicts':[],
                     'assigned':len(result['assignments']), 'pending_by_reason':dict(Counter(p['reason'] for p in result['pending']))}
            if result['pending']:
                metrics['warnings'].append('Hay alumnos pendientes; la propuesta es parcial.')
            settings_id=snapshot['settings'].get('id')
            plan_id=db.execute('''INSERT INTO plans(period_id,settings_id,origin,status,fingerprint,created_by,created_at,
                solver_version,solver_status,input_snapshot,metrics) VALUES (?,?,'ALGORITMO','PROPUESTA',?,?,?,?,?,?,?)''',
                (period_id,settings_id,fingerprint,actor,datetime.now(timezone.utc).isoformat(),'relational-cpsat-1',result['status'],
                 _canonical(snapshot),_canonical(metrics))).lastrowid
            ids={}
            for group in result['groups']:
                gid=db.execute('''INSERT INTO english_groups(plan_id,period_id,code,period_block_id,teacher_id)
                    VALUES (?,?,?,?,?)''',(plan_id,period_id,group['id'],group['block'],group['teacher'])).lastrowid
                ids[group['id']]=gid
                db.executemany('INSERT INTO english_group_levels(group_id,level_id) VALUES (?,?)',[(gid,level) for level in group['levels']])
            cohort_blocks={}
            students={s['id']:s for s in snapshot['students']}
            groups={g['id']:g for g in result['groups']}
            for assignment in result['assignments']:
                sid=assignment['student']; g=groups[assignment['group']]
                db.execute('INSERT INTO student_assignments(plan_id,group_id,student_id) VALUES (?,?,?)',(plan_id,ids[g['id']],sid))
                cohort_blocks[students[sid]['cohort']]=g['block']
            db.executemany('INSERT INTO cohort_blocks(plan_id,period_id,academic_group_id,period_block_id) VALUES (?,?,?,?)',
                           [(plan_id,period_id,cohort,block) for cohort,block in cohort_blocks.items()])
            reasons={'SIN_NIVEL':'Falta confirmar el nivel de inglés para este periodo.',
                     'SIN_ASIGNACION':'Sin grupo compatible en la propuesta; revise cupos, bloque común y disponibilidad docente. No se identificó una causa única.'}
            db.executemany('INSERT INTO plan_pending(plan_id,student_id,category,detail) VALUES (?,?,?,?)',
                           [(plan_id,p['student'],p['reason'],reasons.get(p['reason'],'Asignación pendiente.')) for p in result['pending']])
            db.execute('INSERT INTO plan_report_meta(plan_id,captured_at) VALUES (?,?)',(plan_id,datetime.now(timezone.utc).isoformat()))
            db.execute('''INSERT INTO plan_inactive_students(plan_id,student_id,enrollment,name,career,academic_group,level,school_status)
                SELECT ?,s.id,COALESCE(x.enrollment,s.enrollment),COALESCE(x.name,s.name),
                COALESCE(x.career_name,c.name),COALESCE(x.group_code,ag.code),l.name,COALESCE(x.school_status,s.school_status)
                FROM enrollments e JOIN students s ON s.id=e.student_id JOIN academic_groups ag ON ag.id=e.academic_group_id
                JOIN careers c ON c.id=ag.career_id LEFT JOIN enrollment_snapshots x ON x.enrollment_id=e.id
                LEFT JOIN level_decisions d ON d.id=(SELECT id FROM level_decisions WHERE student_id=e.student_id AND target_period_id=e.period_id ORDER BY id DESC LIMIT 1)
                LEFT JOIN levels l ON l.id=d.level_id WHERE e.period_id=? AND e.active=0''',(plan_id,period_id))
            db.execute('INSERT INTO plan_events(plan_id,actor_id,action,reason,detail,created_at) VALUES (?,?,?,?,?,?)',
                       (plan_id,actor,'GENERACION','',_canonical({'status':result['status']}),datetime.now(timezone.utc).isoformat()))
        return {'plan_id':plan_id,'result':result}

    def proposals(self, session, period_id):
        self.auth.authorize(session, {'SECRETARIA'})
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('''SELECT id,created_at,status,solver_status,created_by,metrics
                FROM plans WHERE period_id=? ORDER BY id DESC''',(period_id,))]

    def proposal(self, session, plan_id):
        self.auth.authorize(session, {'SECRETARIA'})
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM plans WHERE id=?',(plan_id,)).fetchone()
            if not row:
                raise ValueError('La propuesta no existe.')
            snapshot=json.loads(row['input_snapshot'] or '{}')
            saved_students={s['id']:s for s in snapshot.get('students',[])}
            for change in db.execute('SELECT student_id,new_level_id FROM plan_incidents WHERE plan_id=?',(plan_id,)):
                if change['student_id'] in saved_students:
                    saved_students[change['student_id']]['level']=change['new_level_id']
            saved_teachers={t['id']:t for t in snapshot.get('teachers',[])}
            saved_blocks={b['id']:b for b in snapshot.get('blocks',[])}
            groups=[dict(r) for r in db.execute('''SELECT g.id,g.code,g.teacher_id,t.name AS teacher,
                g.period_block_id,b.name AS block FROM english_groups g
                LEFT JOIN teachers t ON t.id=g.teacher_id JOIN period_blocks pb ON pb.id=g.period_block_id
                JOIN block_versions bv ON bv.id=pb.block_version_id JOIN blocks b ON b.id=bv.block_id
                WHERE g.plan_id=? ORDER BY g.code''',(plan_id,))]
            for group in groups:
                group['teacher']=saved_teachers.get(group['teacher_id'],{}).get('name',group['teacher'])
                group['block']=saved_blocks.get(group['period_block_id'],{}).get('name',group['block'])
                group['levels']=[snapshot.get('levels',{}).get(str(r['level_id']),{}).get('name',r['name']) for r in db.execute('''SELECT gl.level_id,l.name FROM english_group_levels gl
                    JOIN levels l ON l.id=gl.level_id WHERE gl.group_id=? ORDER BY l.position''',(group['id'],))]
                group['students']=[dict(r) for r in db.execute('''SELECT s.id,s.enrollment,s.name FROM student_assignments a
                    JOIN students s ON s.id=a.student_id WHERE a.plan_id=? AND a.group_id=? ORDER BY s.name''',(plan_id,group['id']))]
                for student in group['students']:
                    saved=saved_students.get(student['id'],{})
                    student['name']=saved.get('name',student['name'])
                    student['enrollment']=saved.get('enrollment',student['enrollment'])
                    student['career']=saved.get('career','')
                    student['academic_group']=saved.get('academic_group','')
                    student['level']=snapshot.get('levels',{}).get(str(saved.get('level')) ,{}).get('name','Sin nivel')
            pending=[dict(r) for r in db.execute('''SELECT p.student_id,s.enrollment,s.name,p.category,p.detail
                FROM plan_pending p JOIN students s ON s.id=p.student_id WHERE p.plan_id=? ORDER BY s.name''',(plan_id,))]
            for student in pending:
                saved=saved_students.get(student['student_id'],{})
                student['name']=saved.get('name',student['name'])
                student['enrollment']=saved.get('enrollment',student['enrollment'])
            return {'id':row['id'],'period_id':row['period_id'],'status':row['status'],'created_at':row['created_at'],
                    'metrics':json.loads(row['metrics'] or '{}'),'groups':groups,'pending':pending,
                    'teachers':snapshot.get('teachers',[]),'blocks':snapshot.get('blocks',[]),
                    'levels':snapshot.get('levels',{})}
