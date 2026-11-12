from collections import Counter, defaultdict
from itertools import combinations

from ingles.domain import group_level, slots, teacher_buildings, transfer_conflict, validate_bundle


def audit(bundle, plan):
    """Independent verifier; also checks manually edited plans, without a solver."""
    issues = []

    def add(code, message, severity="Error"):
        issues.append({"Severidad": severity, "Regla": code, "Detalle": message})

    input_errors = validate_bundle(bundle)
    for error in input_errors:
        add("Datos de entrada", error)
    if input_errors:
        return issues
    s = bundle["settings"]
    students = {a["Matricula"]: a for a in bundle["students"]}
    teachers = {t["ID"]: t for t in bundle["teachers"]}
    rooms = {r["ID"]: r for r in bundle["rooms"]}
    blocks = {b["Bloque"]: b for b in bundle["blocks"]}
    raw_groups = plan.get("groups", [])
    groups = {g.get("id"): g for g in raw_groups}
    if len(groups) != len(raw_groups) or "" in groups or None in groups:
        add("Grupos", "Hay identificadores de grupo vacíos o repetidos.")
    assigned = Counter()
    members = defaultdict(list)
    cohorts = defaultdict(set)
    for a in plan.get("assignments", []):
        student, gid = a.get("student"), a.get("group")
        assigned[student] += 1
        if student not in students:
            add("Alumnos", f"La matrícula {student} no existe en el padrón.")
            continue
        if gid not in groups:
            add("Asignación", f"{student}: el grupo {gid} no existe.")
            continue
        members[gid].append(student)
        group, record = groups[gid], students[student]
        if group.get("level") != group_level(record["Nivel"], s["grouping"]):
            add("Nivel", f"{student}: su nivel no corresponde al grupo {gid}.")
        if record.get("Bloque fijo") and record["Bloque fijo"] != group.get("block"):
            add("Bloque fijo", f"{student}: no se respetó su bloque fijo.")
        cohorts[record["Carrera"], record["Grupo"]].add(group.get("block"))
        room = rooms.get(group.get("room"))
        if s["strict_building"] and room and record["Edificio"] != room["Edificio"]:
            add("Edificio", f"{student}: fue asignado fuera de su edificio.")
    for student in students:
        if assigned[student] != 1:
            add("Cobertura", f"{student}: tiene {assigned[student]} asignaciones; debe tener exactamente una.")
    for (career, cohort), values in cohorts.items():
        if len(values) > 1:
            add("Grupo de carrera", f"{career} / {cohort}: ocupa más de un bloque. Todos sus alumnos deben tener inglés en los mismos días y horas.")
    teacher_hours = Counter()
    valid = []
    for gid, group in groups.items():
        if not all(group.get(k) in source for k, source in (("teacher", teachers), ("room", rooms), ("block", blocks))):
            add("Referencias", f"{gid}: docente, salón o bloque inexistente.")
            continue
        teacher, room, block = teachers[group["teacher"]], rooms[group["room"]], blocks[group["block"]]
        times = slots(block, s["periods_per_day"])
        valid.append((gid, group, room, times))
        teacher_hours[group["teacher"]] += len(times)
        size, capacity = len(members[gid]), min(int(room["Capacidad"]), s["max_group"])
        if not s["min_group"] <= size <= capacity:
            add("Cupo", f"{gid}: {size} alumnos; rango permitido {s['min_group']} a {capacity}.")
        elif size < 25:
            add("Grupo pequeño", f"{gid}: {size} alumnos. El mínimo configurado es {s['min_group']}.", "Aviso")
        if not times <= slots(teacher, s["periods_per_day"]):
            add("Disponibilidad docente", f"{gid}: está fuera del horario de {teacher['Nombre']}.")
        if not times <= slots(room, s["periods_per_day"]):
            add("Disponibilidad salón", f"{gid}: está fuera del horario disponible del salón.")
        if room["Edificio"] not in teacher_buildings(teacher["Edificios"]):
            add("Edificio docente", f"{gid}: edificio no autorizado para {teacher['Nombre']}.")
    for teacher, hours in teacher_hours.items():
        if hours > int(teachers[teacher]["Horas máximas"]):
            add("Carga docente", f"{teachers[teacher]['Nombre']}: {hours} horas exceden su máximo de {teachers[teacher]['Horas máximas']}.")
    for (aid, a, ar, at), (bid, b, br, bt) in combinations(valid, 2):
        overlap = at & bt
        if overlap and a["room"] == b["room"]:
            add("Choque de salón", f"{aid} y {bid} usan el mismo salón a la misma hora.")
        if a["teacher"] == b["teacher"]:
            if overlap:
                add("Choque docente", f"{aid} y {bid} tienen el mismo docente a la misma hora.")
            elif ar["Edificio"] != br["Edificio"] and transfer_conflict(at, bt, s["transfer_periods"]):
                add("Traslado docente", f"{aid} y {bid}: no dejan {s['transfer_periods']} periodos libres entre edificios.")
    return issues


def errors_only(issues):
    return [i for i in issues if i["Severidad"] == "Error"]
