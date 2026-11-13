from __future__ import annotations

import hashlib
import os
from copy import deepcopy
from datetime import time
from pathlib import Path

import pandas as pd
import streamlit as st

from ingles.audit import audit, errors_only
from ingles.domain import (BUILDINGS, DAYS, KEYS, LEVELS, SCHEMAS, block_minutes, canonical_rows, catalog_key, daily_agenda, demo_bundle, time_label,
                           period_count, periods, propose_blocks, public_columns, validate_bundle, validate_settings, validate_table)
from ingles.exchange import (day_rows, excel_sheets, export_excel, export_career_excel, group_summary, map_rows,
                             read_excel, reservations, roster, schedule_rows, suggested_mapping,
                             teacher_load, template_excel)
from ingles.reports import export_pdf
from ingles.scheduler import resource_summary, solve
from ingles.storage import Store, ConcurrentEdit

st.set_page_config(page_title="Inglés · Planeación académica", page_icon="📚", layout="wide")
ROOT = Path(__file__).resolve().parent
store = Store(os.environ.get("INGLES_DB_PATH", str(ROOT / "data" / "ingles.sqlite3")))
bundle, revision = store.load()
PAGES = ["Vista general", "Datos", "Bloques y reglas", "Generar", "Resultados", "Auditoría"]

st.markdown("""<style>
 .block-container {padding-top:2.1rem; max-width:1450px;}
 h1,h2,h3 {letter-spacing:-.035em;}
 [data-testid="stSidebar"] {border-right:1px solid #dce5ed;}
 [data-testid="stMetric"] {background:white;border:1px solid #dce5ed;border-radius:14px;padding:17px 20px;}
 .eyebrow {font-size:.74rem;letter-spacing:.16em;color:#167c80;font-weight:700;margin-bottom:8px;}
 .hero {background:#17324d;color:white;border-radius:18px;padding:30px 34px;margin:10px 0 24px;}
 .hero h2 {color:white;margin:0 0 8px;font-size:2rem;}
 .hero p {color:#d8e6ee;margin:0;max-width:820px;}
 .step {color:#167c80;font-weight:700;font-size:.8rem;letter-spacing:.06em;}
 div.stButton > button[kind="primary"] {border-radius:9px;}
 </style>""", unsafe_allow_html=True)


def go(page, tab=None):
    st.session_state["next_page"] = page
    if tab:
        st.session_state["next_tab"] = ("data_tabs" if page == "Datos" else "rule_tabs", tab)
    st.rerun()


def flash(message):
    st.session_state["flash"] = message


def show_errors(errors):
    st.error(f"Hay {len(errors)} problemas que debes corregir.")
    st.dataframe(pd.DataFrame({"Detalle": errors}), hide_index=True, width="stretch")


def save_data(candidate, note):
    try:
        store.save(candidate, revision, note)
    except ConcurrentEdit as exc:
        st.error(str(exc))
        return False
    flash("Cambios guardados. Las versiones anteriores se conservan.")
    return True


def frame(rows, columns):
    return pd.DataFrame(rows, columns=columns).fillna("").astype(str)


def records(df):
    return df.astype(object).where(pd.notna(df), "").to_dict("records")


@st.cache_data
def template(kind):
    example = demo_bundle()
    if kind == "students":
        example[kind] = example[kind][:9]
    return template_excel(kind, example)


def table_editor(kind, label):
    st.subheader(label)
    if kind == "students":
        st.caption("Una fila por alumno. Carrera + Grupo identifica a quienes comparten horario. Bloque fijo es opcional: si lo indicas para un alumno, reserva ese bloque para todo su grupo de carrera.")
    elif kind == "teachers":
        st.caption("matricula_docente identifica al docente y debe ser única. Edificios: 1,2,3,4,Idiomas o * para todos. Horas máximas: horas de reloj disponibles para inglés por semana; el receso no cuenta como clase.")
    elif kind == "rooms":
        st.caption("Un salón se identifica por Edificio + Salón. El mismo número de salón puede existir en edificios diferentes.")
    if kind in ("teachers", "rooms", "blocks"):
        st.info("En cada día escribe periodos: 1,2,4-6. * significa toda la jornada; una celda vacía significa sin disponibilidad.")
    st.download_button("Descargar Excel de ejemplo", template(kind), file_name=f"ejemplo_{kind}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"template_{kind}")
    draft_key = f"draft_{kind}_{revision}"
    with st.expander("Importar desde Excel", expanded=not bundle[kind]):
        uploaded = st.file_uploader("Selecciona un archivo .xlsx", type=["xlsx"], key=f"upload_{kind}_{revision}")
        if uploaded is not None:
            try:
                data = uploaded.getvalue()
                sheet = st.selectbox("Hoja", excel_sheets(data), key=f"sheet_{kind}")
                headers, incoming = read_excel(data, sheet)
                st.caption(f"{len(incoming)} registros encontrados. Relaciona las columnas antes de revisar.")
                mapping = suggested_mapping(kind, headers)
                digest = hashlib.sha256(data).hexdigest()[:10]
                columns = st.columns(3)
                for i, field in enumerate(public_columns(kind)):
                    options = ["", *headers]
                    mapping[field] = columns[i % 3].selectbox(field, options, index=options.index(mapping[field]),
                        format_func=lambda value: value or "Sin columna (editar después)", key=f"map_{kind}_{digest}_{sheet}_{field}")
                mode = st.radio("Aplicar importación", ["Agregar y actualizar por matrícula, salón o bloque", "Reemplazar esta tabla"], key=f"import_mode_{kind}")
                if st.button("Llevar a revisión", key=f"review_{kind}"):
                    parsed = map_rows(kind, incoming, mapping, bundle[kind])
                    ids = [catalog_key(kind, r) for r in parsed]
                    if len(ids) != len(set(ids)):
                        raise ValueError("El archivo tiene identificadores repetidos. Corrígelos antes de combinar registros.")
                    if mode.startswith("Agregar"):
                        merged = {r[KEYS[kind]]: r for r in bundle[kind]}
                        merged.update({r[KEYS[kind]]: r for r in parsed})
                        parsed = list(merged.values())
                    st.session_state[draft_key] = parsed
                    st.session_state[f"editor_nonce_{kind}"] = st.session_state.get(f"editor_nonce_{kind}", 0) + 1
                    st.success("Archivo en revisión. Aún no se ha guardado en la base de datos.")
            except (ValueError, KeyError, TypeError, OSError) as exc:
                st.error(str(exc))
    source = st.session_state.get(draft_key, bundle[kind])
    nonce = st.session_state.get(f"editor_nonce_{kind}", 0)
    data = frame(source, public_columns(kind))
    editor_key = f"edit_{kind}_{revision}_{nonce}"
    edited = st.data_editor(data, num_rows="dynamic", hide_index=True, disabled=["_index"],
                           column_config={"_index": None}, width="stretch", key=editor_key, height=390)
    st.caption("Puedes agregar, corregir o eliminar filas. Guarda antes de cambiar de sección; la importación solo se persiste al guardar.")
    left, right = st.columns([1, 3])
    if left.button("Validar y guardar", key=f"save_{kind}", type="primary"):
        if kind in ("teachers", "rooms"):
            # Keep identity on the server: Streamlit preserves row indexes for
            # existing rows but can reuse deleted tail indexes for new rows.
            deleted = set(st.session_state[editor_key].get("deleted_rows", []))
            identities = {i: row["ID"] for i, row in enumerate(source) if i not in deleted}
            edited = edited.copy()
            edited["ID"] = [identities.get(i, "") for i in edited.index]
        rows = canonical_rows(kind, records(edited), bundle[kind])
        errors = validate_table(kind, rows, bundle["settings"])
        if errors:
            show_errors(errors)
        else:
            candidate = deepcopy(bundle)
            candidate[kind] = rows
            if save_data(candidate, f"Actualización de {label.lower()}"):
                st.session_state.pop(draft_key, None)
                st.rerun()
    if right.button("Descartar cambios sin guardar", key=f"discard_{kind}"):
        st.session_state.pop(draft_key, None)
        st.session_state[f"editor_nonce_{kind}"] = nonce + 1
        st.rerun()


def choose_plan():
    history = store.plans()
    if not history:
        st.info("Todavía no hay horarios. Revisa los datos y genera la primera versión.")
        if st.button("Ir a generar"):
            go("Generar")
        return None
    labels = {p["id"]: f"Versión {p['id']} · {p['note']} · datos v{p['revision']}" for p in history}
    pid = st.selectbox("Versión del horario", list(labels), format_func=labels.get, key=f"selected_plan_{st.session_state.nav}")
    return store.get_plan(pid)


def draw_calendar(rows, settings):
    grid = []
    for entry in daily_agenda(settings):
        i = entry["period"]
        pause = entry["kind"] == "break"
        label = f"{time_label(entry['start'])}–{time_label(entry['end'])}"
        row = {"Hora": f"{'Receso' if pause else i} · {label}"}
        for day in DAYS:
            row[day] = "Receso · sin clases" if pause else "\n".join(f"{r['Grupo Inglés']} · E{r['Edificio']}/{r['Salón']}" for r in rows if r["Día"] == day and r["Periodo"] == i)
        grid.append(row)
    table = pd.DataFrame(grid).set_index("Hora")
    styled = table.style.map(lambda v: "background-color:#fff0d5;color:#805715" if v == "Receso · sin clases" else ("background-color:#dcefed;color:#14575c;font-weight:600" if v else "color:#9ba9b5"))
    lines = max((row[day].count("\n") + 1 for row in grid for day in DAYS), default=1)
    st.dataframe(styled, width="stretch", row_height=max(65, 21 * lines + 20))


if "next_page" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("next_page")
if "next_tab" in st.session_state:
    key, label = st.session_state.pop("next_tab")
    st.session_state[key] = label
with st.sidebar:
    st.markdown("### 📚 Inglés")
    st.caption("PLANEACIÓN ACADÉMICA")
    page = st.radio("Navegación", PAGES, key="nav", label_visibility="collapsed")
    st.divider()
    st.caption(f"Datos guardados · versión {revision}")
    st.caption(f"Lunes a viernes · 7 periodos de {bundle['settings']['period_minutes']} min por bloque")
    st.caption(f"Receso: {bundle['settings']['break_start']}–{bundle['settings']['break_end']}")
    st.caption(f"Jornada: {bundle['settings']['start_time']}–{bundle['settings']['end_time']}")
    st.caption("Edificios 1, 2, 3, 4 e Idiomas")
    st.caption("Coordinación local · SQLite")

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon="✅", duration=4)
st.markdown('<div class="eyebrow">COORDINACIÓN DE INGLÉS / HORARIOS Y GRUPOS</div>', unsafe_allow_html=True)

if page == "Vista general":
    st.markdown('<div class="hero"><h2>Un lugar para organizar cada grupo.</h2><p>Reúne alumnos, docentes y espacios. Genera una propuesta de horarios y revisa cada asignación antes de compartirla.</p></div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, kind, name in zip(cols, ["students", "teachers", "rooms", "blocks"], ["Alumnos", "Docentes", "Salones", "Bloques"]):
        col.metric(name, len(bundle[kind]))
    st.write("")
    for col, number, title, detail, target in zip(st.columns(3), ["01", "02", "03"], ["Reúne la información", "Define la semana", "Revisa el resultado"],
        ["Carga los Excel y corrige los registros antes de guardarlos.", "Configura bloques, cupos y disponibilidad de los espacios.", "Comprueba grupos, carga docente y conflictos; exporta los resultados."], ["Datos", "Bloques y reglas", "Generar"]):
        with col.container(border=True):
            st.markdown(f'<div class="step">PASO {number}</div>', unsafe_allow_html=True)
            st.subheader(title)
            st.write(detail)
            if st.button("Abrir " + target.lower(), key=f"start_{number}"):
                go(target)
    st.subheader("Reglas de esta planeación")
    names = {"family": "Familias A, B y C", "cefr": "Niveles A1, A2, B1, B2 y C1", "course": "Curso exacto"}
    st.write(f"**Agrupación:** {names[bundle['settings']['grouping']]} · **Cupo máximo:** {bundle['settings']['max_group']} alumnos · **Horario común:** obligatorio para cada grupo de carrera.")
    st.caption("A1: Prebasic / Basic 1 · A2: Basic 2 / Basic 3 · B1: Intermediate 1 / 2 · B2: Intermediate 3 / 4 · C1: Advanced 1")
    if revision == 0:
        with st.container(border=True):
            st.subheader("Explora con un ejemplo")
            st.write("180 alumnos ficticios, cinco docentes, cinco salones y bloques distribuidos por toda la jornada. Puedes modificarlos o sustituirlos con tus archivos.")
            if st.button("Cargar datos de demostración", type="primary"):
                if save_data(demo_bundle(), "Demostración con datos ficticios"):
                    go("Datos")

elif page == "Datos":
    st.title("Datos de la planeación")
    st.write("Carga, revisa y guarda la información que se usará para formar los grupos.")
    for tab, kind, label in zip(st.tabs(["Alumnos", "Docentes", "Salones"], key="data_tabs", on_change="rerun"), ["students", "teachers", "rooms"], ["Alumnos", "Docentes", "Salones"]):
        with tab:
            table_editor(kind, label)

elif page == "Bloques y reglas":
    st.title("La semana de inglés")
    rules, blocks_tab = st.tabs(["Reglas de asignación", "Bloques semanales"], key="rule_tabs", on_change="rerun")
    with rules:
        s = bundle["settings"]
        with st.form("settings"):
            left, right = st.columns(2)
            names = {"family": "Familias A / B / C", "cefr": "Niveles A1 / A2 / B1 / B2 / C1", "course": "Curso exacto"}
            grouping = left.selectbox("Agrupar alumnos por", list(names), index=list(names).index(s["grouping"]), format_func=names.get)
            maximum = left.slider("Máximo de alumnos por grupo", 25, 35, s["max_group"])
            minimum = left.number_input("Mínimo de alumnos por grupo", min_value=1, max_value=35, value=s["min_group"])
            left.caption("Se permiten grupos pequeños para atender a todos. Puedes exigir un mínimo; si no es viable, el sistema lo indicará.")
            hour, minute = map(int, s["start_time"].split(":"))
            start = right.time_input("Inicio de la jornada", time(hour, minute), step=60)
            end = right.time_input("Fin de la jornada", time.fromisoformat(s["end_time"]), step=60)
            duration = right.number_input("Duración de cada periodo (minutos)", min_value=1, max_value=180, value=s["period_minutes"])
            break_start = right.time_input("Inicio del receso", time.fromisoformat(s["break_start"]), step=60)
            break_end = right.time_input("Fin del receso", time.fromisoformat(s["break_end"]), step=60)
            right.caption("El receso se aplica de lunes a viernes y nunca recibe clases. Si un periodo completo no cabe antes, se mueve al final del receso; no se divide ni se acorta.")
            weekly_minutes = 7 * int(duration)
            right.caption(f"Cada bloque conserva siete periodos: {weekly_minutes // 60} h {weekly_minutes % 60:02} min efectivos de clase. La carga máxima docente se expresa en horas de reloj.")
            right.caption("Los periodos disponibles se calculan hasta el fin de jornada, antes y después del receso. Los minutos sobrantes no forman un periodo parcial.")
            st.info("Todos los alumnos de un mismo grupo de carrera deben compartir el bloque semanal de inglés, aunque pertenezcan a distintos grupos de inglés según su nivel. Esta regla es obligatoria.")
            strict = st.checkbox("Exigir que cada alumno curse inglés en su edificio de origen", value=s["strict_building"])
            st.caption("Con la restricción de edificio desactivada, se busca reducir los cambios de edificio después de minimizar el número de grupos. El docente solo se asigna a sus edificios permitidos.")
            seconds = st.number_input("Tiempo máximo de búsqueda (segundos)", min_value=1, max_value=300, value=s["solver_seconds"])
            if st.form_submit_button("Guardar reglas", type="primary"):
                new_settings = dict(s, grouping=grouping, max_group=maximum, min_group=int(minimum),
                                    start_time=start.strftime("%H:%M"), end_time=end.strftime("%H:%M"), period_minutes=int(duration),
                                    break_start=break_start.strftime("%H:%M"), break_end=break_end.strftime("%H:%M"),
                                    strict_building=strict, solver_seconds=int(seconds))
                errors = validate_settings(new_settings)
                if errors:
                    show_errors(errors)
                else:
                    candidate = deepcopy(bundle)
                    candidate["settings"] = new_settings
                    if save_data(candidate, "Reglas de asignación"):
                        st.rerun()
        st.subheader("Jornada guardada")
        st.caption(f"{period_count(s)} periodos completos por día, de {s['start_time']} a {s['end_time']}.")
        st.dataframe(pd.DataFrame(day_rows(s)), hide_index=True, width="stretch")
        st.caption("Los números de periodo del Excel siguen esta jornada. Al modificar duración o receso, revisa las disponibilidades y revalida los horarios anteriores antes de exportar.")
    with blocks_tab:
        st.write("Un bloque define siete periodos semanales. Varios grupos pueden compartirlo con distintos salones y docentes.")
        st.caption("La generación elige entre estos bloques. Para aprovechar una jornada ampliada, propone nuevos bloques o edita los existentes incluyendo los últimos periodos; revisa después la disponibilidad real.")
        if st.button("Proponer bloques sin superposición"):
            st.session_state[f"draft_blocks_{revision}"] = propose_blocks(period_count(bundle["settings"]))
            st.session_state["editor_nonce_blocks"] = st.session_state.get("editor_nonce_blocks", 0) + 1
            st.success("Propuesta en revisión. Valida y guarda la tabla para usarla.")
        table_editor("blocks", "Bloques")

elif page == "Generar":
    st.title("Generar grupos y horarios")
    st.write("El sistema buscará una asignación para todos los alumnos y comprobará las restricciones antes de guardarla.")
    errors = validate_bundle(bundle)
    if errors:
        show_errors(errors)
    else:
        st.success("Los datos de entrada tienen el formato requerido.")
        cols = st.columns(3)
        cols[0].metric("Alumnos por asignar", len(bundle["students"]))
        cols[1].metric("Bloques disponibles", len(bundle["blocks"]))
        cols[2].metric("Grupos que permiten las horas docentes", f"Hasta {sum(int(t['Horas máximas']) * 60 // block_minutes(bundle['settings']) for t in bundle['teachers'])}")
        st.caption(f"Este máximo suma los grupos completos que cada docente puede cubrir según sus horas semanales. Cada grupo consume {block_minutes(bundle['settings']) / 60:g} horas. Es un límite teórico: disponibilidad, edificios, niveles y salones pueden reducirlo.")
        with st.expander("Disponibilidad compatible por bloque"):
            st.dataframe(pd.DataFrame(resource_summary(bundle)), hide_index=True, width="stretch")
            st.caption("Cada docente y salón de esta tabla cubre los siete periodos del bloque en un edificio permitido. Los conteos no garantizan que puedan usarse todos simultáneamente.")
        last = period_count(bundle["settings"])
        if not any(last in periods(b[d], last) for b in bundle["blocks"] for d in DAYS):
            st.warning(f"Los bloques guardados aún no usan el último periodo ({last}). Para aprovechar el final de jornada, edítalos o propone bloques nuevos en Bloques semanales.")
        st.info("Cada grupo de carrera comparte un único bloque de inglés. El Excel incluirá sus siete periodos reservados para planear después las materias regulares sin cruces.")
        st.caption("Cada ejecución conserva los horarios anteriores. Un límite de tiempo sin solución se informa como búsqueda inconclusa, no como imposibilidad.")
        if st.button("Generar propuesta", type="primary"):
            with st.spinner("Buscando una asignación completa y auditando el resultado…"):
                result = solve(bundle)
                if result.success:
                    issues = audit(bundle, result.payload())
                    if errors_only(issues):
                        st.error("La propuesta no superó la auditoría y no se guardó.")
                        st.dataframe(pd.DataFrame(issues), hide_index=True)
                    else:
                        try:
                            store.save_plan(result.payload(), revision, "Generación automática")
                            st.session_state.pop("generation_failure", None)
                            st.session_state.pop("selected_plan_Resultados", None)
                            flash(result.message)
                            go("Resultados")
                        except ConcurrentEdit as exc:
                            st.error(str(exc))
                else:
                    st.session_state["generation_failure"] = (revision, result.payload())
        failure = st.session_state.get("generation_failure")
        if failure and failure[0] == revision:
            failed = failure[1]
            st.error(failed["message"])
            st.caption(f"Estado: {failed['status']} · Búsqueda: {failed['seconds']:.1f} s")
            if failed["diagnostics"]:
                st.write("Condiciones que impiden esta propuesta o requieren revisión:")
                st.dataframe(pd.DataFrame(failed["diagnostics"])[["Parámetro", "Detalle", "Cómo corregir"]], hide_index=True, width="stretch")
                st.caption("Cuando intervienen varias condiciones, el conflicto corresponde al conjunto; cambiar una sola no garantiza resolverlo.")
            targets = {(item["Sección"], item["Pestaña"]) for item in failed["diagnostics"]}
            targets.update({("Datos", "Docentes"), ("Datos", "Salones"), ("Bloques y reglas", "Bloques semanales"), ("Bloques y reglas", "Reglas de asignación")})
            for target, tab in sorted(targets):
                if st.button(f"Revisar {tab.lower()}", key=f"fix_{target}_{tab}"):
                    go(target, tab)

elif page in ("Resultados", "Auditoría"):
    st.title("Grupos y horarios" if page == "Resultados" else "Auditoría de la planeación")
    selected = choose_plan()
    if selected:
        plan = selected["payload"]
        stale = selected["revision"] != revision
        issues = audit(bundle, plan)
        errors = errors_only(issues)
        if stale:
            st.warning("Los datos cambiaron después de crear esta versión. Revalida los ajustes o genera otra propuesta antes de exportar.")
        if errors:
            st.error(f"Se encontraron {len(errors)} errores con los datos actuales.")
            st.dataframe(pd.DataFrame(issues), hide_index=True, width="stretch")
        elif not stale:
            st.success("Auditoría sin errores: cobertura completa, cupos y asignaciones compatibles.")
        a, b, c, d = st.columns(4)
        a.metric("Alumnos asignados", len({a["student"] for a in plan["assignments"]}))
        b.metric("Grupos de inglés", len(plan["groups"]))
        c.metric("Errores", len(errors))
        d.metric("Avisos", len(issues) - len(errors))

        if page == "Resultados":
            overview, manual, exports = st.tabs(["Por grupo de inglés", "Ajustes manuales", "Exportar"], key="result_tabs", on_change="rerun")
            with overview:
                if not errors:
                    st.caption(f"Cada grupo cursa siete periodos de {bundle['settings']['period_minutes']} min. La columna Horas indica horas de reloj efectivas, sin receso.")
                    summaries = group_summary(bundle, plan)
                    st.dataframe(pd.DataFrame(summaries), hide_index=True, width="stretch")
                    gid = st.selectbox("Ver alumnos y horario del grupo de inglés", ["Todos", *[g["id"] for g in plan["groups"]]])
                    listed = roster(bundle, plan)
                    if gid != "Todos":
                        listed = [a for a in listed if a["Grupo Inglés"] == gid]
                    st.dataframe(pd.DataFrame(listed), hide_index=True, width="stretch")
                    if gid != "Todos":
                        draw_calendar([r for r in schedule_rows(bundle, plan) if r["Grupo Inglés"] == gid], bundle["settings"])
                else:
                    st.caption("Usa los ajustes manuales para corregir las referencias y asignaciones.")
            with manual:
                st.write("Edita bloques, docentes, salones o la asignación de alumnos. Se guardará una nueva versión únicamente si pasa la auditoría.")
                st.caption("Selecciona docentes por nombre y matrícula, y salones por edificio y número. Para agregar o eliminar alumnos, modifica primero el padrón.")
                teachers = {t["ID"]: f"{t['Nombre']} · {t['matricula_docente']}" for t in bundle["teachers"]}
                rooms = {r["ID"]: f"Edificio {r['Edificio']} · Salón {r['Salón']}" for r in bundle["rooms"]}
                # Friendly labels are unique; internal foreign keys never appear in the editor.
                for g in plan["groups"]:
                    teachers.setdefault(g["teacher"], f"Docente eliminado ({len(teachers) + 1})")
                    rooms.setdefault(g["room"], f"Salón eliminado ({len(rooms) + 1})")
                group_df = frame(plan["groups"], ["id", "level", "block", "teacher", "room"])
                group_df["teacher"] = group_df["teacher"].map(teachers)
                group_df["room"] = group_df["room"].map(rooms)
                settings = bundle["settings"]
                level_options = ["A", "B", "C"] if settings["grouping"] == "family" else (["A1", "A2", "B1", "B2", "C1"] if settings["grouping"] == "cefr" else list(LEVELS))
                group_edit = st.data_editor(group_df, num_rows="dynamic", hide_index=True, width="stretch", key=f"manual_groups_{selected['id']}_{revision}",
                    column_config={"id": st.column_config.TextColumn("Grupo Inglés", required=True),
                        "level": st.column_config.SelectboxColumn("Nivel agrupado", options=level_options, required=True),
                        "block": st.column_config.SelectboxColumn("Bloque", options=[b["Bloque"] for b in bundle["blocks"]], required=True),
                        "teacher": st.column_config.SelectboxColumn("Docente · matrícula", options=list(teachers.values()), required=True),
                        "room": st.column_config.SelectboxColumn("Edificio · salón", options=list(rooms.values()), required=True)})
                assignment_df = frame(plan["assignments"], ["student", "group"])
                assignment_edit = st.data_editor(assignment_df, num_rows="dynamic", hide_index=True, width="stretch", height=350, key=f"manual_students_{selected['id']}_{revision}",
                    column_config={"student": st.column_config.TextColumn("Matricula", required=True), "group": st.column_config.TextColumn("Grupo Inglés", required=True)})
                if st.button("Auditar y guardar nueva versión", type="primary"):
                    teacher_ids = {label: key for key, label in teachers.items()}
                    room_ids = {label: key for key, label in rooms.items()}
                    groups = [{**g, "teacher": teacher_ids.get(g["teacher"], ""), "room": room_ids.get(g["room"], "")} for g in records(group_edit)]
                    candidate = dict(plan, groups=groups, assignments=records(assignment_edit), status="MANUAL", message="Versión revisada manualmente")
                    review = audit(bundle, candidate)
                    if errors_only(review):
                        st.error("Los cambios no se guardaron. Corrige los conflictos indicados.")
                        st.dataframe(pd.DataFrame(review), hide_index=True, width="stretch")
                    else:
                        try:
                            store.save_plan(candidate, revision, "Ajuste manual auditado")
                            st.session_state.pop("selected_plan_Resultados", None)
                            flash("Nueva versión guardada y auditada.")
                            st.rerun()
                        except ConcurrentEdit as exc:
                            st.error(str(exc))
            with exports:
                if errors or stale:
                    st.info("La exportación se habilita cuando esta versión está actualizada y sin errores de auditoría.")
                else:
                    st.write("El Excel general incluye el listado con las ocho columnas solicitadas, una hoja por grupo de inglés, horarios, carga docente, auditoría y reservas para las carreras.")
                    st.write("El Excel por grupos de carrera incluye una hoja imprimible por Carrera + Grupo, con su horario común y el nivel, grupo de inglés, docente y salón de cada alumno.")
                    st.write("El PDF incluye el resumen, horarios semanales, carga docente y listas por grupo.")
                    if st.button("Preparar Excel y PDF", type="primary"):
                        with st.spinner("Preparando archivos…"):
                            st.session_state["exports"] = {"key": (selected["id"], revision), "excel": export_excel(bundle, plan), "career_excel": export_career_excel(bundle, plan), "pdf": export_pdf(bundle, plan)}
                    files = st.session_state.get("exports", {})
                    if files.get("key") == (selected["id"], revision):
                        st.download_button("Descargar Excel por grupos de inglés", files["excel"], file_name=f"horarios_ingles_v{selected['id']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        if "career_excel" in files:
                            st.download_button("Descargar Excel por grupos de carrera", files["career_excel"], file_name=f"ingles_por_carrera_v{selected['id']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        st.download_button("Descargar reporte PDF", files["pdf"], file_name=f"reporte_ingles_v{selected['id']}.pdf", mime="application/pdf")

        else:
            if not errors:
                calendar_tab, loads_tab, checks_tab, reservations_tab = st.tabs(["Semana visual", "Carga docente", "Comprobaciones", "Reservas para carreras"])
                with calendar_tab:
                    rows = schedule_rows(bundle, plan)
                    kind = st.radio("Ver horario por", ["Docente", "Salón", "Bloque", "Grupo de inglés", "Grupo de carrera"],
                                    horizontal=True, key="audit_calendar_kind")
                    if kind == "Docente":
                        options = {t["ID"]: f"{t['Nombre']} · {t['matricula_docente']}" for t in bundle["teachers"]}
                        choice = st.selectbox("Docente", list(options), format_func=options.get)
                        ids = {g["id"] for g in plan["groups"] if g["teacher"] == choice}
                    elif kind == "Salón":
                        options = {r["ID"]: f"{r['Salón']} · Edificio {r['Edificio']}" for r in bundle["rooms"]}
                        choice = st.selectbox("Salón", list(options), format_func=options.get)
                        ids = {g["id"] for g in plan["groups"] if g["room"] == choice}
                    elif kind == "Bloque":
                        choice = st.selectbox("Bloque", [b["Bloque"] for b in bundle["blocks"]])
                        ids = {g["id"] for g in plan["groups"] if g["block"] == choice}
                    elif kind == "Grupo de inglés":
                        options = {g["id"]: f"{g['id']} · Nivel {g['level']} · {g['block']}" for g in plan["groups"]}
                        choice = st.selectbox("Grupo de inglés", sorted(options), format_func=options.get,
                                              key="audit_english_group")
                        ids = {choice}
                    else:
                        career = st.selectbox("Carrera", sorted({a["Carrera"] for a in bundle["students"]}),
                                              key="audit_career")
                        cohort = st.selectbox("Grupo de carrera", sorted({a["Grupo"] for a in bundle["students"] if a["Carrera"] == career}),
                                              key="audit_career_group")
                        members = {a["Matricula"] for a in bundle["students"] if (a["Carrera"], a["Grupo"]) == (career, cohort)}
                        ids = {a["group"] for a in plan["assignments"] if a["student"] in members}
                        st.caption("Horario común del grupo de carrera. Cada renglón dentro de una clase muestra uno de sus grupos de inglés y su edificio/salón.")
                    draw_calendar([r for r in rows if r["Grupo Inglés"] in ids], bundle["settings"])
                with loads_tab:
                    st.caption("Carga expresada en horas de reloj. El receso no suma tiempo de clase.")
                    loads = pd.DataFrame(teacher_load(bundle, plan))
                    st.dataframe(loads, hide_index=True, width="stretch")
                    st.bar_chart(loads, x="Docente", y=["Horas asignadas", "Horas libres"], color=["#167C80", "#CBD7E4"])
                with checks_tab:
                    checks = ["Cada alumno tiene exactamente una asignación", "Nivel compatible con su grupo de inglés", "Siete periodos completos en cada bloque", "Ninguna clase invade el receso",
                              "Cupos de grupo y salón respetados", "Docentes y salones sin superposición", "Disponibilidad y carga docente respetadas",
                              "Edificios permitidos y límites de jornada", "Bloques fijos respetados", "Mismo horario de inglés para todos los alumnos de cada grupo de carrera"]
                    st.dataframe(pd.DataFrame({"Comprobación": checks, "Resultado": ["Cumple"] * len(checks)}), hide_index=True, width="stretch")
                    if issues:
                        st.dataframe(pd.DataFrame(issues), hide_index=True, width="stretch")
                with reservations_tab:
                    st.info("Cada combinación de Carrera + Grupo comparte estos siete periodos de inglés. Reserva ese horario al planear sus materias regulares. Esta tabla se incluye en el Excel.")
                    st.dataframe(pd.DataFrame(reservations(bundle, plan)), hide_index=True, width="stretch")

st.divider()
st.caption("Planeación de inglés · Datos guardados localmente · Los cambios se aplican al pulsar Guardar")
