from __future__ import annotations

import hashlib
import os
from copy import deepcopy
from datetime import time
from pathlib import Path

import pandas as pd
import streamlit as st

from ingles.audit import audit, errors_only
from ingles.domain import (BUILDINGS, DAYS, KEYS, LEVELS, SCHEMAS, canonical_rows, demo_bundle,
                           periods, propose_blocks, validate_bundle, validate_settings, validate_table)
from ingles.exchange import (excel_sheets, export_excel, group_summary, map_rows, period_label,
                             read_excel, reservations, roster, schedule_rows, suggested_mapping,
                             teacher_load, template_excel)
from ingles.reports import export_pdf
from ingles.scheduler import solve
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


def go(page):
    st.session_state["next_page"] = page
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
        st.caption("Edificios: 1,2,3,4,Idiomas o * para todos. Horas máximas: carga semanal disponible para inglés.")
    elif kind == "rooms":
        st.caption("Cada salón requiere un ID único y su capacidad. El mismo número de salón puede existir en edificios diferentes.")
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
                for i, field in enumerate(SCHEMAS[kind]):
                    options = ["", *headers]
                    mapping[field] = columns[i % 3].selectbox(field, options, index=options.index(mapping[field]),
                        format_func=lambda value: value or "Sin columna (editar después)", key=f"map_{kind}_{digest}_{sheet}_{field}")
                mode = st.radio("Aplicar importación", ["Agregar y actualizar por identificador", "Reemplazar esta tabla"], key=f"import_mode_{kind}")
                if st.button("Llevar a revisión", key=f"review_{kind}"):
                    parsed = map_rows(kind, incoming, mapping)
                    ids = [r[KEYS[kind]] for r in parsed]
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
    edited = st.data_editor(frame(source, SCHEMAS[kind]), num_rows="dynamic", hide_index=True,
                           width="stretch", key=f"edit_{kind}_{revision}_{nonce}", height=390)
    st.caption("Puedes agregar, corregir o eliminar filas. Guarda antes de cambiar de sección; la importación solo se persiste al guardar.")
    left, right = st.columns([1, 3])
    if left.button("Validar y guardar", key=f"save_{kind}", type="primary"):
        rows = canonical_rows(kind, records(edited))
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
    for i in range(1, settings["periods_per_day"] + 1):
        row = {"Hora": f"{i} · {period_label(settings, i)}"}
        for day in DAYS:
            row[day] = "\n".join(f"{r['Grupo Inglés']} · E{r['Edificio']}/{r['Salón']}" for r in rows if r["Día"] == day and r["Periodo"] == i)
        grid.append(row)
    table = pd.DataFrame(grid).set_index("Hora")
    styled = table.style.map(lambda v: "background-color:#dcefed;color:#14575c;font-weight:600" if v else "color:#9ba9b5")
    st.dataframe(styled, width="stretch", row_height=65)


if "next_page" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("next_page")
with st.sidebar:
    st.markdown("### 📚 Inglés")
    st.caption("PLANEACIÓN ACADÉMICA")
    page = st.radio("Navegación", PAGES, key="nav", label_visibility="collapsed")
    st.divider()
    st.caption(f"Datos guardados · versión {revision}")
    st.caption("Lunes a viernes · 7 horas por bloque")
    st.caption("Edificios 1, 2, 3, 4 e Idiomas")
    st.caption("Coordinación local · SQLite")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))
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
            st.write("180 alumnos ficticios, cinco docentes, cinco salones y tres bloques. Puedes modificarlos o sustituirlos con tus archivos.")
            if st.button("Cargar datos de demostración", type="primary"):
                if save_data(demo_bundle(), "Demostración con datos ficticios"):
                    go("Datos")

elif page == "Datos":
    st.title("Datos de la planeación")
    st.write("Carga, revisa y guarda la información que se usará para formar los grupos.")
    for tab, kind, label in zip(st.tabs(["Alumnos", "Docentes", "Salones"]), ["students", "teachers", "rooms"], ["Alumnos", "Docentes", "Salones"]):
        with tab:
            table_editor(kind, label)

elif page == "Bloques y reglas":
    st.title("La semana de inglés")
    rules, blocks_tab = st.tabs(["Reglas de asignación", "Bloques semanales"])
    with rules:
        s = bundle["settings"]
        with st.form("settings"):
            left, right = st.columns(2)
            names = {"family": "Familias A / B / C", "cefr": "Niveles A1 / A2 / B1 / B2 / C1", "course": "Curso exacto"}
            grouping = left.selectbox("Agrupar alumnos por", list(names), index=list(names).index(s["grouping"]), format_func=names.get)
            maximum = left.slider("Máximo de alumnos por grupo", 25, 30, s["max_group"])
            minimum = left.number_input("Mínimo de alumnos por grupo", min_value=1, max_value=30, value=s["min_group"])
            left.caption("Se permiten grupos pequeños para atender a todos. Puedes exigir un mínimo; si no es viable, el sistema lo indicará.")
            count = right.number_input("Periodos por día", min_value=1, max_value=16, value=s["periods_per_day"])
            hour, minute = map(int, s["start_time"].split(":"))
            start = right.time_input("Inicio de la jornada", time(hour, minute))
            right.caption("Cada periodo dura 60 minutos. Siete periodos equivalen a siete horas semanales; jornada continua sin recesos configurados.")
            transfer = right.number_input("Periodos libres para traslado entre edificios", min_value=0, max_value=4, value=s["transfer_periods"])
            st.info("Todos los alumnos de un mismo grupo de carrera deben compartir el bloque semanal de inglés, aunque pertenezcan a distintos grupos de inglés según su nivel. Esta regla es obligatoria.")
            strict = st.checkbox("Exigir que cada alumno curse inglés en su edificio de origen", value=s["strict_building"])
            st.caption("Con la restricción de edificio desactivada, se busca reducir los cambios de edificio después de minimizar el número de grupos. El docente solo se asigna a sus edificios permitidos.")
            seconds = st.number_input("Tiempo máximo de búsqueda (segundos)", min_value=1, max_value=300, value=s["solver_seconds"])
            if st.form_submit_button("Guardar reglas", type="primary"):
                new_settings = dict(s, grouping=grouping, max_group=maximum, min_group=int(minimum), periods_per_day=int(count),
                                    start_time=start.strftime("%H:%M"), transfer_periods=int(transfer),
                                    strict_building=strict, solver_seconds=int(seconds))
                errors = validate_settings(new_settings)
                if errors:
                    show_errors(errors)
                else:
                    candidate = deepcopy(bundle)
                    candidate["settings"] = new_settings
                    if save_data(candidate, "Reglas de asignación"):
                        st.rerun()
    with blocks_tab:
        st.write("Un bloque define siete periodos semanales. Varios grupos pueden compartirlo con distintos salones y docentes.")
        st.caption("La generación elige entre estos bloques. Las plantillas automáticas distribuyen las horas disponibles; revísalas frente a la disponibilidad real.")
        if st.button("Proponer bloques sin superposición"):
            st.session_state[f"draft_blocks_{revision}"] = propose_blocks(bundle["settings"]["periods_per_day"])
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
        cols[2].metric("Capacidad docente", f"{sum(int(t['Horas máximas']) // 7 for t in bundle['teachers'])} grupos")
        st.info("Cada grupo de carrera comparte un único bloque de inglés. El Excel incluirá sus siete horas reservadas para planear después las materias regulares sin cruces.")
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
                            st.session_state.pop("selected_plan_Resultados", None)
                            flash(result.message)
                            go("Resultados")
                        except ConcurrentEdit as exc:
                            st.error(str(exc))
                else:
                    st.error(result.message)
                    st.caption(f"Estado: {result.status} · Búsqueda: {result.seconds:.1f} s")

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
        b.metric("Grupos", len(plan["groups"]))
        c.metric("Errores", len(errors))
        d.metric("Avisos", len(issues) - len(errors))

        if page == "Resultados":
            overview, manual, exports = st.tabs(["Por grupo", "Ajustes manuales", "Exportar"])
            with overview:
                if not errors:
                    summaries = group_summary(bundle, plan)
                    st.dataframe(pd.DataFrame(summaries), hide_index=True, width="stretch")
                    gid = st.selectbox("Ver alumnos y horario de", ["Todos", *[g["id"] for g in plan["groups"]]])
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
                st.caption("Las claves de docentes y salones aparecen en la sección Datos. Para agregar o eliminar alumnos, modifica primero el padrón.")
                group_df = frame(plan["groups"], ["id", "level", "block", "teacher", "room"])
                settings = bundle["settings"]
                level_options = ["A", "B", "C"] if settings["grouping"] == "family" else (["A1", "A2", "B1", "B2", "C1"] if settings["grouping"] == "cefr" else list(LEVELS))
                group_edit = st.data_editor(group_df, num_rows="dynamic", hide_index=True, width="stretch", key=f"manual_groups_{selected['id']}_{revision}",
                    column_config={"id": st.column_config.TextColumn("Grupo Inglés", required=True),
                        "level": st.column_config.SelectboxColumn("Nivel agrupado", options=level_options, required=True),
                        "block": st.column_config.SelectboxColumn("Bloque", options=[b["Bloque"] for b in bundle["blocks"]], required=True),
                        "teacher": st.column_config.SelectboxColumn("ID docente", options=[t["ID"] for t in bundle["teachers"]], required=True),
                        "room": st.column_config.SelectboxColumn("ID salón", options=[r["ID"] for r in bundle["rooms"]], required=True)})
                assignment_df = frame(plan["assignments"], ["student", "group"])
                assignment_edit = st.data_editor(assignment_df, num_rows="dynamic", hide_index=True, width="stretch", height=350, key=f"manual_students_{selected['id']}_{revision}",
                    column_config={"student": st.column_config.TextColumn("Matricula", required=True), "group": st.column_config.TextColumn("Grupo Inglés", required=True)})
                if st.button("Auditar y guardar nueva versión", type="primary"):
                    candidate = dict(plan, groups=records(group_edit), assignments=records(assignment_edit), status="MANUAL", message="Versión revisada manualmente")
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
                    st.write("El Excel incluye el listado con las ocho columnas solicitadas, una hoja por grupo, horarios, carga docente, auditoría y reservas para las carreras.")
                    st.write("El PDF incluye el resumen, horarios semanales, carga docente y listas por grupo.")
                    if st.button("Preparar Excel y PDF", type="primary"):
                        with st.spinner("Preparando archivos…"):
                            st.session_state["exports"] = {"key": (selected["id"], revision), "excel": export_excel(bundle, plan), "pdf": export_pdf(bundle, plan)}
                    files = st.session_state.get("exports", {})
                    if files.get("key") == (selected["id"], revision):
                        st.download_button("Descargar Excel", files["excel"], file_name=f"horarios_ingles_v{selected['id']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        st.download_button("Descargar reporte PDF", files["pdf"], file_name=f"reporte_ingles_v{selected['id']}.pdf", mime="application/pdf")

        else:
            if not errors:
                calendar_tab, loads_tab, checks_tab, reservations_tab = st.tabs(["Semana visual", "Carga docente", "Comprobaciones", "Reservas para carreras"])
                with calendar_tab:
                    rows = schedule_rows(bundle, plan)
                    kind = st.radio("Ver horario por", ["Docente", "Salón", "Bloque"], horizontal=True)
                    if kind == "Docente":
                        options = {t["ID"]: t["Nombre"] for t in bundle["teachers"]}
                        choice = st.selectbox("Docente", list(options), format_func=lambda k: f"{options[k]} ({k})")
                        ids = {g["id"] for g in plan["groups"] if g["teacher"] == choice}
                    elif kind == "Salón":
                        options = {r["ID"]: f"{r['Salón']} · Edificio {r['Edificio']}" for r in bundle["rooms"]}
                        choice = st.selectbox("Salón", list(options), format_func=options.get)
                        ids = {g["id"] for g in plan["groups"] if g["room"] == choice}
                    else:
                        choice = st.selectbox("Bloque", [b["Bloque"] for b in bundle["blocks"]])
                        ids = {g["id"] for g in plan["groups"] if g["block"] == choice}
                    draw_calendar([r for r in rows if r["Grupo Inglés"] in ids], bundle["settings"])
                with loads_tab:
                    loads = pd.DataFrame(teacher_load(bundle, plan))
                    st.dataframe(loads, hide_index=True, width="stretch")
                    st.bar_chart(loads, x="Docente", y=["Horas asignadas", "Horas libres"], color=["#167C80", "#CBD7E4"])
                with checks_tab:
                    checks = ["Cada alumno tiene exactamente una asignación", "Nivel compatible con su grupo de inglés", "Siete horas en cada bloque",
                              "Cupos de grupo y salón respetados", "Docentes y salones sin superposición", "Disponibilidad y carga docente respetadas",
                              "Edificios permitidos y tiempo de traslado", "Bloques fijos respetados", "Mismo horario de inglés para todos los alumnos de cada grupo de carrera"]
                    st.dataframe(pd.DataFrame({"Comprobación": checks, "Resultado": ["Cumple"] * len(checks)}), hide_index=True, width="stretch")
                    if issues:
                        st.dataframe(pd.DataFrame(issues), hide_index=True, width="stretch")
                with reservations_tab:
                    st.info("Cada combinación de Carrera + Grupo comparte estas siete horas de inglés. Reserva ese horario al planear sus materias regulares. Esta tabla se incluye en el Excel.")
                    st.dataframe(pd.DataFrame(reservations(bundle, plan)), hide_index=True, width="stretch")

st.divider()
st.caption("Planeación de inglés · Datos guardados localmente · Los cambios se aplican al pulsar Guardar")
