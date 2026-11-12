"""Sincronización y autorización independientes de Streamlit."""
from datetime import datetime, timezone
import secrets
import sqlite3
import time
import unicodedata

from ingles.integrations import Batch, Identity, IntegrationError


class AccessDenied(Exception):
    pass


class InvalidBatch(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def required(row, key):
    value = row.get(key)
    if value is None or isinstance(value, (dict, list, bool)) or not str(value).strip():
        raise InvalidBatch(f'Falta el campo obligatorio {key} o tiene formato inválido.')
    return str(value).strip()


def status(value):
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', value.lower()) if not unicodedata.combining(c))
    if normalized in ('activo', 'activa', 'active'):
        return True
    if normalized in ('inactivo', 'inactiva', 'inactive', 'baja'):
        return False
    raise InvalidBatch('Estatus escolar no reconocido.')


class AuthService:
    def __init__(self, store, provider, *, session_seconds=1800, clock=time.monotonic):
        self.store, self.provider = store, provider
        self._sessions = {}
        if session_seconds <= 0:
            raise ValueError('La duración de sesión debe ser positiva.')
        self._session_seconds, self._clock = session_seconds, clock

    def login(self, username, password):
        try:
            identity = self.provider.authenticate(username, password)
        except Exception:
            raise AccessDenied('No fue posible autenticar al usuario.') from None
        if not isinstance(identity, Identity) or not identity.provider or not identity.subject:
            raise AccessDenied('Credenciales o identidad inválidas.')
        with self.store.connect() as db:
            row = db.execute('SELECT id FROM users WHERE identity_provider=? AND subject=? AND active=1',
                             (identity.provider, identity.subject)).fetchone()
            if not row or not db.execute('SELECT 1 FROM user_roles WHERE user_id=?', (row['id'],)).fetchone():
                raise AccessDenied('Usuario inactivo o sin permisos.')
        token = secrets.token_urlsafe(32)
        self._sessions[token] = (row['id'], self._clock() + self._session_seconds)
        try:
            self.authorize(token, {'SECRETARIA', 'DOCENTE'})
        except AccessDenied:
            self._sessions.pop(token, None)
            raise
        return token

    def authorize(self, session, allowed):
        entry = self._sessions.get(session)
        if entry is None:
            raise AccessDenied('Sesión inválida.')
        user_id, expires = entry
        if self._clock() >= expires:
            self._sessions.pop(session, None)
            raise AccessDenied('Sesión expirada.')
        with self.store.connect() as db:
            row = db.execute('SELECT active, teacher_id FROM users WHERE id=?', (user_id,)).fetchone()
            roles = {r[0] for r in db.execute('SELECT role FROM user_roles WHERE user_id=?', (user_id,))}
            if not row or not row['active'] or not roles.intersection(allowed):
                raise AccessDenied('Usuario inactivo o sin permisos.')
            if roles.intersection(allowed) == {'DOCENTE'}:
                teacher = db.execute('SELECT active FROM teachers WHERE id=?', (row['teacher_id'],)).fetchone()
                if not teacher or not teacher['active']:
                    raise AccessDenied('Docente inactivo.')
        return user_id

    def profile(self, session):
        user_id = self.authorize(session, {'SECRETARIA', 'DOCENTE'})
        with self.store.connect() as db:
            row = db.execute('SELECT subject, teacher_id FROM users WHERE id=?', (user_id,)).fetchone()
            roles = {r[0] for r in db.execute('SELECT role FROM user_roles WHERE user_id=?', (user_id,))}
        return {'id': user_id, 'subject': row['subject'], 'teacher_id': row['teacher_id'], 'roles': roles}

    def logout(self, session):
        self._sessions.pop(session, None)


class SyncService:
    def __init__(self, store, auth, provider_name, identity_provider):
        self.store, self.auth = store, auth
        self.provider_name, self.identity_provider = provider_name, identity_provider

    def _run(self, session, provider, kind, apply):
        self.auth.authorize(session, {'SECRETARIA'})
        with self.store.connect() as db:
            if self.provider_name not in ('demo','local_demo') and db.execute('SELECT 1 FROM demo_scenarios LIMIT 1').fetchone():
                raise ValueError('Esta base contiene el escenario ficticio; usa una base institucional separada para sincronizar la API.')
            run_id = db.execute("INSERT INTO sync_runs(source,data_type,started_at,status) VALUES (?,?,?,'EN_PROCESO')",
                                (self.provider_name, kind, now())).lastrowid
        try:
            batch = provider.fetch()
            if not isinstance(batch, Batch) or type(batch.complete) is not bool or not isinstance(batch.records, list):
                raise InvalidBatch('Formato de lote inválido.')
            if not batch.records:
                raise InvalidBatch('Lote vacío: no se aplican bajas ni cambios.')
            self.auth.authorize(session, {'SECRETARIA'})
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                counts = apply(db, batch.records, batch.complete)
                db.execute("UPDATE sync_runs SET finished_at=?, status=?, complete=?, details=? WHERE id=?",
                           (now(), 'EXITOSA' if batch.complete else 'PARCIAL', int(batch.complete), counts, run_id))
            return run_id
        except Exception as exc:
            # Never persist provider error text: it may contain URLs, keys or data.
            safe_errors={'La API rechazó la clave o los permisos (HTTP 401/403).',
                         'La API no encontró el recurso configurado (HTTP 404).',
                         'La API alcanzó su límite de solicitudes (HTTP 429).',
                         'La API devolvió un error HTTP.', 'No fue posible conectar con la API institucional.',
                         'La API devolvió una respuesta JSON inválida.', 'La respuesta institucional no es una lista.',
                         'El tamaño del lote no coincide con el conteo esperado.',
                         'La matrícula debe ser texto o un entero.', 'Faltan carrera o grupo académico.',
                         'Registro institucional inválido.'}
            if isinstance(exc, sqlite3.IntegrityError):
                message='Los datos entrantes entran en conflicto con identificadores existentes o relaciones; no se aplicaron cambios.'
            else:
                message = str(exc) if isinstance(exc, InvalidBatch) or (isinstance(exc,IntegrationError) and str(exc) in safe_errors) else 'Error de conexión o procesamiento institucional.'
            with self.store.connect() as db:
                db.execute("UPDATE sync_runs SET finished_at=?, status='FALLIDA', complete=0, details=? WHERE id=?",
                           (now(), message, run_id))
            raise IntegrationError(message) from None

    def sync_students(self, session, provider, period_id):
        def apply(db, rows, complete):
            period = db.execute('SELECT status FROM periods WHERE id=?', (period_id,)).fetchone()
            if not period or period['status'] == 'CERRADO':
                raise InvalidBatch('El periodo no existe o está cerrado.')
            ids, enrollments = set(), set()
            for row in rows:
                if not isinstance(row, dict):
                    raise InvalidBatch('Registro de alumno inválido.')
                # Canonical contract: the provider adapter maps external fields to these names.
                enrollment = required(row, 'matricula')
                external = required(row, 'id_externo')
                name, career, group = (required(row, x) for x in ('nombre', 'carrera', 'grupo'))
                building, shift, school_status = (required(row, x) for x in ('edificio', 'turno', 'estatus'))
                active = status(school_status)
                if external in ids or enrollment in enrollments:
                    raise InvalidBatch('Identificador o matrícula duplicados en el lote.')
                ids.add(external); enrollments.add(enrollment)
                career_id = required(row, 'carrera_id')
                group_id = required(row, 'grupo_id')
                db.execute('INSERT INTO careers(provider,external_id,name) VALUES (?,?,?) ON CONFLICT(provider,external_id) DO UPDATE SET name=excluded.name', (self.provider_name, career_id, career))
                cid = db.execute('SELECT id FROM careers WHERE provider=? AND external_id=?', (self.provider_name, career_id)).fetchone()[0]
                db.execute('INSERT INTO academic_groups(provider,external_id,career_id,code) VALUES (?,?,?,?) ON CONFLICT(provider,external_id) DO UPDATE SET career_id=excluded.career_id,code=excluded.code', (self.provider_name, group_id, cid, group))
                gid = db.execute('SELECT id FROM academic_groups WHERE provider=? AND external_id=?', (self.provider_name, group_id)).fetchone()[0]
                db.execute('INSERT INTO students(provider,external_id,enrollment,name,building,shift,school_status) VALUES (?,?,?,?,?,?,?) ON CONFLICT(provider,external_id) DO UPDATE SET enrollment=excluded.enrollment,name=excluded.name,building=excluded.building,shift=excluded.shift,school_status=excluded.school_status', (self.provider_name, external, enrollment, name, building, shift, school_status))
                sid = db.execute('SELECT id FROM students WHERE provider=? AND external_id=?', (self.provider_name, external)).fetchone()[0]
                db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id,active) VALUES (?,?,?,?) ON CONFLICT(student_id,period_id) DO UPDATE SET academic_group_id=excluded.academic_group_id,active=excluded.active', (sid, period_id, gid, int(active)))
                eid = db.execute('SELECT id FROM enrollments WHERE student_id=? AND period_id=?', (sid, period_id)).fetchone()[0]
                db.execute('INSERT INTO enrollment_snapshots(enrollment_id,name,enrollment,career_name,group_code,building,shift,school_status) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(enrollment_id) DO UPDATE SET name=excluded.name,enrollment=excluded.enrollment,career_name=excluded.career_name,group_code=excluded.group_code,building=excluded.building,shift=excluded.shift,school_status=excluded.school_status', (eid, name, enrollment, career, group, building, shift, school_status))
            # Absence is not interpreted as withdrawal: status is supplied explicitly.
            return f'recibidos={len(rows)}'
        return self._run(session, provider, 'alumnos', apply)

    def sync_teachers(self, session, provider):
        def apply(db, rows, complete):
            ids = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise InvalidBatch('Registro de docente inválido.')
                external, name, employment = (required(row, x) for x in ('id_externo', 'nombre', 'tipo_contratacion'))
                subject = required(row, 'sujeto_identidad')
                if external in ids or employment not in ('PA', 'PTC', 'OTRO'):
                    raise InvalidBatch('Docente duplicado o tipo de contratación inválido.')
                ids.add(external)
                db.execute('INSERT INTO teachers(provider,external_id,name,employment_type,active) VALUES (?,?,?,?,1) ON CONFLICT(provider,external_id) DO UPDATE SET name=excluded.name,employment_type=excluded.employment_type,active=1', (self.provider_name, external, name, employment))
                tid = db.execute('SELECT id FROM teachers WHERE provider=? AND external_id=?', (self.provider_name, external)).fetchone()[0]
                existing = db.execute('SELECT id,teacher_id FROM users WHERE identity_provider=? AND subject=?', (self.identity_provider, subject)).fetchone()
                if existing and existing['teacher_id'] not in (None, tid):
                    raise InvalidBatch('Identidad institucional asociada a otro docente.')
                db.execute('INSERT INTO users(identity_provider,subject,teacher_id,active) VALUES (?,?,?,1) ON CONFLICT(identity_provider,subject) DO UPDATE SET teacher_id=excluded.teacher_id', (self.identity_provider, subject, tid))
                uid = db.execute('SELECT id FROM users WHERE identity_provider=? AND subject=?', (self.identity_provider, subject)).fetchone()[0]
                db.execute("INSERT OR IGNORE INTO user_roles(user_id,role) VALUES (?,'DOCENTE')", (uid,))
            if complete:
                placeholders = ','.join('?' for _ in ids)
                db.execute(f'UPDATE teachers SET active=0 WHERE provider=? AND external_id NOT IN ({placeholders})', (self.provider_name, *ids))
            return f'recibidos={len(rows)}'
        return self._run(session, provider, 'docentes', apply)
