"""Operaciones del portal; todos los accesos comprueban la sesión."""
from datetime import date
import json

from ingles.institutional_services import AccessDenied


class PortalService:
    def __init__(self, store, auth):
        self.store, self.auth = store, auth

    def periods(self, session):
        self.auth.authorize(session, {'SECRETARIA', 'DOCENTE'})
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT id, code, start_date, end_date, status FROM periods ORDER BY start_date DESC')]

    def create_period(self, session, code, start, end):
        self.auth.authorize(session, {'SECRETARIA'})
        if not code.strip() or not isinstance(start, date) or not isinstance(end, date) or start > end:
            raise ValueError('Indica un código y fechas válidas.')
        with self.store.connect() as db:
            db.execute('INSERT INTO periods(code,start_date,end_date) VALUES (?,?,?)', (code.strip(), start.isoformat(), end.isoformat()))

    def imported(self, session, kind, period_id=None):
        self.auth.authorize(session, {'SECRETARIA'})
        with self.store.connect() as db:
            if kind == 'students':
                query = '''SELECT s.enrollment AS matricula, x.name AS nombre, x.career_name AS carrera,
                           x.group_code AS grupo, x.building AS edificio, x.shift AS turno,
                           x.school_status AS estatus FROM enrollments e
                           JOIN students s ON s.id=e.student_id JOIN enrollment_snapshots x ON x.enrollment_id=e.id
                           WHERE e.period_id=? ORDER BY x.name'''
                rows = db.execute(query, (period_id,))
            elif kind == 'teachers':
                rows = db.execute('SELECT external_id AS identificador, name AS nombre, employment_type AS tipo, active AS activo FROM teachers ORDER BY name')
            elif kind == 'runs':
                rows = db.execute('SELECT data_type AS tipo, started_at AS inicio, status AS estado, complete AS completo, details AS detalle FROM sync_runs ORDER BY id DESC LIMIT 100')
            else:
                raise ValueError('Consulta desconocida.')
            return [dict(r) for r in rows]

    def teacher_groups(self, session, period_id):
        user_id = self.auth.authorize(session, {'DOCENTE'})
        with self.store.connect() as db:
            rows = db.execute('''SELECT g.id, g.code, b.name AS bloque, g.period_block_id, p.input_snapshot FROM users u
                JOIN english_groups g ON g.teacher_id=u.teacher_id
                JOIN plans p ON p.id=g.plan_id AND p.period_id=g.period_id
                JOIN period_blocks pb ON pb.id=g.period_block_id
                JOIN block_versions bv ON bv.id=pb.block_version_id JOIN blocks b ON b.id=bv.block_id
                WHERE u.id=? AND p.period_id=? AND p.status='PUBLICADA' ORDER BY g.code''', (user_id, period_id))
            result=[]
            for r in rows:
                item=dict(r); snapshot=json.loads(item.pop('input_snapshot') or '{}')
                block=next((b for b in snapshot.get('blocks',[]) if b['id']==item['period_block_id']),None)
                if block: item['bloque']=block['name']
                item.pop('period_block_id'); result.append(item)
            return result

    def teacher_students(self, session, period_id):
        user_id = self.auth.authorize(session, {'DOCENTE'})
        with self.store.connect() as db:
            rows = db.execute('''SELECT DISTINCT s.id AS student_id, COALESCE(x.enrollment,s.enrollment) AS matricula,
                COALESCE(x.name,s.name) AS nombre,
                g.code AS grupo, p.input_snapshot
                FROM users u JOIN english_groups g ON g.teacher_id=u.teacher_id
                JOIN plans p ON p.id=g.plan_id AND p.period_id=g.period_id
                JOIN student_assignments a ON a.group_id=g.id AND a.plan_id=p.id
                JOIN students s ON s.id=a.student_id
                JOIN enrollments e ON e.student_id=s.id AND e.period_id=p.period_id
                LEFT JOIN enrollment_snapshots x ON x.enrollment_id=e.id
                WHERE u.id=? AND p.period_id=? AND p.status='PUBLICADA' ORDER BY nombre''', (user_id, period_id))
            result=[]
            for r in rows:
                item=dict(r); snapshot=json.loads(item.pop('input_snapshot') or '{}')
                student=next((s for s in snapshot.get('students',[]) if s['id']==item['student_id']),None)
                if student:
                    item['nombre']=student.get('name',item['nombre']); item['matricula']=student.get('enrollment',item['matricula'])
                item.pop('student_id'); result.append(item)
            return result
