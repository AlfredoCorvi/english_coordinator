"""Casos de uso académicos, con permisos y validación en el servidor."""
from datetime import datetime, timezone
import json

from ingles.institutional_services import AccessDenied


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class AcademicService:
    def __init__(self, store, auth):
        self.store, self.auth = store, auth

    def _admin(self, session):
        return self.auth.authorize(session, {'SECRETARIA'})

    def _teacher(self, session):
        uid = self.auth.authorize(session, {'DOCENTE'})
        with self.store.connect() as db:
            return uid, db.execute('SELECT teacher_id FROM users WHERE id=?', (uid,)).fetchone()[0]

    def _allowed(self, db, teacher, student, period):
        return db.execute('''SELECT 1 FROM teacher_student_permissions WHERE teacher_id=? AND student_id=? AND period_id=?
            UNION SELECT 1 FROM english_groups g JOIN plans p ON p.id=g.plan_id
            JOIN student_assignments a ON a.group_id=g.id AND a.plan_id=p.id
            WHERE g.teacher_id=? AND a.student_id=? AND p.period_id=? AND p.status='PUBLICADA' LIMIT 1''',
            (teacher, student, period, teacher, student, period)).fetchone() is not None

    @staticmethod
    def _history(db, period, actor, kind, ident, action, before=None, after=None, reason=''):
        db.execute('INSERT INTO history(period_id,actor_id,entity_type,entity_id,action,previous_value,new_value,reason,occurred_at) VALUES (?,?,?,?,?,?,?,?,?)',
                   (period, actor, kind, ident, action, before, after, reason, timestamp()))

    def levels(self, session):
        self.auth.authorize(session, {'SECRETARIA', 'DOCENTE'})
        with self.store.connect() as db:
            return [dict(x) for x in db.execute('SELECT id,name,position,exempt FROM levels ORDER BY position')]

    def settings(self,session,period):
        self._admin(session)
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM periods WHERE id=?',(period,)).fetchone(): raise ValueError('Periodo inexistente.')
            row=db.execute('SELECT * FROM settings WHERE period_id=? ORDER BY version DESC LIMIT 1',(period,)).fetchone()
            return dict(row) if row else {'version':0,'min_size':8,'target_size':28,'max_size':35,'solver_seconds':30}

    def set_settings(self,session,period,minimum,target,maximum,seconds):
        actor=self._admin(session)
        if any(type(v) is not int for v in (minimum,target,maximum,seconds)) or not (8<=minimum<=target<=maximum<=35 and 1<=seconds<=300):
            raise ValueError('Usa cupos entre 8 y 35, objetivo intermedio y tiempo entre 1 y 300 segundos.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status FROM periods WHERE id=?',(period,)).fetchone()
            if not row or row['status']=='CERRADO': raise ValueError('Periodo inexistente o cerrado.')
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM settings WHERE period_id=?',(period,)).fetchone()[0]
            db.execute('INSERT INTO settings(period_id,version,min_size,target_size,max_size,solver_seconds) VALUES (?,?,?,?,?,?)',(period,version,minimum,target,maximum,seconds))
            self._history(db,period,actor,'configuracion',period,'VERSION',after=json.dumps({'version':version,'minimo':minimum,'objetivo':target,'maximo':maximum,'segundos':seconds}))
            return version

    def create_block(self,session,code,name):
        actor=self._admin(session)
        if not code.strip() or not name.strip() or len(code)>80 or len(name)>120:
            raise ValueError('Indica un identificador y un nombre de bloque válidos.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM blocks WHERE code=?',(code.strip(),)).fetchone(): raise ValueError('Ya existe ese identificador de bloque.')
            ident=db.execute('INSERT INTO blocks(code,name) VALUES (?,?)',(code.strip(),name.strip())).lastrowid
            self._history(db,None,actor,'bloque',ident,'CREAR',after=name.strip())
            return ident

    def students(self, session, period, target=None):
        uid = self.auth.authorize(session, {'SECRETARIA', 'DOCENTE'})
        profile = self.auth.profile(session)
        with self.store.connect() as db:
            rows = db.execute('''SELECT e.student_id AS id,x.enrollment AS matricula,x.name AS nombre,
              x.career_name AS carrera,x.group_code AS grupo,x.shift AS turno,x.school_status AS estatus,
              l.name AS nivel_actual,n.name AS proximo_nivel, l.id AS nivel_actual_id
              FROM enrollments e JOIN enrollment_snapshots x ON x.enrollment_id=e.id
              LEFT JOIN level_decisions d ON d.id=(SELECT id FROM level_decisions WHERE student_id=e.student_id AND target_period_id=e.period_id ORDER BY id DESC LIMIT 1)
              LEFT JOIN levels l ON l.id=d.level_id
              LEFT JOIN level_decisions nd ON nd.id=(SELECT id FROM level_decisions WHERE student_id=e.student_id AND target_period_id=? ORDER BY id DESC LIMIT 1)
              LEFT JOIN levels n ON n.id=nd.level_id WHERE e.period_id=? ORDER BY x.name''', (target, period)).fetchall()
            if 'SECRETARIA' in profile['roles']:
                return [dict(r) for r in rows]
            return [dict(r) for r in rows if self._allowed(db, profile['teacher_id'], r['id'], period)]

    def grant(self, session, teacher, student, period, enable=True):
        actor = self._admin(session)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM enrollments WHERE student_id=? AND period_id=?', (student,period)).fetchone():
                raise ValueError('El alumno no está inscrito en ese periodo.')
            if not db.execute('SELECT 1 FROM teachers WHERE id=? AND active=1', (teacher,)).fetchone():
                raise ValueError('El docente no existe o está inactivo.')
            if enable:
                db.execute('INSERT OR IGNORE INTO teacher_student_permissions VALUES (?,?,?,?,?)', (teacher,student,period,actor,timestamp()))
            else:
                db.execute('DELETE FROM teacher_student_permissions WHERE teacher_id=? AND student_id=? AND period_id=?', (teacher,student,period))
            self._history(db,period,actor,'permiso_docente',student,'OTORGAR' if enable else 'REVOCAR',after=str(teacher))

    def permissions(self, session, period):
        self._admin(session)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('''SELECT p.teacher_id,p.student_id,t.name AS docente,s.name AS alumno
                FROM teacher_student_permissions p JOIN teachers t ON t.id=p.teacher_id JOIN students s ON s.id=p.student_id WHERE p.period_id=?''', (period,))]

    def set_level(self, session, student, current_period, target_period, level, reason='', initial=False):
        actor = self.auth.authorize(session, {'SECRETARIA'} if initial else {'DOCENTE'})
        teacher = None if initial else self._teacher(session)[1]
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = db.execute('SELECT * FROM periods WHERE id=?', (current_period,)).fetchone()
            if not p or p['status'] == 'CERRADO':
                raise ValueError('El periodo actual no existe o está cerrado.')
            if not db.execute('SELECT 1 FROM enrollments WHERE student_id=? AND period_id=?', (student,current_period)).fetchone():
                raise ValueError('El alumno no está inscrito en el periodo actual.')
            if initial:
                if target_period != current_period or db.execute('SELECT 1 FROM level_decisions WHERE student_id=? AND target_period_id=?', (student,current_period)).fetchone():
                    raise ValueError('Solo se puede establecer un nivel inicial pendiente para este periodo.')
            else:
                if not self._allowed(db,teacher,student,current_period):
                    raise AccessDenied('El alumno no está autorizado para este docente.')
                nxt = db.execute('SELECT id,status FROM periods WHERE start_date>? ORDER BY start_date,id LIMIT 1', (p['end_date'],)).fetchone()
                if not nxt or nxt['id'] != target_period or nxt['status'] == 'CERRADO':
                    raise ValueError('Selecciona el siguiente periodo disponible y abierto.')
                if db.execute("SELECT 1 FROM plans WHERE period_id=? AND status='PUBLICADA'",(target_period,)).fetchone():
                    raise ValueError('El periodo destino ya tiene un plan publicado; solicita una gestión administrativa.')
                if not db.execute('SELECT 1 FROM level_decisions WHERE student_id=? AND target_period_id=?', (student,current_period)).fetchone():
                    raise ValueError('El alumno no tiene nivel actual registrado.')
            if not db.execute('SELECT 1 FROM levels WHERE id=?',(level,)).fetchone():
                raise ValueError('Nivel inválido.')
            old = db.execute('SELECT level_id FROM level_decisions WHERE student_id=? AND target_period_id=? ORDER BY id DESC LIMIT 1', (student,target_period)).fetchone()
            db.execute('INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at,reason) VALUES (?,?,?,?,?,?)', (student,target_period,level,actor,timestamp(),reason.strip()))
            self._history(db,target_period,actor,'nivel',student,'ASIGNAR',str(old[0]) if old else None,str(level),reason.strip())

    def level_history(self, session, student, current_period):
        profile = self.auth.profile(session)
        with self.store.connect() as db:
            if 'SECRETARIA' not in profile['roles'] and not self._allowed(db, profile['teacher_id'], student, current_period):
                raise AccessDenied('Alumno no autorizado.')
            return [dict(r) for r in db.execute('''SELECT p.code AS periodo,l.name AS nivel,d.decided_at AS fecha,d.reason AS motivo
                FROM level_decisions d JOIN levels l ON l.id=d.level_id JOIN periods p ON p.id=d.target_period_id
                WHERE d.student_id=? ORDER BY d.id DESC''', (student,))]

    def teachers(self, session, period):
        self._admin(session)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('''SELECT t.id,t.name AS nombre,t.employment_type AS tipo,t.active AS activo,
              r.id AS regla_id,r.participates AS participa,r.max_hours AS max_horas,r.max_blocks AS max_bloques,
              (SELECT COUNT(*) FROM english_groups g JOIN plans p ON p.id=g.plan_id WHERE g.teacher_id=t.id AND p.period_id=? AND p.status='PUBLICADA') AS grupos
              FROM teachers t LEFT JOIN teacher_period_rules r ON r.teacher_id=t.id AND r.period_id=? ORDER BY t.name''', (period,period))]

    def slots(self, session):
        self.auth.authorize(session, {'SECRETARIA', 'DOCENTE'})
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM time_slots ORDER BY day, starts')]

    def add_slot(self, session, day, starts, ends):
        actor = self._admin(session)
        try:
            start, end = (datetime.strptime(v, '%H:%M') for v in (starts, ends))
        except ValueError:
            raise ValueError('Usa horas con formato HH:MM.') from None
        a,b = start.hour*60+start.minute,end.hour*60+end.minute
        if day not in range(1,6) or b-a != 45 or a < 510 or b > 940 or (a < 715 and b > 690):
            raise ValueError('El intervalo debe durar 45 minutos, estar entre 08:30 y 15:40 y respetar el receso 11:30–11:55.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM time_slots WHERE calendar_version='institucional' AND day=? AND starts<? AND ends>?",(day,ends,starts)).fetchone():
                raise ValueError('El intervalo se superpone con otro.')
            num=db.execute("SELECT COALESCE(MAX(slot_number),0)+1 FROM time_slots WHERE calendar_version='institucional' AND day=?",(day,)).fetchone()[0]
            ident=db.execute("INSERT INTO time_slots(calendar_version,day,slot_number,starts,ends) VALUES ('institucional',?,?,?,?)",(day,num,starts,ends)).lastrowid
            self._history(db,None,actor,'intervalo',ident,'CREAR',after=f'{day} {starts}-{ends}')

    def set_teacher_rules(self, session, teacher, period, participates, hours, blocks, slot_ids):
        actor=self._admin(session)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT employment_type FROM teachers WHERE id=? AND active=1',(teacher,)).fetchone()
            p=db.execute('SELECT status FROM periods WHERE id=?',(period,)).fetchone()
            if not row or not p or p[0]=='CERRADO': raise ValueError('Docente o periodo inválido.')
            maximum=5 if row[0]=='PTC' else 4 if row[0]=='PA' else None
            if maximum is None or not 0 <= blocks <= maximum or hours < 0 or (row[0]=='PTC' and hours > 35):
                raise ValueError('Límites inválidos para el tipo de contratación.')
            ids=set(slot_ids)
            if len(ids)!=len(slot_ids) or any(not db.execute('SELECT 1 FROM time_slots WHERE id=?',(i,)).fetchone() for i in ids):
                raise ValueError('Disponibilidad inválida.')
            assigned=db.execute('''SELECT bs.slot_id,ts.day,ts.starts,ts.ends FROM english_groups g JOIN plans p ON p.id=g.plan_id
                JOIN period_blocks pb ON pb.id=g.period_block_id JOIN block_slots bs ON bs.block_version_id=pb.block_version_id
                JOIN time_slots ts ON ts.id=bs.slot_id
                WHERE p.period_id=? AND p.status='PUBLICADA' AND g.teacher_id=?''',(period,teacher)).fetchall()
            group_count=db.execute("SELECT count(*) FROM english_groups g JOIN plans p ON p.id=g.plan_id WHERE p.period_id=? AND p.status='PUBLICADA' AND g.teacher_id=?",(period,teacher)).fetchone()[0]
            overlaps=any(a['day']==b['day'] and a['starts']<b['ends'] and b['starts']<a['ends'] for i,a in enumerate(assigned) for b in assigned[i+1:])
            if group_count and (not participates or group_count>blocks or group_count*7>hours or any(r[0] not in ids for r in assigned) or overlaps):
                raise ValueError('La configuración contradice asignaciones publicadas.')
            db.execute('INSERT INTO teacher_period_rules(teacher_id,period_id,participates,max_hours,max_blocks) VALUES (?,?,?,?,?) ON CONFLICT(teacher_id,period_id) DO UPDATE SET participates=excluded.participates,max_hours=excluded.max_hours,max_blocks=excluded.max_blocks',(teacher,period,int(participates),hours,blocks))
            rid=db.execute('SELECT id FROM teacher_period_rules WHERE teacher_id=? AND period_id=?',(teacher,period)).fetchone()[0]
            db.execute('DELETE FROM teacher_availability WHERE rule_id=?',(rid,))
            db.executemany('INSERT INTO teacher_availability VALUES (?,?)',[(rid,i) for i in ids])
            self._history(db,period,actor,'docente',teacher,'RESTRICCIONES',after=json.dumps({'horas':hours,'bloques':blocks,'disponibilidad':sorted(ids)}))

    def availability(self, session, teacher, period):
        self._admin(session)
        with self.store.connect() as db:
            return [r[0] for r in db.execute('SELECT a.slot_id FROM teacher_availability a JOIN teacher_period_rules r ON r.id=a.rule_id WHERE r.teacher_id=? AND r.period_id=?',(teacher,period))]

    def teacher_load(self,session,teacher,period):
        self._admin(session)
        with self.store.connect() as db:
            rule=db.execute('SELECT * FROM teacher_period_rules WHERE teacher_id=? AND period_id=?',(teacher,period)).fetchone()
            if not rule: return {'groups':[],'remaining':[],'remaining_hours':None,'remaining_blocks':None}
            rows=[dict(r) for r in db.execute('''SELECT g.code,b.name AS block,t.day,t.starts,t.ends FROM english_groups g
                JOIN plans p ON p.id=g.plan_id JOIN period_blocks pb ON pb.id=g.period_block_id
                JOIN block_versions bv ON bv.id=pb.block_version_id JOIN blocks b ON b.id=bv.block_id
                JOIN block_slots bs ON bs.block_version_id=bv.id JOIN time_slots t ON t.id=bs.slot_id
                WHERE p.period_id=? AND p.status='PUBLICADA' AND g.teacher_id=? ORDER BY g.code,t.day,t.starts''',(period,teacher))]
            groups=sorted({(r['code'],r['block']) for r in rows})
            available=[dict(r) for r in db.execute('''SELECT t.day,t.starts,t.ends FROM teacher_availability a
                JOIN time_slots t ON t.id=a.slot_id WHERE a.rule_id=? ORDER BY t.day,t.starts''',(rule['id'],))]
            remaining=[s for s in available if not any(s['day']==r['day'] and s['starts']<r['ends'] and r['starts']<s['ends'] for r in rows)]
            return {'groups':[{'grupo':c,'bloque':b} for c,b in groups], 'remaining':remaining,
                    'remaining_hours':max(0,rule['max_hours']-7*len(groups)),
                    'remaining_blocks':max(0,rule['max_blocks']-len(groups))}

    def blocks(self, session, period):
        self._admin(session)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('''SELECT b.id,b.name, bv.id AS version_id,bv.version,pb.active
                FROM blocks b LEFT JOIN block_versions bv ON bv.id=(SELECT bv2.id FROM block_versions bv2 JOIN period_blocks pb2 ON pb2.block_version_id=bv2.id WHERE bv2.block_id=b.id AND pb2.period_id=? ORDER BY bv2.version DESC LIMIT 1)
                LEFT JOIN period_blocks pb ON pb.block_version_id=bv.id AND pb.period_id=? ORDER BY b.id''',(period,period))]

    def block_slots(self, session, version):
        self._admin(session)
        with self.store.connect() as db:
            return [r[0] for r in db.execute('SELECT slot_id FROM block_slots WHERE block_version_id=?',(version,))]

    def save_block(self, session, period, block, slot_ids, active):
        actor=self._admin(session)
        if len(slot_ids)!=7 or len(set(slot_ids))!=7: raise ValueError('El bloque debe tener exactamente siete intervalos distintos.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p=db.execute('SELECT status FROM periods WHERE id=?',(period,)).fetchone()
            if not p or p[0]=='CERRADO' or not db.execute('SELECT 1 FROM blocks WHERE id=?',(block,)).fetchone(): raise ValueError('Periodo o bloque inválido.')
            slots=[db.execute('SELECT * FROM time_slots WHERE id=?',(i,)).fetchone() for i in slot_ids]
            if any(s is None for s in slots) or any(sum(s['day']==d for s in slots)>2 for d in range(1,6)):
                raise ValueError('Los intervalos deben existir y no superar dos por día.')
            for slot in slots:
                try:
                    start,end=(datetime.strptime(slot[k],'%H:%M') for k in ('starts','ends'))
                except ValueError:
                    raise ValueError('Hay intervalos institucionales inválidos.') from None
                a,b=start.hour*60+start.minute,end.hour*60+end.minute
                if slot['day'] not in range(1,6) or b-a!=45 or a<510 or b>940 or (a<715 and b>690):
                    raise ValueError('Hay intervalos institucionales inválidos.')
            if any(a['day']==b['day'] and a['starts']<b['ends'] and b['starts']<a['ends'] for i,a in enumerate(slots) for b in slots[i+1:]):
                raise ValueError('Los intervalos del bloque se superponen.')
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM block_versions WHERE block_id=?',(block,)).fetchone()[0]
            vid=db.execute('INSERT INTO block_versions(block_id,version) VALUES (?,?)',(block,version)).lastrowid
            db.executemany('INSERT INTO block_slots VALUES (?,?)',[(vid,i) for i in slot_ids])
            db.execute('UPDATE period_blocks SET active=0 WHERE period_id=? AND block_version_id IN (SELECT id FROM block_versions WHERE block_id=?)',(period,block))
            db.execute('INSERT INTO period_blocks(period_id,block_version_id,active) VALUES (?,?,?)',(period,vid,int(active)))
            self._history(db,period,actor,'bloque',block,'VERSION',after=str(version))

    def create_incident(self, session, period, student, requested, reason):
        actor,teacher=self._teacher(session)
        if not reason.strip(): raise ValueError('Indica el motivo.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self._allowed(db,teacher,student,period): raise AccessDenied('Alumno no autorizado.')
            current=db.execute('SELECT level_id FROM level_decisions WHERE student_id=? AND target_period_id=? ORDER BY id DESC LIMIT 1',(student,period)).fetchone()
            enrollment=db.execute('SELECT x.group_code,p.status FROM enrollments e JOIN enrollment_snapshots x ON x.enrollment_id=e.id JOIN periods p ON p.id=e.period_id WHERE e.student_id=? AND e.period_id=?',(student,period)).fetchone()
            if not current or not enrollment or enrollment['status']=='CERRADO' or not db.execute('SELECT 1 FROM levels WHERE id=?',(requested,)).fetchone(): raise ValueError('Faltan nivel, inscripción o periodo válido.')
            group=db.execute("SELECT g.code FROM student_assignments a JOIN plans p ON p.id=a.plan_id JOIN english_groups g ON g.id=a.group_id WHERE a.student_id=? AND p.period_id=? AND p.status='PUBLICADA'",(student,period)).fetchone()
            iid=db.execute("INSERT INTO incidents(period_id,student_id,teacher_id,current_level_id,suggested_level_id,reason,status,created_at) VALUES (?,?,?,?,?,?,'ABIERTA',?)",(period,student,teacher,current[0],requested,reason.strip(),timestamp())).lastrowid
            db.execute('INSERT INTO incident_context(incident_id,academic_group,english_group) VALUES (?,?,?)',(iid,enrollment['group_code'],group[0] if group else None))
            self._history(db,period,actor,'incidencia',iid,'CREAR')

    def incidents(self, session, period):
        profile=self.auth.profile(session)
        with self.store.connect() as db:
            query='''SELECT i.id,s.name AS alumno,t.name AS docente,c.academic_group AS grupo_academico,c.english_group AS grupo_ingles,l.name AS nivel_actual,
              n.name AS solicitado,i.reason AS motivo,i.status AS estado,c.application_status AS aplicacion,i.resolution AS resolucion,i.created_at AS fecha
              FROM incidents i JOIN students s ON s.id=i.student_id JOIN teachers t ON t.id=i.teacher_id
              JOIN levels l ON l.id=i.current_level_id JOIN levels n ON n.id=i.suggested_level_id
              JOIN incident_context c ON c.incident_id=i.id WHERE i.period_id=?'''
            params=[period]
            if 'SECRETARIA' not in profile['roles']:
                query+=' AND i.teacher_id=?';params.append(profile['teacher_id'])
            return [dict(r) for r in db.execute(query+' ORDER BY i.id DESC',params)]

    def resolve_incident(self, session, incident, approve, reason):
        actor=self._admin(session)
        if not reason.strip(): raise ValueError('Indica la resolución.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM incidents WHERE id=?',(incident,)).fetchone()
            if not row or row['status'] not in ('ABIERTA','EN_REVISION'): raise ValueError('La incidencia ya fue resuelta o no existe.')
            state='APROBADA' if approve else 'RECHAZADA'
            application='NO_APLICA'
            if approve:
                current=db.execute('SELECT level_id FROM level_decisions WHERE student_id=? AND target_period_id=? ORDER BY id DESC LIMIT 1',(row['student_id'],row['period_id'])).fetchone()
                if not current or current[0]!=row['current_level_id']:
                    raise ValueError('El nivel del alumno cambió; revisa la incidencia antes de resolverla.')
                published=db.execute("SELECT 1 FROM student_assignments a JOIN plans p ON p.id=a.plan_id WHERE a.student_id=? AND p.period_id=? AND p.status='PUBLICADA'",(row['student_id'],row['period_id'])).fetchone()
                if published:
                    application='PENDIENTE'
                else:
                    db.execute('INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at,reason) VALUES (?,?,?,?,?,?)',(row['student_id'],row['period_id'],row['suggested_level_id'],actor,timestamp(),reason.strip()))
                    self._history(db,row['period_id'],actor,'nivel',row['student_id'],'INCIDENCIA',str(current[0]),str(row['suggested_level_id']),reason.strip())
                    application='APLICADO'
            db.execute('UPDATE incidents SET status=?,resolved_by=?,resolution=?,resolved_at=? WHERE id=?',(state,actor,reason.strip(),timestamp(),incident))
            db.execute('UPDATE incident_context SET application_status=? WHERE incident_id=?',(application,incident))
            self._history(db,row['period_id'],actor,'incidencia',incident,state,reason=reason.strip())
