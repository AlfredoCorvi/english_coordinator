"""Lectura consistente de entradas relacionales para una ejecución de planeación."""
from datetime import datetime


class ConfigurationError(ValueError):
    pass


def valid_block(slots):
    if len(slots) != 7 or len({s['id'] for s in slots}) != 7:
        return False
    for s in slots:
        try:
            a, b = (datetime.strptime(s[k], '%H:%M') for k in ('starts', 'ends'))
        except (ValueError, TypeError):
            return False
        if a.strftime('%H:%M') != s['starts'] or b.strftime('%H:%M') != s['ends']:
            return False
        start, end = a.hour * 60 + a.minute, b.hour * 60 + b.minute
        if s['day'] not in range(1, 6) or end-start != 45 or start < 510 or end > 940 or (start < 715 and end > 690):
            return False
    if any(sum(s['day'] == d for s in slots) > 2 for d in range(1, 6)):
        return False
    return not any(a['day'] == b['day'] and a['starts'] < b['ends'] and b['starts'] < a['ends']
                   for i, a in enumerate(slots) for b in slots[i+1:])


def load_snapshot(db, period_id):
    """El llamador debe mantener una transacción de lectura durante esta función."""
    period = db.execute('SELECT id,code,status FROM periods WHERE id=?', (period_id,)).fetchone()
    if not period:
        raise ConfigurationError('El cuatrimestre no existe.')
    settings = db.execute('SELECT * FROM settings WHERE period_id=? ORDER BY version DESC LIMIT 1', (period_id,)).fetchone()
    config = {'min_size': 8, 'target_size': 28, 'max_size': 35, 'solver_seconds': 30} if settings is None else dict(settings)
    if not (8 <= config['min_size'] <= config['target_size'] <= config['max_size'] <= 35 and config['solver_seconds'] > 0):
        raise ConfigurationError('La configuración debe respetar mínimo 8, máximo 35 y un objetivo intermedio.')
    levels = {r['id']: dict(r) for r in db.execute('SELECT id,name,position,exempt FROM levels')}
    students = [dict(r) for r in db.execute('''SELECT e.student_id AS id,e.academic_group_id AS cohort,
        COALESCE(x.name,s.name) AS name,COALESCE(x.enrollment,s.enrollment) AS enrollment,
        COALESCE(x.career_name,c.name) AS career,COALESCE(x.group_code,ag.code) AS academic_group,
        l.id AS level,l.position AS level_position,l.exempt FROM enrollments e
        JOIN students s ON s.id=e.student_id JOIN academic_groups ag ON ag.id=e.academic_group_id
        JOIN careers c ON c.id=ag.career_id LEFT JOIN enrollment_snapshots x ON x.enrollment_id=e.id
        LEFT JOIN level_decisions d ON d.id=(SELECT id FROM level_decisions WHERE student_id=e.student_id AND target_period_id=e.period_id ORDER BY id DESC LIMIT 1)
        LEFT JOIN levels l ON l.id=d.level_id WHERE e.period_id=? AND e.active=1 ORDER BY e.student_id''', (period_id,))]
    blocks = []
    for row in db.execute('''SELECT pb.id,b.id AS institutional_id,b.name FROM period_blocks pb JOIN block_versions bv ON bv.id=pb.block_version_id
        JOIN blocks b ON b.id=bv.block_id WHERE pb.period_id=? AND pb.active=1 ORDER BY pb.id''', (period_id,)).fetchall():
        block = dict(row)
        block['slots'] = [dict(r) for r in db.execute('''SELECT t.id,t.day,t.starts,t.ends FROM block_slots s
            JOIN time_slots t ON t.id=s.slot_id WHERE s.block_version_id=(SELECT block_version_id FROM period_blocks WHERE id=?)''', (row['id'],))]
        if not valid_block(block['slots']):
            raise ConfigurationError('Hay bloques activos con horarios incompletos o inválidos.')
        blocks.append(block)
    if not blocks:
        raise ConfigurationError('No hay bloques institucionales activos y configurados para el periodo.')
    teachers = []
    for row in db.execute('''SELECT t.id,t.name,t.employment_type,r.max_hours,r.max_blocks,r.id AS rule_id
        FROM teachers t JOIN teacher_period_rules r ON r.teacher_id=t.id
        WHERE t.active=1 AND r.participates=1 AND r.period_id=? ORDER BY t.id''', (period_id,)).fetchall():
        teacher=dict(row)
        teacher['availability']=[r[0] for r in db.execute('SELECT slot_id FROM teacher_availability WHERE rule_id=?',(row['rule_id'],))]
        teachers.append(teacher)
    return {'period_id':period_id,'settings':config,'levels':levels,'students':students,'blocks':blocks,'teachers':teachers}
