"""Selección y descarga de reportes institucionales."""
import streamlit as st
from ingles.institutional_reports import InstitutionalReports, REPORTS
from ingles.planning_service import PlanningService


def render_reports(store,auth,portal,session):
    auth.authorize(session,{'SECRETARIA'})
    st.subheader('Reportes')
    periods=portal.periods(session)
    period_options={p['id']:p['code'] for p in periods}
    if not period_options:
        st.info('No hay periodos disponibles.'); return
    period=st.selectbox('Periodo del reporte',list(period_options),format_func=period_options.get)
    proposals=PlanningService(store,auth).proposals(session,period)
    if not proposals:
        st.info('Genera una propuesta para descargar reportes.'); return
    versions={p['id']:f"Versión {p['id']} · {p['status']}" for p in proposals}
    version=st.selectbox('Versión del reporte',list(versions),format_func=versions.get)
    kind=st.selectbox('Reporte',list(REPORTS),format_func=lambda k:REPORTS[k][0])
    reports=InstitutionalReports(store,auth)
    summary=reports.collect(session,version,kind)
    st.caption(f"Periodo: {summary['period']} · Versión {version} · Estado: {summary['state']} · Datos de la instantánea de esta versión")
    st.caption(summary['scope'])
    st.dataframe([dict(zip(summary['columns'],row)) for row in summary['rows']],hide_index=True)
    excel=reports.excel(session,version,kind); pdf=reports.pdf(session,version,kind)
    left,right=st.columns(2)
    left.download_button('Descargar Excel',excel,file_name=f'{kind}_v{version}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    right.download_button('Descargar PDF',pdf,file_name=f'{kind}_v{version}.pdf',mime='application/pdf')
