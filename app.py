from __future__ import annotations

import base64
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

st.set_page_config(page_title="Inglés · Planeación académica", page_icon=":material/school:", layout="wide")
ROOT = Path(__file__).resolve().parent
store = Store(os.environ.get("INGLES_DB_PATH", str(ROOT / "data" / "ingles.sqlite3")))
bundle, revision = store.load()
PAGES = ["Vista general", "Datos", "Bloques y reglas", "Generar", "Resultados", "Auditoría"]
PAGE_ICONS = {"Vista general": "home", "Datos": "database", "Bloques y reglas": "tune", "Generar": "bolt", "Resultados": "calendar_month", "Auditoría": "fact_check"}

# Paleta del calendario: un color suave por grupo de inglés
CAL_COLORS = [("#DDF3E6", "#256B4F"), ("#E8F3DC", "#4A6B1F"), ("#D5EEE9", "#1F6B62"), ("#EEF5DF", "#5A6B1C"),
              ("#E0F0E4", "#2F6B45"), ("#D6F0E8", "#1E6B57"), ("#E5EFD6", "#556B2F"), ("#CFE9DA", "#1F5E43")]

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Instrument+Sans:wght@400;500;600;700&display=swap');

:root {
    --ink: #14213D;
    --ink-2: #3B4A66;
    --muted: #5B6678;
    --paper: #F4F6FA;
    --card: #FFFFFF;
    --line: #E1E6EF;
    --blue: #37866A;
    --blue-dark: #2D6F58;
    --blue-soft: #E3F4EC;
    --amber: #FFB703;
    --amber-soft: #FFF4D6;
    --green: #12805C;
    --green-soft: #DDF5EA;
    --radius: 14px;
    --shadow: 0 1px 2px rgba(20, 33, 61, .05), 0 6px 18px -8px rgba(20, 33, 61, .10);
}

/* ---------- Tipografía (sin tocar los iconos de Streamlit) ---------- */
html, body, .stApp, .stMarkdown, [data-testid="stMarkdownContainer"] p, label, input, textarea, button, li,
[data-testid="stCaptionContainer"], [data-testid="stMetricLabel"], [data-baseweb="tab"] {
    font-family: 'Instrument Sans', -apple-system, 'Segoe UI', Roboto, sans-serif !important;
}
h1, h2, h3, .page-head h1, .sb-name {
    font-family: 'Bricolage Grotesque', 'Instrument Sans', sans-serif !important;
    color: var(--ink) !important;
    letter-spacing: -0.02em !important;
}
h1 { font-weight: 800 !important; font-size: 2.2rem !important; }
h2 { font-weight: 700 !important; font-size: 1.5rem !important; }
h3 { font-weight: 700 !important; font-size: 1.15rem !important; }

/* ---------- Lienzo ---------- */
.stApp { background: var(--paper); }
[data-testid="stHeader"] { background: transparent; }
footer, #MainMenu { visibility: hidden; }
.block-container { padding-top: 1.6rem !important; padding-bottom: 4rem !important; max-width: 1360px !important; }
hr { border-color: var(--line) !important; margin: 2.2rem 0 1rem !important; }
[data-testid="stCaptionContainer"] { color: var(--muted) !important; line-height: 1.5; }

/* ---------- Barra superior ---------- */
.topbar {
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
    background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 10px 18px; margin-bottom: 22px; box-shadow: var(--shadow);
}
.topbar-left { display: flex; align-items: center; gap: 10px; color: var(--ink-2); font-weight: 600; font-size: .92rem; }
.topbar-mark { width: 30px; height: 30px; border-radius: 8px; background: var(--ink); display: grid; place-items: center; font-size: 15px; }
.topbar-sep { color: var(--line); }
.topbar-page { color: var(--ink); font-weight: 700; }
.pill {
    display: inline-flex; align-items: center; gap: 7px; padding: 5px 12px; border-radius: 999px;
    background: var(--green-soft); color: var(--green); font-weight: 600; font-size: .8rem;
}
.pill i { width: 7px; height: 7px; border-radius: 50%; background: var(--green); display: inline-block; }

/* ---------- Encabezado de página ---------- */
.page-head { display: flex; align-items: center; gap: 16px; margin: 4px 0 22px; }
.page-head-icon {
    width: 52px; height: 52px; flex: none; border-radius: 14px; background: var(--blue-soft);
    display: grid; place-items: center; font-size: 26px;
}
.page-head h1 { margin: 0 !important; padding: 0 !important; line-height: 1.1 !important; }
.page-head p { margin: 4px 0 0 !important; color: var(--muted); font-size: 1rem; max-width: 760px; }

/* ---------- Métricas ---------- */
[data-testid="stMetric"] {
    background: var(--card) !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
    padding: 18px 20px !important; box-shadow: var(--shadow) !important; border-left: 4px solid var(--blue) !important;
}
[data-testid="stMetricLabel"] { color: var(--muted) !important; font-weight: 600 !important; font-size: .88rem !important; }
[data-testid="stMetricValue"] {
    font-family: 'Bricolage Grotesque', sans-serif !important; color: var(--ink) !important;
    font-weight: 800 !important; font-size: 2.1rem !important; letter-spacing: -0.03em !important;
}

/* ---------- Tarjetas con borde (contenedores) ---------- */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--card); border-color: var(--line) !important; border-radius: var(--radius) !important; box-shadow: var(--shadow);
}
.step-num {
    width: 30px; height: 30px; border-radius: 50%; background: var(--ink); color: #fff; display: grid; place-items: center;
    font-family: 'Bricolage Grotesque', sans-serif; font-weight: 700; font-size: .95rem; margin-bottom: 8px;
}

/* ---------- Reglas de la planeación ---------- */
.rules-row { display: flex; flex-wrap: wrap; gap: 10px; margin: 6px 0 10px; }
.rule-chip { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 10px 16px; }
.rule-chip small { display: block; color: var(--muted); font-size: .78rem; font-weight: 500; }
.rule-chip b { color: var(--ink); font-size: .98rem; }

/* ---------- Barra lateral ---------- */
[data-testid="stSidebar"] { background: var(--ink) !important; border-right: none !important; }
[data-testid="stSidebar"] * { color: #D6DEEE; }
.sb-head { display: flex; align-items: center; gap: 12px; padding: 6px 2px 18px; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,.1); }
.sb-logo { width: 42px; height: 42px; border-radius: 12px; background: var(--amber); display: grid; place-items: center; font-size: 21px; }
.sb-name { color: #fff !important; font-size: 1.12rem; font-weight: 800; line-height: 1.15; }
.sb-sub { color: #9FB0CF !important; font-size: .82rem; margin-top: 2px; }
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 9px 14px; border-radius: 10px; margin: 2px 0; width: 100%; transition: background .15s ease; cursor: pointer;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label > div:first-child { display: none; }
[data-testid="stSidebar"] [data-testid="stRadio"] label p { color: #C3CEE3 !important; font-weight: 500; font-size: .95rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background: rgba(255,255,255,.07); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) { background: var(--blue); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p { color: #fff !important; font-weight: 700; }
.sb-card { background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.1); border-radius: 14px; padding: 14px 16px; margin-top: 18px; }
.sb-card-title { display: flex; justify-content: space-between; color: #fff !important; font-weight: 700; font-size: .9rem; margin-bottom: 8px; }
.sb-card-title em { color: #5FD3A6 !important; font-style: normal; font-weight: 600; font-size: .8rem; }
.sb-row { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,.08); font-size: .82rem; }
.sb-row:last-child { border-bottom: none; }
.sb-row span { color: #9FB0CF !important; }
.sb-row strong { color: #fff !important; font-weight: 600; text-align: right; }

/* ---------- Botones ---------- */
div.stButton > button, div.stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
    border-radius: 10px !important; font-weight: 600 !important; padding: .5rem 1.15rem !important;
    transition: background .15s ease, border-color .15s ease, box-shadow .15s ease !important;
}
div.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] {
    background: var(--blue) !important; border: 1px solid var(--blue) !important; color: #fff !important;
    box-shadow: 0 6px 14px -6px rgba(55, 134, 106, .6) !important;
}
div.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover { background: var(--blue-dark) !important; border-color: var(--blue-dark) !important; }
div.stButton > button[kind="secondary"], div.stDownloadButton > button {
    background: var(--card) !important; border: 1px solid #CBD3E1 !important; color: var(--ink) !important;
}
div.stButton > button[kind="secondary"]:hover, div.stDownloadButton > button:hover {
    border-color: var(--blue) !important; color: var(--blue) !important; background: var(--blue-soft) !important;
}
button:focus-visible, [data-baseweb="tab"]:focus-visible { outline: 3px solid rgba(55, 134, 106, .35) !important; outline-offset: 2px; }

/* ---------- Pestañas ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--line); margin-bottom: 20px; background: transparent; padding: 0; }
.stTabs [data-baseweb="tab"] {
    height: 44px; padding: 0 16px; border-radius: 10px 10px 0 0; color: var(--muted); font-weight: 600; background: transparent;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--ink); background: rgba(55, 134, 106, .08); }
.stTabs [aria-selected="true"] { color: var(--blue) !important; font-weight: 700 !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--blue) !important; height: 3px !important; }
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ---------- Formularios, tablas, expanders ---------- */
[data-testid="stForm"] { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 24px; box-shadow: var(--shadow); }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; box-shadow: var(--shadow); }
[data-testid="stExpander"] { background: var(--card); border: 1px solid var(--line) !important; border-radius: 12px !important; box-shadow: var(--shadow); }
[data-testid="stExpander"] summary { font-weight: 600; color: var(--ink); }
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"] { border-radius: 10px !important; }
[data-testid="stFileUploaderDropzone"] { border: 1.5px dashed #B7C3DB; border-radius: 12px; background: #F8FAFE; }

/* ---------- Avisos ---------- */
[data-testid="stAlert"] { border-radius: 12px !important; font-size: .94rem !important; }
</style>""", unsafe_allow_html=True)

st.markdown("""<style>
:root { --ink:#2B2F42; --ink-2:#565C75; --muted:#7A8096; --paper:#F6FAF7; --line:#E3EDE7; --blue:#37866A; --blue-dark:#2D6F58; --blue-soft:#E3F4EC;
        --amber-soft:#FDF5DD; --green:#3E8E74; --green-soft:#E3F4EC; --lav:#E3F4EC; --radius:16px; --shadow:0 1px 2px rgba(43,47,66,.04); }
.stApp { background: var(--paper); }
h1 { font-size: 2.2rem !important; font-weight: 700 !important; }
.topbar { border-radius: 14px; padding: 10px 16px; box-shadow: none; }
.topbar-mark { background: var(--lav); }
.pill { background: var(--green-soft); box-shadow: none; }
.page-head-icon { width: 52px; height: 52px; border-radius: 16px; background: var(--lav); box-shadow: none; font-size: 24px; }
.page-head h1 { font-size: 2.2rem !important; }
[data-testid="stMetric"] { border: 1px solid var(--line) !important; border-image: none !important; border-radius: var(--radius) !important; padding: 20px 22px !important; box-shadow: none !important; transform: none !important; }
[data-testid="stMetricValue"] { font-size: 2.3rem !important; font-weight: 700 !important; }
[data-testid="stVerticalBlockBorderWrapper"] { box-shadow: none; }
[data-testid="stVerticalBlockBorderWrapper"]:hover { border-color: #CFE3D7 !important; box-shadow: none; }
.step-num { width: 34px; height: 34px; background: var(--lav); color: var(--blue); box-shadow: none; }
.rule-chip { border-left: 1px solid var(--line); border-radius: 12px; }
[data-testid="stSidebar"] { background: #EEF6F1 !important; border-right: 1px solid #DDEBE3 !important; }
[data-testid="stSidebar"] * { color: var(--ink-2); }
.sb-head { border-bottom: 1px solid #DAE9E0; }
.sb-logo { background: #fff; box-shadow: none; border: 1px solid #DAE9E0; }
.sb-name { color: var(--ink) !important; }
.sb-sub { color: var(--muted) !important; }
[data-testid="stSidebar"] [data-testid="stRadio"] label p { color: var(--ink-2) !important; font-weight: 500; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background: rgba(55,134,106,.10); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) { background: #fff; box-shadow: 0 1px 3px rgba(43,47,66,.08); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p { color: var(--blue-dark) !important; font-weight: 600; }
.sb-card { background: #fff; border: 1px solid #DDEBE3; }
.sb-card-title { color: var(--ink) !important; }
.sb-card-title em { color: var(--green) !important; }
.sb-row { border-bottom: 1px solid #E8F1EC; }
.sb-row span { color: var(--muted) !important; }
.sb-row strong { color: var(--ink) !important; }
div.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] { background: var(--blue) !important; border: none !important; box-shadow: none !important; }
div.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover { background: var(--blue-dark) !important; filter: none; transform: none; }
div.stButton > button[kind="secondary"], div.stDownloadButton > button { border: 1px solid #D3E5DB !important; }
.stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid var(--line); gap: 4px; }
.stTabs [data-baseweb="tab"] { background: transparent; border: none; border-radius: 10px; height: 40px; }
.stTabs [aria-selected="true"] { background: var(--lav) !important; color: var(--blue-dark) !important; border: none; }
[data-testid="stForm"], [data-testid="stDataFrame"], [data-testid="stDataEditor"], [data-testid="stExpander"] { box-shadow: none; }
[data-testid="stFileUploaderDropzone"] { background: #F8FCFA; border-color: #CFE3D7; }
.ico { stroke: var(--blue-dark); width: 24px; height: 24px; }
[data-testid="stMetricValue"] { color: #37866A !important; }
.sb-logo-img { display: block; width: auto; height: auto; max-width: 170px; max-height: 70px; object-fit: contain; }
.sb-head:has(.sb-logo-img) { flex-direction: column; align-items: flex-start; gap: 14px; }
.topbar-mark .ico { width: 17px; height: 17px; }
.sb-logo .ico { width: 22px; height: 22px; }
.page-head-icon .ico { width: 26px; height: 26px; }
/* ---------- Tarjetas en verde ---------- */
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) [data-testid="stMetric"] { background: #E3F4EC !important; border-color: #CBE7D8 !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) [data-testid="stVerticalBlockBorderWrapper"] { background: #E3F4EC; border-color: #CBE7D8 !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"] { background: #E6F1E4 !important; border-color: #CFE3CB !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) [data-testid="stVerticalBlockBorderWrapper"] { background: #E6F1E4; border-color: #CFE3CB !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) [data-testid="stMetric"] { background: #DDF1EE !important; border-color: #C5E4DE !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) [data-testid="stVerticalBlockBorderWrapper"] { background: #DDF1EE; border-color: #C5E4DE !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4) [data-testid="stMetric"] { background: #EEF5DF !important; border-color: #DBE8C2 !important; }
[data-testid="stMetricLabel"] { color: var(--ink-2) !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"] .step-num { background: #fff; }
</style>""", unsafe_allow_html=True)


def go(page, tab=None):
    st.session_state["next_page"] = page
    if tab:
        st.session_state["next_tab"] = ("data_tabs" if page == "Datos" else "rule_tabs", tab)
    st.rerun()


def flash(message):
    st.session_state["flash"] = message


ICONS = {'book': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z"/></svg>', 'database': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>', 'sliders': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h8M20 6h-2M4 12h2M20 12h-8M4 18h10M20 18h0"/><circle cx="15" cy="6" r="2.2"/><circle cx="9" cy="12" r="2.2"/><circle cx="17" cy="18" r="2.2"/></svg>', 'bolt': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>', 'calendar': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>', 'check': '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3M8.5 11l2 2 3.5-4"/></svg>'}


ICONS["home"] = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5V21H3z"/><path d="M9 21v-6h6v6"/></svg>'


def sidebar_logo():
    """Logo del proyecto en la barra lateral (img/logo-utc.png); si no existe, un icono."""
    logo = ROOT / "img" / "logo-utc.png"
    if logo.is_file():
        data = base64.b64encode(logo.read_bytes()).decode()
        return f'<img class="sb-logo-img" src="data:image/png;base64,{data}" alt="Logo UTC">'
    return '<div class="sb-logo">' + ICONS["book"] + '</div>'


def page_head(icon, title, subtitle):
    st.markdown(f'<div class="page-head"><div class="page-head-icon">{ICONS[icon]}</div>'
                f'<div><h1>{title}</h1><p>{subtitle}</p></div></div>', unsafe_allow_html=True)


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


def cell_style(value):
    if value == "Receso · sin clases":
        return "background-color:#EEF1EF;color:#5E6B64;font-weight:600;font-style:italic"
    if not value:
        return "color:#B4C2BA"
    group = value.split(" · ")[0]
    bg, fg = CAL_COLORS[int(hashlib.md5(group.encode()).hexdigest(), 16) % len(CAL_COLORS)]
    return f"background-color:{bg};color:{fg};font-weight:600"


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
    styled = table.style.map(cell_style)
    lines = max((row[day].count("\n") + 1 for row in grid for day in DAYS), default=1)
    st.dataframe(styled, width="stretch", row_height=max(65, 21 * lines + 20))


if "next_page" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("next_page")
if "next_tab" in st.session_state:
    key, label = st.session_state.pop("next_tab")
    st.session_state[key] = label
with st.sidebar:
    st.markdown("""
    <div class="sb-head">
        """ + sidebar_logo() + """
        <div>
            <div class="sb-name">Coordinación</div>
            <div class="sb-sub">Planeación de Inglés</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    page = st.radio("Navegación", PAGES, key="nav", label_visibility="collapsed", format_func=lambda p: f":material/{PAGE_ICONS[p]}:  {p}")
    st.markdown(f"""
    <div class="sb-card">
        <div class="sb-card-title"><span>Estado del sistema</span><em>● Activo</em></div>
        <div class="sb-row"><span>Versión de datos</span><strong>v{revision}</strong></div>
        <div class="sb-row"><span>Bloque semanal</span><strong>7 periodos ({bundle['settings']['period_minutes']} min)</strong></div>
        <div class="sb-row"><span>Receso</span><strong>{bundle['settings']['break_start']} – {bundle['settings']['break_end']}</strong></div>
        <div class="sb-row"><span>Jornada</span><strong>{bundle['settings']['start_time']} – {bundle['settings']['end_time']}</strong></div>
        <div class="sb-row"><span>Espacios</span><strong>Edif. 1-4 e Idiomas</strong></div>
        <div class="sb-row"><span>Base de datos</span><strong>SQLite local</strong></div>
    </div>
    """, unsafe_allow_html=True)

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon=":material/check_circle:", duration=4)

st.markdown(f"""
<div class="topbar">
    <div class="topbar-left">
        <div class="topbar-mark"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z"/></svg></div>
        <span>Coordinación de Inglés</span><span class="topbar-sep">/</span><span class="topbar-page">{page}</span>
    </div>
    <div class="pill"><i></i>Datos v{revision} · Base activa</div>
</div>
""", unsafe_allow_html=True)

if page == "Vista general":
    page_head("home", "Dashboard", "Resumen de la planeación de inglés: datos cargados y siguientes pasos.")
    cols = st.columns(4)
    for col, kind, name in zip(cols, ["students", "teachers", "rooms", "blocks"], ["Alumnos", "Docentes", "Salones", "Bloques"]):
        col.metric(name, len(bundle[kind]))
    st.write("")
    for col, number, title, detail, target in zip(st.columns(3), ["1", "2", "3"], ["Reúne la información", "Define la semana", "Revisa el resultado"],
        ["Carga los Excel y corrige los registros antes de guardarlos.", "Configura bloques, cupos y disponibilidad de los espacios.", "Comprueba grupos, carga docente y conflictos; exporta los resultados."], ["Datos", "Bloques y reglas", "Generar"]):
        with col.container(border=True):
            st.markdown(f'<div class="step-num">{number}</div>', unsafe_allow_html=True)
            st.subheader(title)
            st.write(detail)
            if st.button("Abrir " + target.lower(), key=f"start_{number}"):
                go(target)
    st.subheader("Reglas de esta planeación")
    names = {"family": "Familias A, B y C", "cefr": "Niveles A1, A2, B1, B2 y C1", "course": "Curso exacto"}
    st.markdown(f"""
    <div class="rules-row">
        <div class="rule-chip"><small>Agrupación</small><b>{names[bundle['settings']['grouping']]}</b></div>
        <div class="rule-chip"><small>Cupo máximo</small><b>{bundle['settings']['max_group']} alumnos</b></div>
        <div class="rule-chip"><small>Horario común</small><b>Obligatorio por grupo de carrera</b></div>
    </div>
    """, unsafe_allow_html=True)
    st.caption("A1: Prebasic / Basic 1 · A2: Basic 2 / Basic 3 · B1: Intermediate 1 / 2 · B2: Intermediate 3 / 4 · C1: Advanced 1")
    if revision == 0:
        with st.container(border=True):
            st.subheader("Explora con un ejemplo")
            st.write("180 alumnos ficticios, cinco docentes, cinco salones y bloques distribuidos por toda la jornada. Puedes modificarlos o sustituirlos con tus archivos.")
            if st.button("Cargar datos de demostración", type="primary"):
                if save_data(demo_bundle(), "Demostración con datos ficticios"):
                    go("Datos")

elif page == "Datos":
    page_head("database", "Datos de la planeación", "Carga, revisa y guarda la información que se usará para formar los grupos.")
    for tab, kind, label in zip(st.tabs(["Alumnos", "Docentes", "Salones"], key="data_tabs", on_change="rerun"), ["students", "teachers", "rooms"], ["Alumnos", "Docentes", "Salones"]):
        with tab:
            table_editor(kind, label)

elif page == "Bloques y reglas":
    page_head("sliders", "La semana de inglés", "Define cómo se agrupan los alumnos, la jornada y los bloques semanales disponibles.")
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

            # Opción oculta del frontend: se conserva la configuración del edificio de origen.
            #strict = st.checkbox("Exigir que cada alumno curse inglés en su edificio de origen", value=s["strict_building"])
            strict = s["strict_building"]

            st.caption("Con la restricción de edificio desactivada, se busca reducir los cambios de edificio después de minimizar el número de grupos. El docente solo se asigna a sus edificios permitidos.")

            # Opción oculta del frontend: se conserva el tiempo máximo de búsqueda configurado.
            #seconds = st.number_input("Tiempo máximo de búsqueda (segundos)", min_value=1, max_value=300, value=s["solver_seconds"])
            seconds = s["solver_seconds"]
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
        daily_count = period_count(bundle["settings"])
        maximum_blocks = daily_count * len(DAYS) // 7
        if maximum_blocks:
            desired_blocks = st.number_input("Cantidad de bloques a proponer", min_value=1, max_value=maximum_blocks,
                                             value=min(len(bundle["blocks"]) or maximum_blocks, maximum_blocks), step=1,
                                             key=f"block_count_{revision}")
            st.caption(f"La jornada permite hasta {maximum_blocks} bloques sin superposición ({daily_count * len(DAYS)} periodos semanales disponibles). Cada bloque mantiene siete periodos; la propuesta se distribuye entre el inicio y el final de la jornada.")
            st.caption(f"Actualmente hay {len(bundle['blocks'])} bloques guardados. Elige la cantidad, propone, revisa y pulsa Validar y guardar para aplicarla. Los bloques manuales pueden solaparse si hay docentes y salones compatibles.")
        else:
            st.warning("La jornada tiene menos de siete periodos semanales disponibles. Amplíala en Reglas de asignación antes de proponer bloques.")
        if st.button("Proponer bloques sin superposición", disabled=maximum_blocks == 0):
            st.session_state[f"draft_blocks_{revision}"] = propose_blocks(daily_count, int(desired_blocks))
            st.session_state["editor_nonce_blocks"] = st.session_state.get("editor_nonce_blocks", 0) + 1
            st.success(f"{desired_blocks} bloques en revisión. Valida y guarda la tabla para usarlos.")
        table_editor("blocks", "Bloques")

elif page == "Generar":
    page_head("bolt", "Generar grupos y horarios", "El sistema buscará una asignación para todos los alumnos y comprobará las restricciones antes de guardarla.")
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
            # Overlay que congela la pantalla mientras se procesa
            st.markdown("""
                <style>
                #gen-overlay {
                    position: fixed;
                    inset: 0;
                    background: rgba(0, 0, 0, 0.45);
                    z-index: 999999;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    gap: 1rem;
                    cursor: not-allowed;
                    pointer-events: all;
                }
                #gen-overlay .gen-spinner {
                    width: 56px;
                    height: 56px;
                    border: 6px solid rgba(255,255,255,0.3);
                    border-top-color: #ffffff;
                    border-radius: 50%;
                    animation: gen-spin 0.9s linear infinite;
                }
                #gen-overlay .gen-label {
                    color: #ffffff;
                    font-size: 1.1rem;
                    font-weight: 600;
                    letter-spacing: 0.02em;
                    text-shadow: 0 1px 4px rgba(0,0,0,0.6);
                }
                @keyframes gen-spin { to { transform: rotate(360deg); } }
                </style>
                <div id="gen-overlay">
                    <div class="gen-spinner"></div>
                    <div class="gen-label">Generando propuesta, por favor espera…</div>
                </div>
            """, unsafe_allow_html=True)

            with st.spinner("Buscando una asignación completa y auditando el resultado…", show_time=True):

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
    if page == "Resultados":
        page_head("calendar", "Grupos y horarios", "Consulta los grupos formados, ajusta asignaciones y exporta los archivos finales.")
    else:
        page_head("check", "Auditoría de la planeación", "Verifica horarios, carga docente y cada regla antes de compartir la propuesta.")
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
        st.write("")

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
                    st.write("El Excel general incluye el listado de general de alumnos, una hoja por grupo de inglés, horarios, carga docente, auditoría y reservas para las carreras.")
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
                    st.bar_chart(loads, x="Docente", y=["Horas asignadas", "Horas libres"], color=["#37866A", "#CFE8D8"])
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