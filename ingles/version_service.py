"""Revisión, versiones derivadas y publicación atómica de propuestas."""
from copy import deepcopy
from datetime import datetime, timezone
import json

from ingles.planning_service import DuplicateProposal, StalePlanningData, _canonical, proposal_fingerprint, block_identity
from ingles.relational_audit import audit_snapshot
from ingles.relational_planning import load_snapshot


def _now():
    return datetime.now(timezone.utc).isoformat()


def _snapshot(raw):
    data=json.loads(raw)
    data['levels']={int(k):v for k,v in data['levels'].items()}
    return data


def _read(db, plan_id):
    row=db.execute('SELECT * FROM plans WHERE id=?',(plan_id,)).fetchone()
    if not row or not row['input_snapshot']:
        raise ValueError('No existe una propuesta con instantánea verificable.')
    base=_snapshot(row['input_snapshot'])
    groups=[]
    for g in db.execute('SELECT * FROM english_groups WHERE plan_id=? ORDER BY id',(plan_id,)).fetchall():
        groups.append({'id':g['code'],'block':g['period_block_id'],'teacher':g['teacher_id'],
                       'levels':[r[0] for r in db.execute('SELECT level_id FROM english_group_levels WHERE group_id=? ORDER BY level_id',(g['id'],))]})
    assignments=[{'student':r['student_id'],'group':r['code']} for r in db.execute('''SELECT a.student_id,g.code
        FROM student_assignments a JOIN english_groups g ON g.id=a.group_id WHERE a.plan_id=?''',(plan_id,))]
    pending=[{'student':r['student_id'],'reason':r['category'],'detail':r['detail']} for r in db.execute('SELECT * FROM plan_pending WHERE plan_id=?',(plan_id,))]
    changes=[dict(r) for r in db.execute('SELECT * FROM plan_incidents WHERE plan_id=?',(plan_id,))]
    return row,base,{'groups':groups,'assignments':assignments,'pending':pending},changes


def _effective(base, changes):
    snapshot=deepcopy(base)
    students={s['id']:s for s in snapshot['students']}
    for change in changes:
        student=students.get(change['student_id']); level=snapshot['levels'].get(change['new_level_id'])
        if not student or not level:
            raise ValueError('La incidencia ya no coincide con la instantánea del plan.')
        student.update(level=level['id'],level_position=level['position'],exempt=level['exempt'])
    return snapshot


def _refresh_levels(snapshot, plan):
    students={s['id']:s for s in snapshot['students']}
    for group in plan['groups']:
        group['levels']=sorted({students[a['student']]['level'] for a in plan['assignments'] if a['group']==group['id']})


def _verify(snapshot,plan):
    issues=audit_snapshot(snapshot,plan)
    if issues:
        raise ValueError('Asignación inválida: '+'; '.join(f"{i['rule']}: {i['detail']}" for i in issues))


class VersionService:
    def __init__(self,store,auth):
        self.store,self.auth=store,auth

    def _event(self,db,plan_id,actor,action,reason,detail):
        db.execute('INSERT INTO plan_events(plan_id,actor_id,action,reason,detail,created_at) VALUES (?,?,?,?,?,?)',
                   (plan_id,actor,action,reason,_canonical(detail),_now()))

    def _write(self,db,period,actor,parent,base,plan,changes,reason,action,detail):
        effective=_effective(base,changes); _refresh_levels(effective,plan); _verify(effective,plan)
        fingerprint=proposal_fingerprint(plan,effective)
        if db.execute('SELECT 1 FROM plans WHERE period_id=? AND fingerprint=?',(period,fingerprint)).fetchone():
            raise DuplicateProposal('Ya existe una versión con las mismas asignaciones reales.')
        metrics={'status':'MANUAL','message':'Versión derivada y auditada.',
                 'warnings':['Hay alumnos pendientes.'] if plan['pending'] else [],'conflicts':[],
                 'assigned':len(plan['assignments'])}
        plan_id=db.execute('''INSERT INTO plans(period_id,settings_id,parent_id,origin,status,fingerprint,created_by,created_at,
            solver_version,solver_status,input_snapshot,metrics) VALUES (?,?,?,'MANUAL','PROPUESTA',?,?,?,'manual','MANUAL',?,?)''',
            (period,base['settings'].get('id'),parent,fingerprint,actor,_now(),_canonical(base),_canonical(metrics))).lastrowid
        gids={}
        for g in plan['groups']:
            gid=db.execute('INSERT INTO english_groups(plan_id,period_id,code,period_block_id,teacher_id) VALUES (?,?,?,?,?)',
                           (plan_id,period,g['id'],g['block'],g['teacher'])).lastrowid
            gids[g['id']]=gid
            db.executemany('INSERT INTO english_group_levels(group_id,level_id) VALUES (?,?)',[(gid,l) for l in g['levels']])
        students={s['id']:s for s in effective['students']}; groups={g['id']:g for g in plan['groups']}; cohorts={}
        for a in plan['assignments']:
            db.execute('INSERT INTO student_assignments(plan_id,group_id,student_id) VALUES (?,?,?)',(plan_id,gids[a['group']],a['student']))
            cohorts[students[a['student']]['cohort']]=groups[a['group']]['block']
        db.executemany('INSERT INTO cohort_blocks(plan_id,period_id,academic_group_id,period_block_id) VALUES (?,?,?,?)',
                       [(plan_id,period,c,b) for c,b in cohorts.items()])
        db.executemany('INSERT INTO plan_pending(plan_id,student_id,category,detail) VALUES (?,?,?,?)',
                       [(plan_id,p['student'],p['reason'],p.get('detail')) for p in plan['pending']])
        db.executemany('INSERT INTO plan_incidents(plan_id,incident_id,student_id,old_level_id,new_level_id) VALUES (?,?,?,?,?)',
                       [(plan_id,c['incident_id'],c['student_id'],c['old_level_id'],c['new_level_id']) for c in changes])
        if db.execute('SELECT 1 FROM plan_report_meta WHERE plan_id=?',(parent,)).fetchone():
            db.execute('INSERT INTO plan_report_meta(plan_id,captured_at) VALUES (?,?)',(plan_id,_now()))
            db.execute('''INSERT INTO plan_inactive_students(plan_id,student_id,enrollment,name,career,academic_group,level,school_status)
                SELECT ?,student_id,enrollment,name,career,academic_group,level,school_status FROM plan_inactive_students WHERE plan_id=?''',(plan_id,parent))
        self._event(db,plan_id,actor,action,reason,detail)
        return plan_id

    def _source(self,db,plan_id):
        row,base,plan,changes=_read(db,plan_id)
        if db.execute('SELECT status FROM periods WHERE id=?',(row['period_id'],)).fetchone()[0]=='CERRADO':
            raise ValueError('El cuatrimestre está cerrado; solo puede consultarse su historial.')
        current=load_snapshot(db,row['period_id'])
        expected=_effective(base,changes) if row['status'] in ('PUBLICADA','SUSTITUIDA') else base
        if _canonical(current)!=_canonical(expected):
            raise StalePlanningData('Los datos del periodo cambiaron; genera una propuesta actualizada.')
        effective=_effective(base,changes)
        _verify(effective,plan)
        if proposal_fingerprint(plan,effective)!=row['fingerprint']:
            raise ValueError('La integridad de las asignaciones de la versión no coincide con su huella.')
        students={s['id']:s for s in effective['students']}; groups={g['id']:g for g in plan['groups']}
        actual={a['academic_group_id']:a['period_block_id'] for a in db.execute('SELECT academic_group_id,period_block_id FROM cohort_blocks WHERE plan_id=?',(plan_id,))}
        expected_blocks={students[a['student']]['cohort']:groups[a['group']]['block'] for a in plan['assignments']}
        if actual!=expected_blocks:
            raise ValueError('La integridad de bloques comunes de la versión no coincide con las asignaciones.')
        if row['status'] in ('PUBLICADA','SUSTITUIDA'):
            return row,current,plan,[]
        return row,base,plan,changes

    def modify(self,session,plan_id,*,kind,group=None,value=None,student=None,reason):
        actor=self.auth.authorize(session,{'SECRETARIA'})
        if not reason.strip(): raise ValueError('Indica el motivo del cambio.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.auth.authorize(session,{'SECRETARIA'})
            row,base,plan,changes=self._source(db,plan_id)
            groups={g['id']:g for g in plan['groups']}
            if group not in groups: raise ValueError('El grupo no existe en la versión seleccionada.')
            if kind in ('docente','bloque'):
                field='teacher' if kind=='docente' else 'block'; before=groups[group][field]
                groups[group][field]=value
            elif kind=='alumno':
                assignment=next((a for a in plan['assignments'] if a['student']==student),None)
                if not assignment: raise ValueError('El alumno no está asignado en esta versión.')
                before=assignment['group']; assignment['group']=group
            else: raise ValueError('Tipo de cambio desconocido.')
            if before==(group if kind=='alumno' else value): raise ValueError('El cambio no modifica la asignación.')
            return self._write(db,row['period_id'],actor,plan_id,base,plan,changes,reason.strip(),kind.upper(),
                               {'group':group,'student':student,'before':before,'after':group if kind=='alumno' else value})

    def stage_incident(self,session,plan_id,incident_id,destination,reason):
        actor=self.auth.authorize(session,{'SECRETARIA'})
        if not reason.strip(): raise ValueError('Indica el motivo del cambio.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.auth.authorize(session,{'SECRETARIA'})
            row,base,plan,changes=self._source(db,plan_id)
            incident=db.execute('''SELECT i.*,c.application_status FROM incidents i JOIN incident_context c ON c.incident_id=i.id
                WHERE i.id=?''',(incident_id,)).fetchone()
            if not incident or incident['period_id']!=row['period_id'] or incident['status']!='APROBADA' or incident['application_status']!='PENDIENTE':
                raise ValueError('La incidencia no está aprobada y pendiente en este periodo.')
            if any(c['student_id']==incident['student_id'] for c in changes):
                raise ValueError('Ya hay un cambio de nivel preparado para este alumno.')
            assignment=next((a for a in plan['assignments'] if a['student']==incident['student_id']),None)
            if not assignment: raise ValueError('El alumno no tiene grupo de origen en esta versión.')
            student=next((s for s in base['students'] if s['id']==incident['student_id']),None)
            if not student or student['level']!=incident['current_level_id']:
                raise StalePlanningData('El nivel actual no coincide con la incidencia aprobada.')
            requested=base['levels'][incident['suggested_level_id']]
            before=assignment['group']
            if requested['exempt']:
                if destination is not None: raise ValueError('Un alumno exento no puede tener grupo de destino.')
                plan['assignments'].remove(assignment)
            else:
                if destination not in {g['id'] for g in plan['groups']}: raise ValueError('El grupo de destino no existe.')
                assignment['group']=destination
                if before==destination: raise ValueError('Selecciona un grupo diferente al de origen.')
            changes.append({'incident_id':incident_id,'student_id':incident['student_id'],
                            'old_level_id':incident['current_level_id'],'new_level_id':incident['suggested_level_id']})
            return self._write(db,row['period_id'],actor,plan_id,base,plan,changes,reason.strip(),'INCIDENCIA',
                               {'incident':incident_id,'student':incident['student_id'],'before':before,'after':destination})

    def publish(self,session,plan_id,*,confirmed=False,confirm_partial=False,reason='',expected_official_id):
        actor=self.auth.authorize(session,{'SECRETARIA'})
        if confirmed is not True: raise ValueError('Confirma explícitamente la publicación.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.auth.authorize(session,{'SECRETARIA'})
            row,base,plan,changes=self._source(db,plan_id)
            if row['status']!='PROPUESTA': raise ValueError('Solo puede publicarse una propuesta vigente.')
            if plan['pending'] and confirm_partial is not True:
                raise ValueError('La propuesta tiene alumnos pendientes; confirma explícitamente la publicación parcial.')
            effective=_effective(base,changes); _verify(effective,plan)
            for c in changes:
                incident=db.execute('''SELECT i.status,c.application_status FROM incidents i JOIN incident_context c ON c.incident_id=i.id WHERE i.id=?''',(c['incident_id'],)).fetchone()
                if not incident or incident['status']!='APROBADA' or incident['application_status']!='PENDIENTE':
                    raise ValueError('Una incidencia preparada ya no está pendiente de aplicación.')
                current=db.execute('SELECT level_id FROM level_decisions WHERE student_id=? AND target_period_id=? ORDER BY id DESC LIMIT 1',(c['student_id'],row['period_id'])).fetchone()
                if not current or current[0]!=c['old_level_id']: raise StalePlanningData('El nivel del alumno cambió desde la propuesta.')
            previous=db.execute("SELECT id FROM plans WHERE period_id=? AND status='PUBLICADA'",(row['period_id'],)).fetchone()
            actual=previous['id'] if previous else None
            if actual!=expected_official_id:
                raise StalePlanningData('La publicación oficial cambió desde la revisión; actualiza el estado y revisa antes de publicar.')
            if previous:
                db.execute("UPDATE plans SET status='SUSTITUIDA' WHERE id=?",(previous['id'],))
            for c in changes:
                db.execute('INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at,reason) VALUES (?,?,?,?,?,?)',
                           (c['student_id'],row['period_id'],c['new_level_id'],actor,_now(),reason.strip() or 'Publicación de incidencia'))
                db.execute("UPDATE incident_context SET application_status='APLICADO' WHERE incident_id=?",(c['incident_id'],))
                db.execute('UPDATE incidents SET resulting_plan_id=? WHERE id=?',(plan_id,c['incident_id']))
                db.execute('''INSERT INTO history(period_id,actor_id,entity_type,entity_id,action,previous_value,new_value,reason,occurred_at)
                    VALUES (?,?,?,?,?,?,?,?,?)''',(row['period_id'],actor,'nivel',c['student_id'],'PUBLICAR_INCIDENCIA',str(c['old_level_id']),str(c['new_level_id']),reason.strip(),_now()))
            db.execute("UPDATE plans SET status='PUBLICADA' WHERE id=?",(plan_id,))
            self._event(db,plan_id,actor,'PUBLICACION',reason.strip(),{'previous_plan_id':previous['id'] if previous else None,'partial':bool(plan['pending'])})
            return plan_id

    def current_official(self,session,period):
        self.auth.authorize(session,{'SECRETARIA'})
        with self.store.connect() as db:
            row=db.execute("SELECT id FROM plans WHERE period_id=? AND status='PUBLICADA'",(period,)).fetchone()
            return row['id'] if row else None

    def compare(self,session,first_id,second_id):
        self.auth.authorize(session,{'SECRETARIA'})
        with self.store.connect() as db:
            a,base_a,first,changes_a=_read(db,first_id); b,base_b,second,changes_b=_read(db,second_id)
            if a['period_id']!=b['period_id']: raise ValueError('Las versiones deben pertenecer al mismo periodo.')
            def mapping(plan,snapshot):
                groups={g['id']:g for g in plan['groups']}; members={g['id']:[] for g in plan['groups']}
                students={s['id']:s for s in snapshot['students']}
                for item in plan['assignments']: members[item['group']].append(item['student'])
                return {item['student']:{'teacher':groups[item['group']]['teacher'],
                    'block':block_identity(snapshot,groups[item['group']]['block']),
                    'level':students[item['student']]['level'],'members':sorted(members[item['group']])} for item in plan['assignments']}
            x,y=mapping(first,_effective(base_a,changes_a)),mapping(second,_effective(base_b,changes_b))
            return [{'student_id':sid,'before':x.get(sid),'after':y.get(sid)} for sid in sorted(set(x)|set(y)) if x.get(sid)!=y.get(sid)]

    def history(self,session,period):
        self.auth.authorize(session,{'SECRETARIA'})
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('''SELECT p.id AS version,p.status,p.origin,p.created_at,u.subject AS creator,
                e.action,e.reason,e.detail,e.created_at AS event_time,actor.subject AS actor
                FROM plans p JOIN users u ON u.id=p.created_by LEFT JOIN plan_events e ON e.plan_id=p.id
                LEFT JOIN users actor ON actor.id=e.actor_id WHERE p.period_id=? ORDER BY p.id DESC,e.id''',(period,))]

    def academic_history(self,session,period):
        self.auth.authorize(session,{'SECRETARIA'})
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('''SELECT h.entity_type,h.entity_id,h.action,h.previous_value,h.new_value,
                h.reason,h.occurred_at,u.subject AS actor FROM history h LEFT JOIN users u ON u.id=h.actor_id
                WHERE h.period_id=? ORDER BY h.id DESC''',(period,))]

    def dashboard(self,session,period):
        self.auth.authorize(session,{'SECRETARIA'})
        with self.store.connect() as db:
            latest=db.execute('SELECT id FROM plans WHERE period_id=? ORDER BY id DESC LIMIT 1',(period,)).fetchone()
            official=db.execute("SELECT id FROM plans WHERE period_id=? AND status='PUBLICADA'",(period,)).fetchone()
            count=lambda sql,params: db.execute(sql,params).fetchone()[0]
            generated=count('SELECT count(*) FROM english_groups WHERE plan_id=?',(latest['id'],)) if latest else 0
            published=count('SELECT count(*) FROM english_groups WHERE plan_id=?',(official['id'],)) if official else 0
            without_teacher=count('SELECT count(*) FROM english_groups WHERE plan_id=? AND teacher_id IS NULL',(official['id'],)) if official else 0
            teachers=count('SELECT count(DISTINCT teacher_id) FROM english_groups WHERE plan_id=?',(official['id'],)) if official else 0
            assigned=count('''SELECT count(*) FROM student_assignments a JOIN enrollments e
                ON e.student_id=a.student_id AND e.period_id=? AND e.active=1 WHERE a.plan_id=?''',
                (period,official['id'])) if official else 0
            incidents=count("SELECT count(*) FROM incidents i LEFT JOIN incident_context c ON c.incident_id=i.id WHERE i.period_id=? AND (i.status IN ('ABIERTA','EN_REVISION') OR (i.status='APROBADA' AND c.application_status='PENDIENTE'))",(period,))
            conflicts=[]
            if official:
                row,base,plan,changes=_read(db,official['id'])
                try:
                    current=load_snapshot(db,period)
                    conflicts=audit_snapshot(current,plan)
                except ValueError as exc:
                    conflicts=[{'rule':'CONFIGURACION','detail':str(exc)}]
            return {'latest_id':latest['id'] if latest else None,'official_id':official['id'] if official else None,
                    'generated_groups':generated,'published_groups':published,'assigned_teachers':teachers,
                    'groups_without_teacher':without_teacher,
                    'assigned_students':assigned,'pending_incidents':incidents,'conflicts':conflicts}
