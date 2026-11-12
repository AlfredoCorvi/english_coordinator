from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from copy import deepcopy

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
BUILDINGS = ["1", "2", "3", "4", "Idiomas"]
LEVELS = {
    "Prebasic": "A1", "Basic 1": "A1", "Basic 2": "A2", "Basic 3": "A2",
    "Intermediate 1": "B1", "Intermediate 2": "B1", "Intermediate 3": "B2",
    "Intermediate 4": "B2", "Advanced 1": "C1",
}
SCHEMAS = {
    "students": ["Matricula", "Nombre", "Grupo", "Carrera", "Edificio", "Nivel", "Bloque fijo"],
    "teachers": ["ID", "Nombre", "Edificios", "Horas máximas", *DAYS],
    "rooms": ["ID", "Salón", "Edificio", "Capacidad", *DAYS],
    "blocks": ["Bloque", *DAYS],
}
KEYS = {"students": "Matricula", "teachers": "ID", "rooms": "ID", "blocks": "Bloque"}
DEFAULT_SETTINGS = {
    "periods_per_day": 8, "start_time": "07:00", "period_minutes": 60,
    "grouping": "family", "max_group": 30, "min_group": 1,
    "strict_building": False, "transfer_periods": 1,
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


def transfer_conflict(first, second, gap):
    return any(d == e and abs(p - q) <= gap for d, p in first for e, q in second)


def canonical_rows(kind, rows):
    result = []
    for source in rows:
        row = {c: clean(source.get(c, "")) for c in SCHEMAS[kind]}
        if not any(row.values()):
            continue
        if "Edificio" in row:
            row["Edificio"] = building(row["Edificio"])
        if kind == "students":
            row["Nivel"] = canonical_level(row["Nivel"])
        result.append(row)
    return result


def empty_bundle():
    return {**{kind: [] for kind in SCHEMAS}, "settings": deepcopy(DEFAULT_SETTINGS)}


def validate_settings(s):
    errors = []
    limits = {"periods_per_day": (1, 16), "period_minutes": (60, 60), "max_group": (25, 30),
              "min_group": (1, 30), "transfer_periods": (0, 4), "solver_seconds": (1, 300)}
    for key, (lo, hi) in limits.items():
        value = s.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            errors.append(f"Configuración {key}: se requiere un entero entre {lo} y {hi}.")
    if not errors and s["min_group"] > s["max_group"]:
        errors.append("El cupo mínimo no puede superar al máximo.")
    if s.get("grouping") not in ("family", "cefr", "course"):
        errors.append("El criterio de agrupación no es válido.")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(s.get("start_time", ""))):
        errors.append("La hora inicial debe tener formato HH:MM.")
    elif isinstance(s.get("periods_per_day"), int):
        h, m = map(int, s["start_time"].split(":"))
        if h * 60 + m + s["periods_per_day"] * 60 > 1440:
            errors.append("La jornada no puede terminar después de medianoche.")
    return errors


def validate_table(kind, rows, settings):
    errors = []
    seen = set()
    required = {"students": SCHEMAS["students"][:-1],
                "teachers": ["ID", "Nombre", "Edificios", "Horas máximas"],
                "rooms": ["ID", "Salón", "Edificio", "Capacidad"], "blocks": ["Bloque"]}[kind]
    physical_rooms = set()
    for index, row in enumerate(rows, 2):
        label = f"Fila {index} ({row.get(KEYS[kind], '')})"
        for c in required:
            if not clean(row.get(c, "")):
                errors.append(f"{label}: falta {c}.")
        key = clean(row.get(KEYS[kind], ""))
        if key in seen:
            errors.append(f"{label}: identificador duplicado '{key}'.")
        seen.add(key)
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
                times = slots(row, settings["periods_per_day"])
                if kind == "blocks" and len(times) != 7:
                    errors.append(f"{label}: el bloque tiene {len(times)} horas; necesita exactamente 7.")
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
    """Plantillas de siete horas; no sustituyen la búsqueda de asignaciones."""
    remaining = {d: list(range(1, count + 1)) for d in DAYS}
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
    bundle["blocks"] = propose_blocks(8)[:3]
    courses = list(LEVELS)
    for i in range(180):
        bundle["students"].append({"Matricula": f"{i + 1:07}", "Nombre": f"Estudiante de ejemplo {i + 1:03}",
            "Grupo": f"{i % 6 + 1}A", "Carrera": ["Ingeniería", "Administración", "Diseño"][i % 3],
            "Edificio": str(i % 4 + 1), "Nivel": courses[i % len(courses)], "Bloque fijo": ""})
    for i, b in enumerate(BUILDINGS):
        bundle["rooms"].append({"ID": f"S{i + 1}", "Salón": "101", "Edificio": b, "Capacidad": "30", **{d: "*" for d in DAYS}})
        bundle["teachers"].append({"ID": f"D{i + 1}", "Nombre": f"Docente de ejemplo {i + 1}", "Edificios": b,
                                    "Horas máximas": "21", **{d: "*" for d in DAYS}})
    return bundle
