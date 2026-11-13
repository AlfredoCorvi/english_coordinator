from __future__ import annotations

from collections import Counter, defaultdict
import re
from io import BytesIO
from zipfile import ZipFile, BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ingles.audit import audit, errors_only
from ingles.domain import (DAYS, SCHEMAS, block_minutes, canonical_rows, cefr, clean,
                           daily_agenda, norm, period_count, period_label, periods, public_columns, time_label)

HEADERS = ["Matricula", "Nombre", "Grupo", "Nombre de materia", "Grupo Inglés", "Nivel de inglés", "Docente", "Salón"]
ALIASES = {
    "Matricula": ["matrícula", "id alumno", "numero de control", "número de control"],
    "Nombre": ["nombre completo", "alumno", "docente", "profesor", "nombre docente"],
    "Grupo": ["grupo de carrera", "grupo origen"], "Carrera": ["programa", "licenciatura"],
    "Nivel": ["nivel de inglés", "nivel de ingles", "curso", "nivel ingles"],
    "Horas máximas": ["horas maximas", "horas semanales", "carga máxima", "horas laborables"],
    "Edificios": ["edificio", "edificios permitidos"],
    "matricula_docente": ["matrícula docente", "matricula docente", "matricula", "matrícula", "clave", "id docente", "ID"],
    "Salón": ["salon", "aula"], "Capacidad": ["cupo"],
    "Bloque": ["nombre de materia", "materia", "nombre del bloque"],
}


def excel_sheets(data):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("El archivo excede 20 MB.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError("El archivo descomprimido excede 100 MB.")
        book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, KeyError, OSError) as exc:
        raise ValueError("No se pudo leer el archivo. Usa un libro Excel .xlsx válido.") from exc
    try:
        return book.sheetnames
    finally:
        book.close()


def read_excel(data, sheet):
    excel_sheets(data)
    book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    try:
        ws = book[sheet]
        if ws.max_row > 20001 or ws.max_column > 100:
            raise ValueError("La hoja debe tener como máximo 20,000 registros y 100 columnas.")
        rows = ws.iter_rows()
        headers = [clean(c.value) for c in next(rows, [])]
        while headers and not headers[-1]:
            headers.pop()
        if not headers or any(not h for h in headers) or len({norm(h) for h in headers}) != len(headers):
            raise ValueError("La primera fila debe tener encabezados distintos, sin celdas vacías entre columnas.")
        result = []
        for cells in rows:
            row = {}
            for key, cell in zip(headers, cells):
                if cell.data_type == "f":
                    raise ValueError(f"{cell.coordinate}: convierte las fórmulas a valores antes de importar.")
                value = clean(cell.value)
                # Keep matrícula/IDs displayed with a zero-filled Excel number format.
                if isinstance(cell.value, (int, float)) and set(cell.number_format) == {"0"}:
                    value = value.zfill(len(cell.number_format))
                row[key] = value
            if any(row.values()):
                result.append(row)
        return headers, result
    finally:
        book.close()


def suggested_mapping(kind, headers):
    mapping = {}
    for target in public_columns(kind):
        aliases = {norm(target), *(norm(x) for x in ALIASES.get(target, []))}
        mapping[target] = next((h for h in headers if norm(h) in aliases), "")
    return mapping


def map_rows(kind, rows, mapping, existing=()):
    columns = [v for v in mapping.values() if v]
    if len(columns) != len(set(columns)):
        raise ValueError("Una columna del Excel no puede usarse para dos campos distintos.")
    return canonical_rows(kind, [{target: row.get(mapping.get(target), "") for target in public_columns(kind)} for row in rows], existing)


def roster(bundle, plan):
    students = {a["Matricula"]: a for a in bundle["students"]}
    groups = {g["id"]: g for g in plan["groups"]}
    teachers = {t["ID"]: t for t in bundle["teachers"]}
    rooms = {r["ID"]: r for r in bundle["rooms"]}
    result = []
    for assignment in plan["assignments"]:
        student, group = students[assignment["student"]], groups[assignment["group"]]
        teacher, room = teachers[group["teacher"]], rooms[group["room"]]
        result.append({
                "Matricula": student["Matricula"], "Nombre": student["Nombre"], "Grupo": student["Grupo"],
                "Nombre de materia": group["block"], "Grupo Inglés": group["id"],
                "Nivel de inglés": f"{student['Nivel']} ({cefr(student['Nivel'])})" if student["Nivel"] != cefr(student["Nivel"]) else student["Nivel"],
                "Docente": teacher["Nombre"], "Salón": f"{room['Salón']} · Edificio {room['Edificio']}"})
    return sorted(result, key=lambda row: (row["Grupo Inglés"], row["Nombre"], row["Matricula"]))


def group_summary(bundle, plan):
    counts = Counter(a["group"] for a in plan["assignments"])
    teachers = {t["ID"]: t for t in bundle["teachers"]}
    rooms = {r["ID"]: r for r in bundle["rooms"]}
    return [{"Grupo Inglés": g["id"], "Nivel agrupado": g["level"], "Bloque": g["block"],
             "Docente": teachers[g["teacher"]]["Nombre"], "Edificio": rooms[g["room"]]["Edificio"],
             "Salón": rooms[g["room"]]["Salón"], "Alumnos": counts[g["id"]],
             "Cupo": min(int(rooms[g["room"]]["Capacidad"]), bundle["settings"]["max_group"]),
             "Horas": round(block_minutes(bundle["settings"]) / 60, 2)}
            for g in plan["groups"]]


def teacher_load(bundle, plan):
    counts = Counter(g["teacher"] for g in plan["groups"])
    per_group = block_minutes(bundle["settings"])
    return [{"Docente": t["Nombre"], "Grupos": counts[t["ID"]], "Horas asignadas": round(per_group * counts[t["ID"]] / 60, 2),
             "Horas máximas": int(t["Horas máximas"]), "Horas libres": round(int(t["Horas máximas"]) - per_group * counts[t["ID"]] / 60, 2)}
            for t in bundle["teachers"]]


def reservations(bundle, plan):
    students = {a["Matricula"]: a for a in bundle["students"]}
    groups = {g["id"]: g for g in plan["groups"]}
    blocks = {b["Bloque"]: b for b in bundle["blocks"]}
    unique = set()
    for a in plan["assignments"]:
        student, group = students[a["student"]], groups[a["group"]]
        for day in DAYS:
            for p in periods(blocks[group["block"]][day], period_count(bundle["settings"])):
                unique.add((student["Carrera"], student["Grupo"], day, p))
    return [{"Carrera": c, "Grupo": g, "Día": d, "Periodo reservado": p,
             "Horario": period_label(bundle["settings"], p)}
            for c, g, d, p in sorted(unique, key=lambda x: (x[0], x[1], DAYS.index(x[2]), x[3]))]


def day_rows(settings):
    return [{"Periodo": row["period"] if row["kind"] == "class" else "Receso",
             "Inicio": time_label(row["start"]), "Fin": time_label(row["end"]),
             "Duración (min)": row["end"] - row["start"],
             "Asignable": "Sí" if row["kind"] == "class" else "No"}
            for row in daily_agenda(settings)]


def schedule_rows(bundle, plan):
    blocks = {b["Bloque"]: b for b in bundle["blocks"]}
    summary = {g["Grupo Inglés"]: g for g in group_summary(bundle, plan)}
    rows = []
    for g in plan["groups"]:
        for day in DAYS:
            for p in sorted(periods(blocks[g["block"]][day], period_count(bundle["settings"]))):
                rows.append({"Grupo Inglés": g["id"], "Bloque": g["block"], "Día": day, "Periodo": p,
                             "Horario": period_label(bundle["settings"], p), "Docente": summary[g["id"]]["Docente"],
                             "Salón": summary[g["id"]]["Salón"], "Edificio": summary[g["id"]]["Edificio"]})
    return rows


def style_sheet(ws, widths=None):
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    ws.print_title_rows = "1:1"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="17324D")
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    for row in ws.iter_rows(min_row=2):
        ws.row_dimensions[row[0].row].height = 34
        for cell in row:
            cell.font = Font(name="Calibri", size=11, color="17324D")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if cell.row % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="EEF4F6")
    for col in range(1, ws.max_column + 1):
        auto = min(40, max(14, max(len(str(ws.cell(row, col).value or "")) for row in range(1, min(ws.max_row, 100) + 1)) + 2))
        ws.column_dimensions[get_column_letter(col)].width = widths[col - 1] if widths else auto


def append_text_safe(ws, values):
    ws.append(values)
    # Every imported string is exported as literal text, including Excel formula prefixes.
    for cell, value in zip(ws[ws.max_row], values):
        if isinstance(value, str):
            cell.data_type = "s"
            cell.number_format = "@"


def workbook_bytes(sheets):
    book = Workbook()
    book.remove(book.active)
    for name, headers, rows in sheets:
        ws = book.create_sheet(name)
        append_text_safe(ws, headers)
        for row in rows:
            append_text_safe(ws, [row.get(h, "") for h in headers])
        style_sheet(ws, [16, 36, 14, 22, 17, 29, 30, 27] if headers == HEADERS else None)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def export_excel(bundle, plan):
    issues = audit(bundle, plan)
    if errors_only(issues):
        raise ValueError("La auditoría tiene errores. Corrige el horario antes de exportar.")
    listed = roster(bundle, plan)
    tables = [("Listado", HEADERS, listed)]
    for name, rows in [("Grupos", group_summary(bundle, plan)), ("Horarios", schedule_rows(bundle, plan)),
                       ("Jornada", day_rows(bundle["settings"])),
                       ("Carga docente", teacher_load(bundle, plan)), ("Reservas carrera", reservations(bundle, plan)),
                       ("Auditoría", issues or [{"Severidad": "Correcto", "Regla": "Auditoría", "Detalle": "Sin errores detectados"}])]:
        tables.append((name, list(rows[0]) if rows else [], rows))
    for index, g in enumerate(plan["groups"], 1):
        tables.append((f"Grupo {index:03}", HEADERS, [row for row in listed if row["Grupo Inglés"] == g["id"]]))
    return workbook_bytes(tables)


def template_excel(kind, demo):
    return workbook_bytes([(kind, public_columns(kind), demo[kind])])


def export_career_excel(bundle, plan):
    """Printable lists by Carrera + Grupo, retaining each student's English level."""
    if errors_only(audit(bundle, plan)):
        raise ValueError("La auditoría tiene errores. Corrige el horario antes de exportar.")
    students = {a["Matricula"]: a for a in bundle["students"]}
    cohorts = defaultdict(list)
    for row in roster(bundle, plan):
        student = students[row["Matricula"]]
        cohorts[student["Carrera"], student["Grupo"]].append(row)
    schedules = defaultdict(list)
    for row in reservations(bundle, plan):
        schedules[row["Carrera"], row["Grupo"]].append(f"{row['Día']}: {row['Horario']}")
    book = Workbook()
    book.remove(book.active)
    for index, ((career, cohort), rows) in enumerate(sorted(cohorts.items()), 1):
        # Numeric prefix guarantees unique names even after truncation/sanitizing.
        title = re.sub(r"[\[\]:*?/\\]", "-", f"{index:03} {career} {cohort}")[:31].strip("'")
        ws = book.create_sheet(title)
        append_text_safe(ws, [f"Inglés · {career} · Grupo {cohort}"])
        append_text_safe(ws, ["Horario común: " + " | ".join(schedules[career, cohort])])
        append_text_safe(ws, HEADERS)
        for row in sorted(rows, key=lambda r: (r["Nombre"], r["Matricula"])):
            append_text_safe(ws, [row[h] for h in HEADERS])
        style_sheet(ws, [16, 36, 14, 22, 17, 29, 30, 27])
        ws.merge_cells("A1:H1")
        ws.merge_cells("A2:H2")
        ws.row_dimensions[1].height = 30
        ws.row_dimensions[2].height = 48
        for cell in ws[3]:
            cell.fill = PatternFill("solid", fgColor="17324D")
            cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = f"A3:H{ws.max_row}"
        ws.print_title_rows = "1:3"
        ws.print_area = f"A1:H{ws.max_row}"
        ws.oddFooter.center.text = "Página &P de &N"
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
