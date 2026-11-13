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
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* Base typography */
html, body, [class*="css"], .stMarkdown, p, span, label, input, button {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
}

/* Page Layout */
.block-container {
    padding-top: 1.8rem !important;
    padding-bottom: 4rem !important;
    max-width: 1440px !important;
}

/* Headings */
h1 {
    font-weight: 800 !important;
    letter-spacing: -0.04em !important;
    color: #0F172A !important;
    font-size: 2.15rem !important;
    margin-bottom: 0.35rem !important;
}

h2 {
    font-weight: 700 !important;
    letter-spacing: -0.03em !important;
    color: #1E293B !important;
    font-size: 1.55rem !important;
}

h3 {
    font-weight: 700 !important;
    letter-spacing: -0.025em !important;
    color: #334155 !important;
    font-size: 1.22rem !important;
}

/* Header bar */
.top-header-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 14px;
    padding: 12px 20px;
    margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.top-brand {
    display: inline-flex;
    align-items: center;
    gap: 10px;
}

.top-brand-icon {
    width: 32px;
    height: 32px;
    background: linear-gradient(135deg, #0F766E, #0D9488);
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    color: white;
    box-shadow: 0 2px 6px rgba(15, 118, 110, 0.2);
}

.top-brand-text {
    font-size: 0.82rem;
    font-weight: 800;
    letter-spacing: 0.1em;
    color: #0F766E;
    text-transform: uppercase;
}

.status-badge-live {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    background: #F0FDF4;
    border: 1px solid #BBF7D0;
    border-radius: 9999px;
    font-size: 0.76rem;
    font-weight: 700;
    color: #166534;
}

.status-pulse {
    width: 8px;
    height: 8px;
    background: #22C55E;
    border-radius: 50%;
    box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.25);
}

/* Hero Section */
.hero-card {
    position: relative;
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 55%, #0F766E 100%);
    border-radius: 20px;
    padding: 36px 42px;
    margin: 8px 0 26px;
    color: #FFFFFF;
    box-shadow: 0 14px 34px -10px rgba(15, 23, 42, 0.3);
    overflow: hidden;
}

.hero-card::after {
    content: '';
    position: absolute;
    top: -60px;
    right: -60px;
    width: 240px;
    height: 240px;
    background: radial-gradient(circle, rgba(20, 184, 166, 0.25) 0%, rgba(20, 184, 166, 0) 70%);
    border-radius: 50%;
    pointer-events: none;
}

.hero-tag {
    display: inline-block;
    padding: 4px 12px;
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 9999px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: #99F6E4;
    text-transform: uppercase;
    margin-bottom: 12px;
    backdrop-filter: blur(8px);
}

.hero-card h2 {
    color: #FFFFFF !important;
    font-size: 2.15rem !important;
    font-weight: 800 !important;
    margin: 0 0 10px 0 !important;
    letter-spacing: -0.04em !important;
}

.hero-card p {
    color: #E2E8F0 !important;
    font-size: 1.02rem !important;
    line-height: 1.55 !important;
    margin: 0 !important;
    max-width: 820px !important;
}

/* Metric Cards */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 16px !important;
    padding: 20px 22px !important;
    box-shadow: 0 2px 6px -1px rgba(0, 0, 0, 0.04), 0 1px 3px -1px rgba(0, 0, 0, 0.02) !important;
    transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
    position: relative !important;
    overflow: hidden !important;
}

[data-testid="stMetric"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 10px 22px -4px rgba(15, 23, 42, 0.08) !important;
    border-color: #CBD5E1 !important;
}

[data-testid="stMetric"]::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, #0F766E, #14B8A6);
}

[data-testid="stMetricLabel"] {
    font-size: 0.78rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.06em !important;
    color: #64748B !important;
    text-transform: uppercase !important;
}

[data-testid="stMetricValue"] {
    font-size: 1.95rem !important;
    font-weight: 800 !important;
    color: #0F172A !important;
    letter-spacing: -0.04em !important;
    margin-top: 4px !important;
}

/* Step badges */
.step-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    background: #F0FDFA;
    color: #0F766E;
    border: 1px solid #CCFBF1;
    border-radius: 8px;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    margin-bottom: 10px;
}

/* Sidebar Custom Styling */
[data-testid="stSidebar"] {
    background: #F8FAFC !important;
    border-right: 1px solid #E2E8F0 !important;
}

.sidebar-header-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 4px 18px;
    margin-bottom: 14px;
    border-bottom: 1px solid #E2E8F0;
}

.sidebar-icon-box {
    width: 44px;
    height: 44px;
    background: linear-gradient(135deg, #0F766E 0%, #0369A1 100%);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    color: white;
    box-shadow: 0 4px 12px rgba(15, 118, 110, 0.25);
}

.sidebar-app-name {
    font-size: 1.08rem;
    font-weight: 800;
    color: #0F172A;
    letter-spacing: -0.03em;
    line-height: 1.2;
}

.sidebar-app-sub {
    font-size: 0.68rem;
    font-weight: 700;
    color: #0F766E;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-top: 3px;
}

.sidebar-info-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 14px;
    padding: 14px 16px;
    margin-top: 14px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.sidebar-info-title {
    font-size: 0.72rem;
    font-weight: 800;
    color: #475569;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.sidebar-info-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid #F1F5F9;
    font-size: 0.78rem;
    color: #475569;
}

.sidebar-info-row:last-child {
    border-bottom: none;
}

.sidebar-info-row strong {
    color: #0F172A;
    font-weight: 600;
}

/* Sidebar Radio Navigation */
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 9px 14px;
    border-radius: 10px;
    background: transparent;
    border: 1px solid transparent;
    margin: 2px 0;
    font-size: 0.88rem;
    font-weight: 500;
    color: #334155;
    transition: all 0.15s ease;
    cursor: pointer;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: #FFFFFF;
    border-color: #E2E8F0;
    color: #0F172A;
}

/* Buttons */
div.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    padding: 0.48rem 1.15rem !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    letter-spacing: -0.01em !important;
}

div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #0F766E 0%, #0D9488 100%) !important;
    border: none !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 12px rgba(15, 118, 110, 0.25) !important;
}

div.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 18px rgba(15, 118, 110, 0.35) !important;
}

div.stButton > button[kind="secondary"], div.stButton > button:not([kind="primary"]) {
    background: #FFFFFF !important;
    border: 1px solid #CBD5E1 !important;
    color: #334155 !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04) !important;
}

div.stButton > button[kind="secondary"]:hover, div.stButton > button:not([kind="primary"]):hover {
    background: #F8FAFC !important;
    border-color: #94A3B8 !important;
    color: #0F172A !important;
    transform: translateY(-1px) !important;
}

div.stDownloadButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    padding: 0.48rem 1.15rem !important;
    border: 1px solid #CBD5E1 !important;
    background: #FFFFFF !important;
    color: #0F766E !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04) !important;
    transition: all 0.2s ease !important;
}

div.stDownloadButton > button:hover {
    background: #F0FDFA !important;
    border-color: #0F766E !important;
    transform: translateY(-1px) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: #F1F5F9;
    padding: 5px;
    border-radius: 12px;
    border: 1px solid #E2E8F0;
    margin-bottom: 22px;
}

.stTabs [data-baseweb="tab"] {
    height: 38px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.86rem;
    color: #64748B;
    border: none !important;
    background-color: transparent;
    padding: 0 16px;
    transition: all 0.15s ease;
}

.stTabs [data-baseweb="tab"]:hover {
    color: #0F172A;
    background-color: rgba(255, 255, 255, 0.6);
}

.stTabs [aria-selected="true"] {
    background-color: #FFFFFF !important;
    color: #0F766E !important;
    font-weight: 700 !important;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06) !important;
}

/* Form styling */
[data-testid="stForm"] {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 2px 6px -1px rgba(0, 0, 0, 0.03);
}

/* Dataframe containers */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #E2E8F0;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

/* Expanders */
[data-testid="stExpander"] {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
    margin: 12px 0;
}

[data-testid="stExpander"] details summary {
    font-weight: 600;
    color: #0F172A;
    border-radius: 12px;
}

/* Alerts */
[data-testid="stAlert"] {
    border-radius: 12px !important;
    border: 1px solid transparent !important;
    padding: 14px 18px !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
}
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
    styled = table.style.map(lambda v: "background-color:#FEF3C7;color:#92400E;font-weight:600" if v == "Receso · sin clases" else ("background-color:#CCFBF1;color:#0F766E;font-weight:700" if v else "color:#94A3B8"))
    lines = max((row[day].count("\n") + 1 for row in grid for day in DAYS), default=1)
    st.dataframe(styled, width="stretch", row_height=max(65, 21 * lines + 20))


if "next_page" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("next_page")
if "next_tab" in st.session_state:
    key, label = st.session_state.pop("next_tab")
    st.session_state[key] = label
with st.sidebar:
    st.markdown("""
    <div class="sidebar-header-card">
        <div class="sidebar-icon-box">📚</div>
        <div>
            <div class="sidebar-app-name">Coordinación</div>
            <div class="sidebar-app-sub">Planeación de Inglés</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    page = st.radio("Navegación", PAGES, key="nav", label_visibility="collapsed")
    st.markdown(f"""
    <div class="sidebar-info-card">
        <div class="sidebar-info-title">
            <span>Estado del Sistema</span>
            <span style="color:#0F766E;">● Activo</span>
        </div>
        <div class="sidebar-info-row">
            <span>Versión de datos:</span>
            <strong>v{revision}</strong>
        </div>
        <div class="sidebar-info-row">
            <span>Bloque semanal:</span>
            <strong>7 periodos ({bundle['settings']['period_minutes']} min)</strong>
        </div>
        <div class="sidebar-info-row">
            <span>Receso:</span>
            <strong>{bundle['settings']['break_start']} – {bundle['settings']['break_end']}</strong>
        </div>
        <div class="sidebar-info-row">
            <span>Jornada:</span>
            <strong>{bundle['settings']['start_time']} – {bundle['settings']['end_time']}</strong>
        </div>
        <div class="sidebar-info-row">
            <span>Espacios:</span>
            <strong>Edif. 1-4 e Idiomas</strong>
        </div>
        <div class="sidebar-info-row">
            <span>Base de datos:</span>
            <strong>SQLite Local</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon="✅", duration=4)

st.markdown(f"""
<div class="top-header-bar">
    <div class="top-brand">
        <div class="top-brand-icon">📚</div>
        <span class="top-brand-text">Coordinación de Inglés · Horarios y Grupos</span>
    </div>
    <div class="status-badge-live">
        <div class="status-pulse"></div>
        <span>Datos v{revision} · Base activa</span>
    </div>
</div>
""", unsafe_allow_html=True)

if page == "Vista general":
    st.markdown("""
    <div class="hero-card">
        <div class="hero-tag">✨ Sistema Inteligente de Horarios</div>
        <h2>Un lugar para organizar cada grupo.</h2>
        <p>Reúne alumnos, docentes y espacios. Genera una propuesta de horarios y revisa cada asignación antes de compartirla.</p>
    </div>
    """, unsafe_allow_html=True)
    cols = st.columns(4)
    for col, kind, name in zip(cols, ["students", "teachers", "rooms", "blocks"], ["Alumnos", "Docentes", "Salones", "Bloques"]):
        col.metric(name, len(bundle[kind]))
    st.write("")
    for col, number, title, detail, target in zip(st.columns(3), ["01", "02", "03"], ["Reúne la información", "Define la semana", "Revisa el resultado"],
        ["Carga los Excel y corrige los registros antes de guardarlos.", "Configura bloques, cupos y disponibilidad de los espacios.", "Comprueba grupos, carga docente y conflictos; exporta los resultados."], ["Datos", "Bloques y reglas", "Generar"]):
        with col.container(border=True):
            st.markdown(f'<div class="step-badge">PASO {number}</div>', unsafe_allow_html=True)
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
                    st.bar_chart(loads, x="Docente", y=["Horas asignadas", "Horas libres"], color=["#0F766E", "#CBD5E1"])
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
