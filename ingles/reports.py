from collections import defaultdict
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from ingles.audit import audit, errors_only
from ingles.domain import DAYS, block_minutes, daily_agenda, period_count, periods, time_label
from ingles.exchange import group_summary, roster, teacher_load


def export_pdf(bundle, plan):
    issues = audit(bundle, plan)
    if errors_only(issues):
        raise ValueError("Corrige los errores de auditoría antes de exportar.")
    stream = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Cell", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#17324D")))
    styles.add(ParagraphStyle(name="HeadCell", parent=styles["Cell"], fontName="Helvetica-Bold", textColor=colors.white))
    styles["Title"].textColor = colors.HexColor("#17324D")
    styles["Heading2"].textColor = colors.HexColor("#167C80")
    doc = SimpleDocTemplate(stream, pagesize=landscape(A4), rightMargin=15 * mm, leftMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title="Planeación de inglés", author="Coordinación de Inglés")
    story = []

    def p(value, style="Cell"):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])

    def table(headers, rows, widths, compact=False):
        data = [[p(h, "HeadCell") for h in headers]] + [[p(row.get(h, "")) for h in headers] for row in rows]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF4F6")]),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 1 if compact else 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1 if compact else 6)]))
        story.extend([t, Spacer(1, 5 * mm)])

    now = datetime.now(ZoneInfo("America/Mexico_City")).strftime("%d/%m/%Y %H:%M")
    story.extend([p("Planeación de inglés", "Title"), p(f"Coordinación académica · Generado {now} (Ciudad de México)"), Spacer(1, 5 * mm)])
    s = bundle["settings"]
    story.append(p(f"{len(bundle['students'])} alumnos · {len(plan['groups'])} grupos · 7 periodos semanales por grupo", "Heading2"))
    minutes = block_minutes(s)
    story.append(p(f"Jornada: {s['start_time']} - {s['end_time']} · {period_count(s)} periodos disponibles por día."))
    story.append(p(f"Periodos de {s['period_minutes']} min; {minutes // 60} h {minutes % 60:02} min de clase por bloque. Receso diario: {s['break_start']} - {s['break_end']}, sin clases. Carga docente expresada en horas de reloj."))
    mode = {"family": "Familias A / B / C", "cefr": "Niveles A1 / A2 / B1 / B2 / C1", "course": "Curso exacto"}[bundle["settings"]["grouping"]]
    story.append(p(f"Agrupación: {mode}. Cupo máximo: {bundle['settings']['max_group']}. Auditoría: sin errores; {len(issues)} avisos."))
    story.append(Spacer(1, 4 * mm))
    summary = group_summary(bundle, plan)
    table(list(summary[0]), summary, [25, 28, 30, 64, 21, 25, 23, 23, 20])
    story.append(p("Carga docente", "Heading2"))
    table(["Docente", "Grupos", "Horas asignadas", "Horas máximas", "Horas libres"], teacher_load(bundle, plan), [103, 30, 45, 45, 36])
    if issues:
        story.append(p("Avisos para la coordinadora", "Heading2"))
        table(["Severidad", "Regla", "Detalle"], issues, [25, 45, 189])
    story.append(p("Los horarios de las materias regulares aún no existen. El Excel incluye las horas reservadas por grupo de carrera para planear esas materias posteriormente."))
    used_blocks = {g["block"] for g in plan["groups"]}
    for block in bundle["blocks"]:
        if block["Bloque"] not in used_blocks:
            continue
        story.extend([PageBreak(), p(block["Bloque"], "Title"), p(f"Horario semanal · siete periodos de {s['period_minutes']} min", "Heading2")])
        grid = []
        for row in daily_agenda(s):
            pause = row["kind"] == "break"
            label = f"{time_label(row['start'])}-{time_label(row['end'])}"
            grid.append({"Periodo": f"{'Receso' if pause else row['period']} · {label}",
                         **{d: "Receso · sin clases" if pause else ("Inglés" if row["period"] in periods(block[d], period_count(s)) else "") for d in DAYS}})
        table(["Periodo", *DAYS], grid, [44, 43, 43, 43, 43, 43], compact=True)
        rows = [g for g in summary if g["Bloque"] == block["Bloque"]]
        table(["Grupo Inglés", "Nivel agrupado", "Docente", "Edificio", "Salón", "Alumnos"], rows, [32, 33, 90, 30, 39, 35])
    by_group = defaultdict(list)
    for row in roster(bundle, plan):
        by_group[row["Grupo Inglés"]].append(row)
    students = {a["Matricula"]: a for a in bundle["students"]}
    for group in summary:
        story.extend([PageBreak(), p(f"{group['Grupo Inglés']} · {group['Nivel agrupado']}", "Title"),
                      p(f"{group['Bloque']} · {group['Docente']} · Salón {group['Salón']} / Edificio {group['Edificio']}", "Heading2")])
        rows = [{**row, "Carrera": students[row["Matricula"]]["Carrera"]} for row in by_group[group["Grupo Inglés"]]]
        table(["Matricula", "Nombre", "Carrera", "Grupo", "Nivel de inglés"], rows, [29, 95, 60, 23, 52], compact=True)

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5B6E82"))
        canvas.drawString(15 * mm, 9 * mm, "Coordinación de Inglés | Horarios y grupos")
        canvas.drawRightString(282 * mm, 9 * mm, f"Página {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
