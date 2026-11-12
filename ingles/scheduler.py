from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from ingles.domain import group_level, slots, teacher_buildings, transfer_conflict, validate_bundle


@dataclass
class SolveResult:
    status: str
    message: str
    groups: list
    assignments: list
    seconds: float = 0

    @property
    def success(self):
        return self.status in ("OPTIMAL", "FEASIBLE")

    def payload(self):
        return {"status": self.status, "message": self.message, "groups": self.groups,
                "assignments": self.assignments, "seconds": self.seconds}


def solve(bundle):
    errors = validate_bundle(bundle)
    if errors:
        return SolveResult("INVALID", "\n".join(errors), [], [])
    s = bundle["settings"]
    students, teachers, rooms, blocks = (bundle[k] for k in ("students", "teachers", "rooms", "blocks"))
    total = len(students)
    if sum(int(t["Horas máximas"]) // 7 for t in teachers) * s["max_group"] < total:
        return SolveResult("INFEASIBLE", "La carga docente total no alcanza para atender a todos los alumnos en grupos de siete horas.", [], [])
    model = cp_model.CpModel()
    bslots = [slots(b, s["periods_per_day"]) for b in blocks]
    rslots = [slots(r, s["periods_per_day"]) for r in rooms]
    tslots = [slots(t, s["periods_per_day"]) for t in teachers]
    levels = sorted({group_level(a["Nivel"], s["grouping"]) for a in students})
    # Aggregate interchangeable students; do not pre-split groups. The solver chooses
    # sizes and blocks jointly, avoiding false failures from an arbitrary partition.
    demand = defaultdict(list)
    for a in sorted(students, key=lambda a: a["Matricula"]):
        key = (a["Carrera"], a["Grupo"], group_level(a["Nivel"], s["grouping"]), a["Edificio"], a["Bloque fijo"])
        demand[key].append(a["Matricula"])
    cell_open, level_open, teacher_choice = {}, {}, {}
    for bi, b in enumerate(blocks):
        for ri, room in enumerate(rooms):
            if not bslots[bi] <= rslots[ri]:
                continue
            eligible = [ti for ti, t in enumerate(teachers) if bslots[bi] <= tslots[ti]
                        and room["Edificio"] in teacher_buildings(t["Edificios"])
                        and int(t["Horas máximas"]) >= 7]
            if not eligible:
                continue
            cell_open[bi, ri] = model.new_bool_var(f"open_{bi}_{ri}")
            for level in levels:
                level_open[bi, ri, level] = model.new_bool_var(f"level_{bi}_{ri}_{level}")
            model.add(sum(level_open[bi, ri, level] for level in levels) == cell_open[bi, ri])
            for ti in eligible:
                teacher_choice[bi, ri, ti] = model.new_bool_var(f"teacher_{bi}_{ri}_{ti}")
            model.add(sum(teacher_choice[bi, ri, ti] for ti in eligible) == cell_open[bi, ri])
    if not cell_open:
        return SolveResult("INFEASIBLE", "Ningún bloque tiene simultáneamente salón y docente disponibles en el mismo edificio. Revisa las plantillas de bloques y disponibilidades.", [], [])
    allocation = {}
    by_cell_level = defaultdict(list)
    mismatch = []
    cohort_block = {}
    # A shared weekly block per Carrera + Grupo is mandatory, including when an
    # older saved configuration still contains cohort_block=False.
    for cohort in sorted({key[:2] for key in demand}):
        for bi in range(len(blocks)):
            cohort_block[cohort, bi] = model.new_bool_var(f"cohort_{cohort}_{bi}")
        model.add(sum(cohort_block[cohort, bi] for bi in range(len(blocks))) == 1)
    for di, (key, members) in enumerate(demand.items()):
        career, cohort, level, building, fixed = key
        options = []
        for bi, ri in cell_open:
            if fixed and blocks[bi]["Bloque"] != fixed:
                continue
            if s["strict_building"] and rooms[ri]["Edificio"] != building:
                continue
            var = model.new_int_var(0, len(members), f"students_{di}_{bi}_{ri}")
            allocation[di, bi, ri] = var
            model.add(var <= len(members) * level_open[bi, ri, level])
            model.add(var <= len(members) * cohort_block[(career, cohort), bi])
            options.append(var)
            by_cell_level[bi, ri, level].append(var)
            if rooms[ri]["Edificio"] != building:
                mismatch.append(var)
        if not options:
            return SolveResult("INFEASIBLE", f"No hay opciones para {career} / {cohort}, nivel {level}, edificio {building}, bloque fijo {fixed or 'libre'}.", [], [])
        model.add(sum(options) == len(members))
    for (bi, ri, level), opened in level_open.items():
        count = sum(by_cell_level[bi, ri, level])
        capacity = min(int(rooms[ri]["Capacidad"]), s["max_group"])
        model.add(count <= capacity * opened)
        model.add(count >= s["min_group"] * opened)
    # Room and teacher occupancy is checked per actual day/period, not block name.
    for slot in set().union(*bslots):
        for ri in range(len(rooms)):
            model.add(sum(v for (bi, r), v in cell_open.items() if r == ri and slot in bslots[bi]) <= 1)
        for ti in range(len(teachers)):
            model.add(sum(v for (bi, ri, t), v in teacher_choice.items() if t == ti and slot in bslots[bi]) <= 1)
    for ti, teacher in enumerate(teachers):
        choices = [(bi, ri, v) for (bi, ri, t), v in teacher_choice.items() if t == ti]
        model.add(sum(v for _, _, v in choices) * 7 <= int(teacher["Horas máximas"]))
        for i, (bi, ri, first) in enumerate(choices):
            for bj, rj, second in choices[i + 1:]:
                if rooms[ri]["Edificio"] != rooms[rj]["Edificio"] and transfer_conflict(bslots[bi], bslots[bj], s["transfer_periods"]):
                    model.add(first + second <= 1)
    # Lexicographic objective: first fewer groups, then fewer student relocations.
    model.minimize((total + 1) * sum(cell_open.values()) + sum(mismatch))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = s["solver_seconds"]
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    status = solver.solve(model)
    name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        message = ("No existe una asignación completa con estos bloques y restricciones. Revisa cupos, niveles, edificios, carga docente y horarios; puedes modificar o proponer otros bloques."
                   if status == cp_model.INFEASIBLE else
                   "La búsqueda terminó sin encontrar una solución dentro del tiempo disponible. Esto no demuestra que sea imposible; aumenta el tiempo o ajusta los bloques.")
        return SolveResult(name, message, [], [], solver.wall_time)
    groups, assignments, group_ids = [], [], {}
    for (bi, ri, level), var in level_open.items():
        if solver.value(var):
            gid = f"ING-{len(groups) + 1:03}"
            ti = next(t for (b, r, t), choice in teacher_choice.items() if b == bi and r == ri and solver.value(choice))
            group_ids[bi, ri] = gid
            groups.append({"id": gid, "level": level, "block": blocks[bi]["Bloque"], "teacher": teachers[ti]["ID"], "room": rooms[ri]["ID"]})
    for di, (_, members) in enumerate(demand.items()):
        cursor = 0
        for (d, bi, ri), var in allocation.items():
            if di != d:
                continue
            count = solver.value(var)
            assignments.extend({"student": student, "group": group_ids[bi, ri]} for student in members[cursor:cursor + count])
            cursor += count
    message = "Asignación completa y óptima para los bloques configurados." if name == "OPTIMAL" else "Asignación completa encontrada; no se ha demostrado que use el mínimo número de grupos."
    return SolveResult(name, message, groups, assignments, solver.wall_time)
