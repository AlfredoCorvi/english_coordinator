from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from copy import deepcopy
from uuid import uuid4

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
BUILDINGS = ["1", "2", "3", "4", "Idiomas"]
LEVELS = {
    "Prebasic": "A1", "Basic 1": "A1", "Basic 2": "A2", "Basic 3": "A2",
    "Intermediate 1": "B1", "Intermediate 2": "B1", "Intermediate 3": "B2",
    "Intermediate 4": "B2", "Advanced 1": "C1",
}
SCHEMAS = {
    "students": ["Matricula", "Nombre", "Grupo", "Carrera", "Edificio", "Nivel", "Bloque fijo"],
    "teachers": ["ID", "matricula_docente", "Nombre", "Edificios", "Horas máximas", *DAYS],
    "rooms": ["ID", "Salón", "Edificio", "Capacidad", *DAYS],
    "blocks": ["Bloque", *DAYS],
}
KEYS = {"students": "Matricula", "teachers": "ID", "rooms": "ID", "blocks": "Bloque"}
DEFAULT_SETTINGS = {
    "periods_per_day": 11, "start_time": "07:00", "end_time": "15:45", "period_minutes": 45,
    "break_start": "11:30", "break_end": "11:55",
    "grouping": "family", "max_group": 30, "min_group": 1,
    "strict_building": False,
    "solver_seconds": 30,
}


def norm(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(value))
                            if not unicodedata.combining(c)).lower().split())


def clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def canonical_level(value):
    lookup = {norm(k): k for k in [*LEVELS, *set(LEVELS.values())]}
    lookup["pre basic"] = "Prebasic"
    lookup["pre-basic"] = "Prebasic"
    return lookup.get(norm(value), clean(value))


def cefr(value):
    value = canonical_level(value)
    return LEVELS.get(value, value if value in LEVELS.values() else "")


def group_level(value, mode):
    if mode == "course":
        return canonical_level(value)
    return cefr(value)[:1] if mode == "family" else cefr(value)


def building(value):
    value = re.sub(r"^edificio\s*", "", norm(clean(value)))
    return "Idiomas" if value in ("idiomas", "de idiomas") else value


def teacher_buildings(value):
    if clean(value) == "*":
        return set(BUILDINGS)
    return {building(x) for x in re.split(r"[,;]", clean(value)) if x.strip()}


def periods(value, count):
    value = clean(value)
    if not value:
        return set()
    if value == "*":
        return set(range(1, count + 1))
    out = set()
    for token in value.replace(";", ",").split(","):
        token = token.strip()
        if re.fullmatch(r"\d+", token):
            numbers = [int(token)]
        elif re.fullmatch(r"\d+\s*-\s*\d+", token):
            a, b = map(int, token.split("-"))
            if a > b:
                raise ValueError(f"Rango invertido: {token}")
            numbers = range(a, b + 1)
        else:
            raise ValueError(f"Periodo no válido: '{token}'. Usa 1,2,4-6 o *.")
        for p in numbers:
            if p < 1 or p > count:
                raise ValueError(f"El periodo {p} debe estar entre 1 y {count}.")
            if p in out:
                raise ValueError(f"El periodo {p} está repetido.")
            out.add(p)
    return out


def slots(row, count):
    return {(day, p) for day in DAYS for p in periods(row.get(day, ""), count)}


def time_minutes(value):
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def time_label(value):
    return f"{value // 60:02}:{value % 60:02}"


def daily_periods(settings):
    """Full teaching periods only. A break is never an assignable period.

    If a complete period would overlap the break, start it after the break.
    Any leftover minutes before the break remain free; classes are not split.
    Call after validate_settings for user-provided settings.
    """
    cursor = time_minutes(settings["start_time"])
    pause_start = time_minutes(settings["break_start"])
    pause_end = time_minutes(settings["break_end"])
    duration = settings["period_minutes"]
    result = []
    end = time_minutes(settings["end_time"])
    while cursor + duration <= end and duration > 0:
        if cursor < pause_end and cursor + duration > pause_start:
            cursor = pause_end
        if cursor + duration > end:
            break
        result.append({"period": len(result) + 1, "start": cursor, "end": cursor + duration})
        cursor += duration
    return result


def daily_agenda(settings):
    rows = [{**row, "kind": "class"} for row in daily_periods(settings)]
    start, end = time_minutes(settings["break_start"]), time_minutes(settings["break_end"])
    if start < time_minutes(settings["end_time"]) and end > time_minutes(settings["start_time"]):
        start = max(start, time_minutes(settings["start_time"]))
        end = min(end, time_minutes(settings["end_time"]))
        rows.append({"period": None, "start": start, "end": end, "kind": "break"})
    return sorted(rows, key=lambda row: row["start"])


def period_count(settings):
    return len(daily_periods(settings))


def period_label(settings, p):
    if not 1 <= p <= period_count(settings):
        raise ValueError("Periodo fuera de la jornada.")
    row = daily_periods(settings)[p - 1]
    return f"{time_label(row['start'])}–{time_label(row['end'])}"


def block_minutes(settings):
    return 7 * settings["period_minutes"]


def public_columns(kind):
    return [column for column in SCHEMAS[kind] if column != "ID"]


def catalog_key(kind, row):
    if kind == "teachers":
        return clean(row.get("matricula_docente", ""))
    if kind == "rooms":
        return building(row.get("Edificio", "")), norm(row.get("Salón", ""))
    return clean(row.get(KEYS[kind], ""))


def canonical_rows(kind, rows, existing=()):
    result = []
    known = {catalog_key(kind, row): row["ID"] for row in existing} if kind in ("teachers", "rooms") else {}
    for source in rows:
        row = {c: clean(source.get(c, "")) for c in SCHEMAS[kind]}
        if not any(row.values()):
            continue
        if "Edificio" in row:
            row["Edificio"] = building(row["Edificio"])
        if kind == "students":
            row["Nivel"] = canonical_level(row["Nivel"])
        if kind in ("teachers", "rooms"):
            row["ID"] = row["ID"] or known.get(catalog_key(kind, row)) or uuid4().hex
        result.append(row)
    return result


def empty_bundle():
    return {**{kind: [] for kind in SCHEMAS}, "settings": deepcopy(DEFAULT_SETTINGS)}


def validate_settings(s):
    errors = []
    limits = {"period_minutes": (1, 180), "max_group": (25, 35),
              "min_group": (1, 35), "solver_seconds": (1, 300)}
    for key, (lo, hi) in limits.items():
        value = s.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            errors.append(f"Configuración {key}: se requiere un entero entre {lo} y {hi}.")
    if not errors and s["min_group"] > s["max_group"]:
        errors.append("El cupo mínimo no puede superar al máximo.")
    if s.get("grouping") not in ("family", "cefr", "course"):
        errors.append("El criterio de agrupación no es válido.")
    for key, name in (("start_time", "Inicio de jornada"), ("end_time", "Fin de jornada"), ("break_start", "Inicio del receso"), ("break_end", "Fin del receso")):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(s.get(key, ""))):
            errors.append(f"{name}: usa una hora válida en formato HH:MM.")
    if not errors:
        if time_minutes(s["break_start"]) >= time_minutes(s["break_end"]):
            errors.append("El fin del receso debe ser posterior a su inicio, dentro del mismo día.")
        elif time_minutes(s["start_time"]) >= time_minutes(s["end_time"]):
            errors.append("El fin de jornada debe ser posterior al inicio, dentro del mismo día.")
        elif not daily_periods(s):
            errors.append("La jornada no tiene espacio para un periodo completo fuera del receso. Amplía la jornada o reduce la duración.")
    return errors


def validate_table(kind, rows, settings):
    errors = []
    seen = set()
    required = {"students": SCHEMAS["students"][:-1],
                "teachers": ["ID", "matricula_docente", "Nombre", "Edificios", "Horas máximas"],
                "rooms": ["ID", "Salón", "Edificio", "Capacidad"], "blocks": ["Bloque"]}[kind]
    physical_rooms = set()
    teacher_numbers = set()
    for index, row in enumerate(rows, 2):
        label = f"Fila {index} ({catalog_key(kind, row)})"
        for c in required:
            if not clean(row.get(c, "")):
                errors.append(f"{label}: falta {c}.")
        key = clean(row.get(KEYS[kind], ""))
        if key in seen:
            errors.append(f"{label}: identificador duplicado '{key}'.")
        seen.add(key)
        if kind == "teachers":
            number = clean(row.get("matricula_docente", ""))
            if number in teacher_numbers:
                errors.append(f"{label}: matrícula docente duplicada '{number}'.")
            teacher_numbers.add(number)
        if kind == "students":
            if not cefr(row.get("Nivel", "")):
                errors.append(f"{label}: nivel de inglés desconocido.")
            elif settings["grouping"] == "course" and row["Nivel"] not in LEVELS:
                errors.append(f"{label}: indica el curso exacto para agrupar por curso.")
        if "Edificio" in row and row["Edificio"] not in BUILDINGS:
            errors.append(f"{label}: edificio válido: 1, 2, 3, 4 o Idiomas.")
        if kind == "teachers" and (not teacher_buildings(row.get("Edificios", "")) or
                                   not teacher_buildings(row.get("Edificios", "")) <= set(BUILDINGS)):
            errors.append(f"{label}: edificios permitidos no válidos.")
        if kind in ("teachers", "rooms"):
            col = "Capacidad" if kind == "rooms" else "Horas máximas"
            if not re.fullmatch(r"\d+", clean(row.get(col, ""))) or int(row.get(col) or 0) < 1:
                errors.append(f"{label}: {col} debe ser un entero positivo.")
        if kind == "rooms":
            physical = (row["Edificio"], norm(row["Salón"]))
            if physical in physical_rooms:
                errors.append(f"{label}: el salón ya existe en ese edificio.")
            physical_rooms.add(physical)
        if kind != "students":
            try:
                times = slots(row, period_count(settings))
                if kind == "blocks" and len(times) != 7:
                    errors.append(f"{label}: el bloque tiene {len(times)} periodos; necesita exactamente 7.")
                elif not times:
                    errors.append(f"{label}: falta disponibilidad.")
            except ValueError as exc:
                errors.append(f"{label}: {exc}")
    return errors


def validate_bundle(bundle):
    errors = validate_settings(bundle["settings"])
    if errors:
        return errors
    for kind in SCHEMAS:
        if not bundle[kind]:
            errors.append(f"Faltan registros en {kind}.")
        errors.extend(validate_table(kind, bundle[kind], bundle["settings"]))
    blocks = {b["Bloque"] for b in bundle["blocks"]}
    fixed_by_cohort = defaultdict(set)
    for student in bundle["students"]:
        if student.get("Bloque fijo") and student["Bloque fijo"] not in blocks:
            errors.append(f"{student['Matricula']}: el bloque fijo no existe.")
        if student.get("Bloque fijo"):
            fixed_by_cohort[student["Carrera"], student["Grupo"]].add(student["Bloque fijo"])
    for (career, cohort), fixed in fixed_by_cohort.items():
        if len(fixed) > 1:
            errors.append(f"{career} / {cohort}: bloques fijos incompatibles ({', '.join(sorted(fixed))}). Todos los alumnos del grupo de carrera deben compartir el mismo bloque.")
    return errors


def propose_blocks(count):
    """Plantillas de siete periodos; no sustituyen la búsqueda de asignaciones."""
    remaining = {d: list(range(1, count + 1)) for d in DAYS}
    # Distribute the unused remainder over the week, preserving the last period
    # of each day. Automatic templates therefore cover the entire jornada.
    spare = count * len(DAYS) % 7
    candidates = [(d, p) for p in range(1, count + 1) for d in DAYS]
    for i in range(spare):
        d, p = candidates[(i + 1) * len(candidates) // (spare + 1)]
        remaining[d].remove(p)
    blocks = []
    while sum(map(len, remaining.values())) >= 7:
        chosen = {d: [] for d in DAYS}
        for _ in range(7):
            candidates = [d for d in DAYS if remaining[d]]
            day = min(candidates, key=lambda d: (len(chosen[d]), -len(remaining[d]), DAYS.index(d)))
            chosen[day].append(remaining[day].pop(0))
        blocks.append({"Bloque": f"Bloque {len(blocks) + 1}",
                       **{d: ",".join(map(str, chosen[d])) for d in DAYS}})
    return blocks


def demo_bundle():
    bundle = empty_bundle()
    available = propose_blocks(period_count(bundle["settings"]))
    bundle["blocks"] = [available[0], available[len(available) // 2], available[-1]]
    courses = list(LEVELS)
    for i in range(180):
        bundle["students"].append({"Matricula": f"{i + 1:07}", "Nombre": f"Estudiante de ejemplo {i + 1:03}",
            "Grupo": f"{i % 6 + 1}A", "Carrera": ["Ingeniería", "Administración", "Diseño"][i % 3],
            "Edificio": str(i % 4 + 1), "Nivel": courses[i % len(courses)], "Bloque fijo": ""})
    for i, b in enumerate(BUILDINGS):
        bundle["rooms"].append({"ID": f"S{i + 1}", "Salón": "101", "Edificio": b, "Capacidad": "30", **{d: "*" for d in DAYS}})
        bundle["teachers"].append({"ID": f"D{i + 1}", "matricula_docente": f"D{i + 1}", "Nombre": f"Docente de ejemplo {i + 1}", "Edificios": b,
                                    "Horas máximas": "21", **{d: "*" for d in DAYS}})
    return bundle
