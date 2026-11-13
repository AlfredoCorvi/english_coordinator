from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import ceil

from ortools.sat.python import cp_model

from ingles.domain import block_minutes, group_level, period_count, slots, teacher_buildings, validate_bundle


@dataclass
class SolveResult:
    status: str
    message: str
    groups: list
    assignments: list
    seconds: float = 0
    diagnostics: list = field(default_factory=list)

    @property
    def success(self):
        return self.status in ("OPTIMAL", "FEASIBLE")

    def payload(self):
        return {"status": self.status, "message": self.message, "groups": self.groups,
                "assignments": self.assignments, "seconds": self.seconds, "diagnostics": self.diagnostics}


def diagnostic(parameter, detail, action, section, tab):
    return {"Parámetro": parameter, "Detalle": detail, "Cómo corregir": action, "Sección": section, "Pestaña": tab}


def resource_options(bundle):
    s = bundle["settings"]
    count = period_count(s)
    options = {}
    for bi, block in enumerate(bundle["blocks"]):
        times = slots(block, count)
        for ri, room in enumerate(bundle["rooms"]):
            if not times <= slots(room, count):
                continue
            teachers = [ti for ti, teacher in enumerate(bundle["teachers"])
                        if times <= slots(teacher, count)
                        and room["Edificio"] in teacher_buildings(teacher["Edificios"])
                        and int(teacher["Horas máximas"]) * 60 >= block_minutes(s)]
            if teachers:
                options[bi, ri] = teachers
    return options


def resource_summary(bundle):
    options = resource_options(bundle)
    return [{"Bloque": block["Bloque"],
             "Salones compatibles": sum(b == bi for b, _ in options),
             "Docentes compatibles": len({ti for (b, _), teachers in options.items() if b == bi for ti in teachers})}
            for bi, block in enumerate(bundle["blocks"])]


def preflight(bundle, options):
    """Necessary conditions only: every reported failure is a proven obstacle."""
    s = bundle["settings"]
    problems = []
    counts = Counter(group_level(a["Nivel"], s["grouping"]) for a in bundle["students"])
    capacity = min(s["max_group"], max(int(r["Capacidad"]) for r in bundle["rooms"]))
    needed = sum(ceil(n / capacity) for n in counts.values())
    available = sum(int(t["Horas máximas"]) * 60 // block_minutes(s) for t in bundle["teachers"])
    if needed > available:
        problems.append(diagnostic("Horas máximas docentes",
            f"Se necesitan al menos {needed} grupos por nivel y cupo; las horas contratadas permiten como máximo {available}. Cada grupo requiere {block_minutes(s) / 60:g} horas semanales.",
            "Revisa las horas máximas o incorpora docentes con disponibilidad suficiente.", "Datos", "Docentes"))
    for level, n in counts.items():
        if n < s["min_group"]:
            problems.append(diagnostic("Mínimo de alumnos por grupo", f"El nivel {level} tiene {n} alumnos y el mínimo es {s['min_group']}.",
                f"Reduce el mínimo a {n} o menos, o revisa los niveles del padrón.", "Bloques y reglas", "Reglas de asignación"))
    cohorts = defaultdict(list)
    for a in bundle["students"]:
        cohorts[a["Carrera"], a["Grupo"]].append(a)
    for (career, cohort), students in cohorts.items():
        fixed = next((a["Bloque fijo"] for a in students if a["Bloque fijo"]), "")
        reasons = []
        for bi, block in enumerate(bundle["blocks"]):
            if fixed and fixed != block["Bloque"]:
                continue
            rooms = [ri for b, ri in options if b == bi]
            teachers = {ti for ri in rooms for ti in options[bi, ri]}
            demand = Counter((group_level(a["Nivel"], s["grouping"]), a["Edificio"] if s["strict_building"] else "") for a in students)
            required = 0
            detail = ""
            for (level, building), n in demand.items():
                compatible = [ri for ri in rooms if not building or bundle["rooms"][ri]["Edificio"] == building]
                caps = [min(int(bundle["rooms"][ri]["Capacidad"]), s["max_group"]) for ri in compatible]
                if not caps:
                    detail = f"sin salón y docente compatibles{f' en edificio {building}' if building else ''}"
                    break
                if sum(caps) < n:
                    detail = f"nivel {level}: {n} alumnos y solo {sum(caps)} lugares compatibles"
                    break
                required += ceil(n / max(caps))
            if not detail and required > min(len(rooms), len(teachers)):
                detail = f"requiere al menos {required} grupos simultáneos; hay {len(rooms)} salones y {len(teachers)} docentes compatibles"
            if not detail:
                break  # At least one block passes these necessary checks.
            reasons.append(f"{block['Bloque']}: {detail}")
        else:
            problems.append(diagnostic("Bloque común y recursos simultáneos", f"{career} / {cohort}. " + "; ".join(reasons) + ".",
                "Revisa los siete periodos del bloque, disponibilidad y edificios de docentes/salones. Todos los niveles de este grupo de carrera necesitan recursos a la misma hora." + (f" Revisa también su bloque fijo {fixed}." if fixed else ""),
                "Bloques y reglas", "Bloques semanales"))
    return problems


def solve(bundle):
    errors = validate_bundle(bundle)
    if errors:
        return SolveResult("INVALID", "\n".join(errors), [], [])
    s = bundle["settings"]
    students, teachers, rooms, blocks = (bundle[k] for k in ("students", "teachers", "rooms", "blocks"))
    total = len(students)
    group_minutes = block_minutes(s)
    compatible = resource_options(bundle)
    problems = preflight(bundle, compatible)
    if problems:
        return SolveResult("INFEASIBLE", "No se puede generar una propuesta con los datos actuales. Se detectaron estos impedimentos:", [], [], diagnostics=problems)
    model = cp_model.CpModel()
    count = period_count(s)
    bslots = [slots(b, count) for b in blocks]
    assumptions = {}

    def assumption(info):
        var = model.new_bool_var(f"rule_{len(assumptions)}")
        model.add_assumption(var)
        assumptions[var.index] = info
        return var

    cap_rule = assumption(diagnostic("Cupos de grupos y salones", f"Máximo por grupo: {s['max_group']}; cada salón conserva su propio cupo.", "Revisa la capacidad real de los salones y el máximo de alumnos por grupo.", "Datos", "Salones"))
    min_rule = assumption(diagnostic("Mínimo de alumnos por grupo", f"Mínimo exigido: {s['min_group']} alumnos.", "Reduce el mínimo si los niveles o reservas dejan grupos pequeños.", "Bloques y reglas", "Reglas de asignación"))
    hours_rule = assumption(diagnostic("Horas máximas docentes", "La carga semanal de cada docente debe respetar sus horas máximas.", "Revisa horas máximas y disponibilidad; considera incorporar otro docente.", "Datos", "Docentes"))
    room_rule = assumption(diagnostic("Salones sin choques", "Un salón no puede atender dos grupos en el mismo periodo.", "Agrega salones disponibles o cambia los periodos de los bloques que se solapan.", "Datos", "Salones"))
    teacher_rule = assumption(diagnostic("Docentes sin choques", "Un docente no puede atender dos grupos en el mismo periodo.", "Agrega docentes compatibles o cambia los periodos de los bloques que se solapan.", "Datos", "Docentes"))
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
            eligible = compatible.get((bi, ri), [])
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
    cohort_rules = {}
    # A shared weekly block per Carrera + Grupo is mandatory, including when an
    # older saved configuration still contains cohort_block=False.
    for cohort in sorted({key[:2] for key in demand}):
        cohort_rules[cohort] = assumption(diagnostic("Grupo de carrera", f"{cohort[0]} / {cohort[1]}: todos sus alumnos requieren un mismo bloque, con grupos separados por nivel.", "Revisa los niveles, edificios y bloques fijos de sus alumnos y los recursos simultáneos disponibles.", "Datos", "Alumnos"))
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
        model.add(sum(options) == len(members)).only_enforce_if(cohort_rules[career, cohort])
    for (bi, ri, level), opened in level_open.items():
        count = sum(by_cell_level[bi, ri, level])
        capacity = min(int(rooms[ri]["Capacidad"]), s["max_group"])
        model.add(count <= capacity * opened).only_enforce_if(cap_rule)
        model.add(count >= s["min_group"] * opened).only_enforce_if(min_rule)
    # Room and teacher occupancy is checked per actual day/period, not block name.
    for slot in set().union(*bslots):
        for ri in range(len(rooms)):
            model.add(sum(v for (bi, r), v in cell_open.items() if r == ri and slot in bslots[bi]) <= 1).only_enforce_if(room_rule)
        for ti in range(len(teachers)):
            model.add(sum(v for (bi, ri, t), v in teacher_choice.items() if t == ti and slot in bslots[bi]) <= 1).only_enforce_if(teacher_rule)
    for ti, teacher in enumerate(teachers):
        choices = [(bi, ri, v) for (bi, ri, t), v in teacher_choice.items() if t == ti]
        model.add(sum(v for _, _, v in choices) * group_minutes <= int(teacher["Horas máximas"]) * 60).only_enforce_if(hours_rule)
    # Lexicographic objective: first fewer groups, then fewer student relocations.
    model.minimize((total + 1) * sum(cell_open.values()) + sum(mismatch))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = s["solver_seconds"]
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    # Fix guards in the optimization model so assumptions do not restrict
    # presolve/parallel optimization. Keep the original for a failure explanation.
    optimization = model.clone()
    optimization.clear_assumptions()
    for index in assumptions:
        optimization.add(optimization.get_bool_var_from_proto_index(index) == 1)
    status = solver.solve(optimization)
    name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        message = ("No existe una asignación completa con estos bloques y restricciones. Revisa cupos, niveles, edificios, carga docente y horarios; puedes modificar o proponer otros bloques."
                   if status == cp_model.INFEASIBLE else
                   "La búsqueda terminó sin encontrar una solución dentro del tiempo disponible. Esto no demuestra que sea imposible; aumenta el tiempo o ajusta los bloques.")
        core = list(assumptions)
        elapsed = solver.wall_time
        if status == cp_model.INFEASIBLE:
            model.clear_objective()
            explainer = cp_model.CpSolver()
            explainer.parameters.num_search_workers = 1
            explainer.parameters.max_time_in_seconds = min(3, s["solver_seconds"])
            if explainer.solve(model) == cp_model.INFEASIBLE:
                core = explainer.sufficient_assumptions_for_infeasibility()
            elapsed += explainer.wall_time
        info = ([assumptions[i] for i in core] if status == cp_model.INFEASIBLE else
                [diagnostic("Tiempo máximo de búsqueda", f"La búsqueda terminó tras {solver.wall_time:.1f} segundos sin una propuesta completa.", "Aumenta el tiempo máximo de búsqueda. No hay prueba de que las reglas sean incompatibles.", "Bloques y reglas", "Reglas de asignación")])
        return SolveResult(name, message, [], [], elapsed, info)
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
