"""Portal de desarrollo; las pantallas legadas permanecen independientes."""
import json
import os
from pathlib import Path
import sqlite3

import streamlit as st

from ingles.integrations import ConfigurableTestAuth, Identity, IntegrationError, provider_from_environment
from ingles.institutional_services import AccessDenied, AuthService, SyncService
from ingles.local_fixtures import LocalFixture
from ingles.portal_services import PortalService
from ingles.relational_storage import RelationalStore
from ingles.academic_services import AcademicService
from ingles.academic_ui import render as render_academic
from ingles.planning_ui import render_planning, render_groups, render_history
from ingles.planning_service import PlanningService
from ingles.version_service import VersionService
from ingles.demo_scenario import DemoService
from ingles.report_ui import render_reports


st.set_page_config(page_title='Inglés · Portal institucional', page_icon='📚', layout='wide')


@st.cache_resource
def resources(path, credentials_json):
    # The cache key and credentials remain in process memory, never in SQLite.
    store = RelationalStore(path)
    store.initialize()
    try:
        credentials = json.loads(credentials_json)
        if not isinstance(credentials, dict):
            raise ValueError
        entries = {}
        for username, data in credentials.items():
            if not isinstance(username, str) or not isinstance(data, dict):
                raise ValueError
            password, subject = data.get('password'), data.get('subject')
            if not isinstance(password, str) or not password or not isinstance(subject, str) or not subject:
                raise ValueError
            entries[username] = (password, Identity('desarrollo', subject))
    except (ValueError, TypeError):
        raise ValueError('Configuración de autenticación ficticia inválida.') from None
    auth = AuthService(store, ConfigurableTestAuth(entries))
    return store, auth, PortalService(store, auth)


path = os.environ.get('INGLES_RELATIONAL_DB_PATH', str(Path(__file__).resolve().parent / 'data' / 'institucional.sqlite3'))
try:
    store, auth, portal = resources(path, os.environ.get('INGLES_DEV_AUTH', '{}'))
except (ValueError, sqlite3.Error):
    st.error('No fue posible inicializar el portal. Comprueba la base relacional y la configuración de desarrollo.')
    st.stop()

st.title('Sistema de inglés')
st.caption('Portal de desarrollo con identidades ficticias')
session = st.session_state.get('institutional_session')
try:
    profile = auth.profile(session) if session else None
except AccessDenied:
    st.session_state.pop('institutional_session', None)
    profile = None
    st.warning('La sesión terminó o el usuario ya no tiene acceso.')

if not profile:
    with st.form('login', clear_on_submit=True):
        username = st.text_input('Usuario')
        password = st.text_input('Contraseña', type='password')
        submit = st.form_submit_button('Iniciar sesión')
    if submit:
        try:
            st.session_state['institutional_session'] = auth.login(username, password)
            st.rerun()
        except AccessDenied:
            st.error('No fue posible iniciar sesión.')
    st.stop()

with st.sidebar:
    st.write(f"Usuario: {profile['subject']}")
    if st.button('Cerrar sesión'):
        auth.logout(session)
        st.session_state.clear()
        st.rerun()
    is_admin = 'SECRETARIA' in profile['roles']
    choices = (['Panel', 'Periodos', 'Sincronización', 'Alumnos', 'Docentes', 'Niveles', 'Bloques horarios', 'Configuración del algoritmo', 'Incidencias', 'Generación de grupos', 'Grupos de inglés', 'Historial y versiones', 'Reportes']
               if is_admin else ['Mi panel', 'Mis alumnos y grupos', 'Alumnos', 'Niveles', 'Incidencias'])
    page = st.radio('Navegación', choices)

try:
    if page == 'Reportes':
        render_reports(store,auth,portal,session)
    elif page == 'Generación de grupos':
        render_planning(store, auth, portal, session)
    elif page == 'Grupos de inglés':
        render_groups(store, auth, portal, session)
    elif page == 'Historial y versiones':
        render_history(store, auth, portal, session)
    elif page in ('Alumnos', 'Docentes', 'Niveles', 'Bloques horarios', 'Configuración del algoritmo', 'Incidencias'):
        render_academic(page, is_admin, session, portal, AcademicService(store, auth))
    elif page == 'Panel':
        auth.authorize(session, {'SECRETARIA'})
        st.subheader('Panel administrativo')
        if os.environ.get('INGLES_DEMO_MODE')=='1':
            st.info('Modo de desarrollo: el escenario y sus horarios son ficticios.')
            if st.button('Cargar escenario de demostración'):
                try:
                    outcome=DemoService(store,auth).load(session)
                    st.success('Escenario ficticio cargado.' if outcome['created'] else 'El escenario ya estaba cargado; no se modificaron los datos.')
                except ValueError as exc:
                    st.error(str(exc))
        periods=portal.periods(session)
        if not periods:
            st.info('Crea un periodo para consultar los indicadores.')
        else:
            labels={p['id']:p['code'] for p in periods}
            selected=st.selectbox('Periodo del panel',list(labels),format_func=labels.get)
            info=PlanningService(store,auth).overview(session,selected)
            state=VersionService(store,auth).dashboard(session,selected)
            metrics=[('Alumnos inscritos',info['total']),('Alumnos activos',info['active']),('Elegibles',info['eligible']),('Sin nivel',info['missing_level']),
                     ('Exentos',info['exempt']),('Grupos última versión',state['generated_groups']),('Grupos publicados',state['published_groups']),
                     ('Grupos oficiales sin docente',state['groups_without_teacher']),
                     ('Docentes participantes',len(info['teachers'])),('Docentes disponibles',sum(bool(t['compatible_blocks']) for t in info['teachers'])),('Docentes asignados',state['assigned_teachers']),
                     ('Alumnos sin grupo oficial',max(0,info['active']-info['exempt']-state['assigned_students'])),
                     ('Incidencias pendientes',state['pending_incidents']),('Conflictos oficiales',len(state['conflicts']))]
            for i in range(0,len(metrics),4):
                for col,(label,value) in zip(st.columns(4),metrics[i:i+4]): col.metric(label,value)
            if state['conflicts']:
                st.warning('La organización oficial presenta conflictos frente a los datos actuales.')
                st.dataframe(state['conflicts'],hide_index=True)
    elif page == 'Periodos':
        st.subheader('Periodos académicos')
        st.dataframe(portal.periods(session), hide_index=True)
        with st.form('period_form', clear_on_submit=True):
            code = st.text_input('Código del periodo')
            start = st.date_input('Fecha de inicio')
            end = st.date_input('Fecha de fin')
            create = st.form_submit_button('Crear periodo')
        if create:
            try:
                portal.create_period(session, code, start, end)
                st.success('Periodo creado.')
                st.rerun()
            except (ValueError, sqlite3.IntegrityError):
                st.error('El periodo no es válido o el código ya existe.')
    elif page == 'Sincronización':
        auth.authorize(session, {'SECRETARIA'})
        st.subheader('Sincronización institucional')
        periods = portal.periods(session)
        options = {p['id']: p['code'] for p in periods if p['status'] != 'CERRADO'}
        period_id = st.selectbox('Periodo de alumnos', list(options), format_func=options.get) if options else None
        if not options:
            st.info('Crea un periodo antes de sincronizar alumnos.')
        source = st.radio('Origen', ['Datos ficticios locales', 'Mockaroo'], horizontal=True)
        kind = st.radio('Datos', ['Alumnos', 'Maestros'], horizontal=True)
        if st.button('Sincronizar'):
            try:
                if kind == 'Alumnos' and period_id is None:
                    raise ValueError('Selecciona un periodo.')
                api_kind = 'ALUMNOS' if kind == 'Alumnos' else 'MAESTROS'
                provider = LocalFixture(api_kind) if source.startswith('Datos') else provider_from_environment(api_kind)
                sync = SyncService(store, auth, 'local_demo' if source.startswith('Datos') else 'mockaroo', 'desarrollo')
                run = sync.sync_students(session, provider, period_id) if kind == 'Alumnos' else sync.sync_teachers(session, provider)
                st.success(f'Sincronización {run} procesada.')
            except (IntegrationError, ValueError) as exc:
                st.error(str(exc))
        st.markdown('**Alumnos importados del periodo**')
        st.dataframe(portal.imported(session, 'students', period_id), hide_index=True)
        st.markdown('**Docentes importados**')
        st.dataframe(portal.imported(session, 'teachers'), hide_index=True)
        st.markdown('**Resultados de sincronización**')
        st.dataframe(portal.imported(session, 'runs'), hide_index=True)
    elif page in ('Mi panel', 'Mis alumnos y grupos'):
        auth.authorize(session, {'DOCENTE'})
        st.subheader(page)
        periods = portal.periods(session)
        options = {p['id']: p['code'] for p in periods}
        if not options:
            st.info('No hay periodos disponibles.')
        else:
            period_id = st.selectbox('Periodo', list(options), format_func=options.get)
            if page == 'Mi panel':
                academic=AcademicService(store,auth)
                selected_period=next(p for p in periods if p['id']==period_id)
                future=sorted((p for p in periods if p['start_date']>selected_period['end_date']),key=lambda p:p['start_date'])
                students=academic.students(session,period_id,future[0]['id'] if future else None)
                my_groups=portal.teacher_groups(session,period_id)
                cols=st.columns(3)
                cols[0].metric('Alumnos autorizados',len(students))
                cols[1].metric('Sin próximo nivel',sum(not s['proximo_nivel'] for s in students) if future else 'Sin periodo siguiente')
                cols[2].metric('Bloques asignados',len({g['bloque'] for g in my_groups}))
            st.write('Grupos publicados')
            st.dataframe(portal.teacher_groups(session, period_id), hide_index=True)
            if page == 'Mis alumnos y grupos':
                st.write('Alumnos de mis grupos publicados')
                st.dataframe(portal.teacher_students(session, period_id), hide_index=True)
            st.caption('Para registrar el próximo nivel o una incidencia, usa Alumnos o Incidencias en el menú.')
except AccessDenied:
    st.session_state.pop('institutional_session', None)
    st.warning('La sesión terminó o ya no tiene permisos.')
    st.rerun()
except (ValueError, sqlite3.IntegrityError) as exc:
    st.error(str(exc) if isinstance(exc, ValueError) else 'No fue posible guardar: comprueba los datos y relaciones.')
