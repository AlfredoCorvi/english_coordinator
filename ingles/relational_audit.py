"""Auditor independiente de propuestas generadas con el modelo relacional."""
from collections import Counter, defaultdict
from itertools import combinations

from ingles.relational_planning import valid_block


def audit_snapshot(data, plan):
    issues=[]
    def add(rule, detail): issues.append({'rule':rule,'detail':detail})
    students={s['id']:s for s in data['students']}; teachers={t['id']:t for t in data['teachers']}
    blocks={b['id']:b for b in data['blocks']}; levels=data['levels']; settings=data['settings']
    raw=plan.get('groups',[]); groups={g.get('id'):g for g in raw}
    if len(groups)!=len(raw) or None in groups or '' in groups: add('GRUPOS','Identificadores de grupo duplicados o vacíos.')
    for block in blocks.values():
        if not valid_block(block['slots']): add('HORARIO','Bloque inválido o incompleto.')
    members=defaultdict(list); counts=Counter(); cohorts=defaultdict(set)
    for item in plan.get('assignments',[]):
        sid,gid=item.get('student'),item.get('group'); counts[sid]+=1
        if sid not in students or gid not in groups:
            add('REFERENCIAS','Alumno o grupo inexistente.'); continue
        student=students[sid]; group=groups[gid]; members[gid].append(student)
        if student['level'] is None or student['exempt']: add('ELEGIBILIDAD',f'Alumno {sid} sin nivel o exento.')
        cohorts[student['cohort']].add(group.get('block'))
    if any(count>1 for count in counts.values()): add('DUPLICADOS','Un alumno está asignado más de una vez.')
    if any(len(x)>1 for x in cohorts.values()): add('BLOQUE_COMUN','Un grupo académico ocupa varios bloques.')
    pending=Counter(p.get('student') for p in plan.get('pending',[]))
    for sid,student in students.items():
        if student['exempt']:
            if counts[sid] or pending[sid]: add('EXENTO',f'Alumno {sid} exento aparece en el plan.')
        elif counts[sid]+pending[sid] != 1:
            add('COBERTURA',f'Alumno {sid} debe estar asignado o pendiente una sola vez.')
        elif student['level'] is None and counts[sid]: add('NIVEL',f'Alumno {sid} sin nivel asignado.')
    if any(sid not in students for sid in pending): add('REFERENCIAS','Pendiente inexistente.')
    loads=Counter(); schedules=defaultdict(list)
    for gid,group in groups.items():
        teacher=teachers.get(group.get('teacher')); block=blocks.get(group.get('block'))
        if teacher is None or block is None:
            add('REFERENCIAS',f'{gid}: docente o bloque inválido.'); continue
        size=len(members[gid]); level_set={s['level'] for s in members[gid]}
        if not max(8,settings['min_size'])<=size<=min(35,settings['max_size']): add('CUPO',f'{gid}: cupo fuera de rango.')
        if len(level_set) not in (1,2) or None in level_set or any(l not in levels for l in level_set):
            add('NIVELES',f'{gid}: niveles inválidos.')
        elif len(level_set)==2 and abs(levels[tuple(level_set)[0]]['position']-levels[tuple(level_set)[1]]['position'])!=1:
            add('NIVELES',f'{gid}: niveles no consecutivos.')
        if set(group.get('levels',[]))!=level_set: add('NIVELES',f'{gid}: niveles declarados no coinciden con integrantes.')
        if not {s['id'] for s in block['slots']} <= set(teacher['availability']): add('DISPONIBILIDAD',f'{gid}: docente no disponible.')
        loads[teacher['id']]+=1; schedules[teacher['id']].append((gid,block['slots']))
    for tid,count in loads.items():
        teacher=teachers[tid]; cap=min(teacher['max_blocks'],5 if teacher['employment_type']=='PTC' else 4 if teacher['employment_type']=='PA' else 0)
        hours=min(teacher['max_hours'],35 if teacher['employment_type']=='PTC' else teacher['max_hours'])
        if count>cap or count*7>hours: add('CARGA',f'Docente {tid}: límite de bloques u horas excedido.')
        for (a,first),(b,second) in combinations(schedules[tid],2):
            if any(x['day']==y['day'] and x['starts']<y['ends'] and y['starts']<x['ends'] for x in first for y in second):
                add('EMPALME',f'Docente {tid}: grupos {a} y {b} se superponen.')
    return issues
