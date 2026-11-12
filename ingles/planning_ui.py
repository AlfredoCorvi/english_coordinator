"""Consulta y generación de propuestas; sin lógica del optimizador en la vista."""
import streamlit as st
import json

from ingles.planning_service import PlanningService, block_identity
from ingles.relational_planning import ConfigurationError
from ingles.version_service import VersionService
from ingles.academic_services import AcademicService


def render_planning(store, auth, portal, session):
    service=PlanningService(store,auth)
    st.subheader('Generación de grupos')
    periods=portal.periods(session)
    options={p['id']:p['code'] for p in periods}
    if not options:
        st.info('Crea un cuatrimestre antes de generar propuestas.')
        return
    period=st.selectbox('Cuatrimestre a organizar',list(options),format_func=options.get,key='planning_period')
    overview=service.overview(session,period)
    if overview['period']['status']=='CERRADO':
        st.warning('El cuatrimestre está cerrado; sus versiones solo pueden consultarse.')
    cols=st.columns(4)
    for col,label,key in zip(cols,['Alumnos activos','Elegibles','Sin nivel','Exentos'],['active','eligible','missing_level','exempt']):
        col.metric(label,overview[key])
    if overview['missing_level']:
        st.warning('Hay alumnos sin nivel confirmado; se mostrarán como pendientes.')
        with st.expander('Ver alumnos sin nivel'):
            st.dataframe(overview['missing_students'],hide_index=True)
    if overview['exempt_students']:
        with st.expander('Ver alumnos exentos'):
            st.dataframe(overview['exempt_students'],hide_index=True)
    if not overview['eligible']:
        st.info('No hay alumnos elegibles con nivel confirmado.')
    st.markdown('**Docentes participantes y disponibilidad**')
    st.dataframe(overview['teachers'],hide_index=True)
    if not overview['teachers'] or all(not t['compatible_blocks'] for t in overview['teachers']):
        st.warning('No hay docentes participantes con disponibilidad compatible con algún bloque válido.')
    st.markdown('**Bloques activos**')
    st.dataframe(overview['blocks'],hide_index=True)
    if not overview['blocks'] or any(not b['valid'] for b in overview['blocks']):
        st.warning('Configura bloques activos con siete intervalos válidos antes de generar.')
    ready=bool(overview['period']['status']!='CERRADO' and overview['eligible'] and overview['blocks'] and all(b['valid'] for b in overview['blocks']) and
               any(t['compatible_blocks'] for t in overview['teachers']))
    if st.button('Generar y guardar propuesta',type='primary',disabled=not ready):
        try:
            generated=service.generate_and_save(session,period)
            result=generated['result']
            if generated['plan_id']:
                st.success(f"Propuesta {generated['plan_id']} guardada. {result['message']}")
            else:
                st.warning(f"{result['status']}: {result['message']} No se guardó una propuesta.")
        except (ValueError,ConfigurationError) as exc:
            st.error(str(exc))
    proposals=service.proposals(session,period)
    st.markdown('**Propuestas del cuatrimestre**')
    if not proposals:
        st.info('Todavía no hay propuestas guardadas.')
        return
    options={p['id']:f"Propuesta {p['id']} · {p['status']} · {p['created_at']}" for p in proposals}
    plan_id=st.selectbox('Consultar propuesta',list(options),format_func=options.get)
    plan=service.proposal(session,plan_id)
    metrics=plan['metrics']
    st.write(f"Estado de solución: {metrics.get('status','Sin datos')} · {metrics.get('message','')}")
    st.caption('La optimalidad se refiere a la búsqueda con las organizaciones anteriores excluidas.')
    if metrics.get('warnings'):
        for warning in metrics['warnings']: st.warning(warning)
    st.write('Prioridades demostradas:',metrics.get('proven_stages',[]))
    for group in plan['groups']:
        with st.expander(f"{group['code']} · {group['block']} · {group['teacher']} · {len(group['students'])} alumnos"):
            st.write('Niveles:',', '.join(group['levels']))
            st.dataframe(group['students'],hide_index=True)
    st.markdown('**Alumnos pendientes**')
    st.dataframe(plan['pending'],hide_index=True)


def _versions(store,auth,portal,session,key):
    periods=portal.periods(session)
    options={p['id']:p['code'] for p in periods}
    if not options:
        st.info('No hay cuatrimestres disponibles.')
        return None,None,None
    period=st.selectbox('Cuatrimestre',list(options),format_func=options.get,key=key+'_period')
    proposals=PlanningService(store,auth).proposals(session,period)
    if not proposals:
        st.info('No hay propuestas para este cuatrimestre.')
        return period,None,None
    labels={p['id']:f"Versión {p['id']} · {p['status']} · {p['created_at']}" for p in proposals}
    plan_id=st.selectbox('Versión',list(labels),format_func=labels.get,key=key+'_version')
    return period,plan_id,proposals


def render_groups(store,auth,portal,session):
    st.subheader('Grupos de inglés')
    period,plan_id,_=_versions(store,auth,portal,session,'groups')
    if plan_id is None: return
    service=PlanningService(store,auth); versions=VersionService(store,auth)
    plan=service.proposal(session,plan_id)
    period_name=next(p['code'] for p in portal.periods(session) if p['id']==period)
    st.write(f"Cuatrimestre {period_name} · versión {plan_id} · {plan['status']}")
    groups=plan['groups']
    levels=sorted({level for g in groups for level in g['levels']})
    teachers=sorted({g['teacher'] for g in groups if g['teacher']})
    blocks=sorted({g['block'] for g in groups})
    level=st.selectbox('Filtrar por nivel',['Todos']+levels)
    teacher=st.selectbox('Filtrar por docente',['Todos']+teachers)
    block=st.selectbox('Filtrar por bloque',['Todos']+blocks)
    visible=[g for g in groups if (level=='Todos' or level in g['levels']) and
             (teacher=='Todos' or teacher==g['teacher']) and (block=='Todos' or block==g['block'])]
    st.dataframe([{'grupo':g['code'],'niveles':', '.join(g['levels']),'alumnos':len(g['students']),
                   'docente':g['teacher'],'bloque':g['block'],'periodo':period_name,'estado':plan['status']} for g in visible],hide_index=True)
    if not visible:
        st.info('No hay grupos con esos filtros.')
    else:
        labels={g['code']:f"{g['code']} · {g['teacher']} · {g['block']}" for g in visible}
        group_code=st.selectbox('Grupo',list(labels),format_func=labels.get)
        chosen=next(g for g in visible if g['code']==group_code)
        st.dataframe(chosen['students'],hide_index=True)
        with st.expander('Preparar cambio manual'):
            kind=st.selectbox('Tipo de cambio',['Docente','Bloque','Reasignar alumno'])
            value=None; student=None; target=group_code
            if kind=='Docente':
                choices={t['id']:t['name'] for t in plan['teachers']}
                if choices: value=st.selectbox('Nuevo docente',list(choices),format_func=choices.get)
            elif kind=='Bloque':
                choices={b['id']:b['name'] for b in plan['blocks']}
                if choices: value=st.selectbox('Nuevo bloque',list(choices),format_func=choices.get)
            else:
                choices={s['id']:f"{s['enrollment']} · {s['name']}" for s in chosen['students']}
                destinations={g['code']:g['code'] for g in groups if g['code']!=group_code}
                if choices and destinations:
                    student=st.selectbox('Alumno',list(choices),format_func=choices.get)
                    target=st.selectbox('Grupo destino',list(destinations))
                else:
                    st.info('Se necesita un alumno asignado y otro grupo de destino.')
            reason=st.text_input('Motivo del cambio')
            if st.button('Validar y crear versión derivada'):
                try:
                    if (kind in ('Docente','Bloque') and value is None) or (kind=='Reasignar alumno' and student is None):
                        raise ValueError('Selecciona los datos necesarios para el cambio.')
                    new_id=versions.modify(session,plan_id,kind={'Docente':'docente','Bloque':'bloque','Reasignar alumno':'alumno'}[kind],
                                           group=target,value=value,student=student,reason=reason)
                    st.success(f'Versión derivada {new_id} creada. La versión original permanece intacta.')
                except ValueError as exc: st.error(str(exc))
    incidents=[i for i in AcademicService(store,auth).incidents(session,period) if i['estado']=='APROBADA' and i['aplicacion']=='PENDIENTE']
    if incidents and groups:
        with st.expander('Preparar aplicación de incidencia aprobada'):
            labels={i['id']:f"{i['id']} · {i['alumno']} · {i['nivel_actual']} → {i['solicitado']}" for i in incidents}
            incident=st.selectbox('Incidencia',list(labels),format_func=labels.get)
            requested=next(i['solicitado'] for i in incidents if i['id']==incident)
            exempt={l['name'] for l in AcademicService(store,auth).levels(session) if l['exempt']}
            if requested in exempt:
                destination=None
                st.info('El nivel solicitado es exento; se validará la salida del alumno de su grupo.')
            else:
                destination=st.selectbox('Grupo compatible de destino',[g['code'] for g in groups])
            reason=st.text_input('Motivo de la aplicación')
            if st.button('Validar incidencia y crear versión'):
                try:
                    new_id=versions.stage_incident(session,plan_id,incident,destination,reason)
                    st.success(f'Versión {new_id} creada. La incidencia seguirá pendiente hasta publicar esa versión.')
                except ValueError as exc: st.error(str(exc))
    st.markdown('**Alumnos pendientes**')
    st.dataframe(plan['pending'],hide_index=True)
    if plan['status']=='PROPUESTA':
        with st.expander('Publicar propuesta'):
            publication_key=f'publication_seen_{plan_id}'
            current_official=versions.current_official(session,period)
            if publication_key not in st.session_state:
                st.session_state[publication_key]=current_official
            shown=st.session_state[publication_key]
            st.caption(f"Publicación revisada: versión {shown}" if shown is not None else 'Publicación revisada: no había una versión oficial.')
            if st.button('Actualizar estado de publicación'):
                st.session_state[publication_key]=current_official
                st.rerun()
            if plan['pending']:
                st.warning(f"La propuesta tiene {len(plan['pending'])} alumnos pendientes. Revisa sus motivos arriba.")
                partial=st.checkbox('Confirmo la publicación parcial con estos pendientes')
            else: partial=False
            confirmed=st.checkbox('Confirmo que deseo publicar esta versión')
            reason=st.text_input('Motivo de publicación (opcional)')
            if st.button('Publicar propuesta'):
                try:
                    versions.publish(session,plan_id,confirmed=confirmed,confirm_partial=partial,reason=reason,
                                     expected_official_id=shown)
                    st.session_state.pop(publication_key,None)
                    st.success('Propuesta publicada. Se conservó el historial de publicaciones.')
                except ValueError as exc: st.error(str(exc))


def render_history(store,auth,portal,session):
    st.subheader('Historial y versiones')
    period,plan_id,proposals=_versions(store,auth,portal,session,'history')
    if period is None: return
    versions=VersionService(store,auth)
    if plan_id is not None:
        st.dataframe(versions.history(session,period),hide_index=True)
    st.markdown('**Movimientos académicos del periodo**')
    st.dataframe(versions.academic_history(session,period),hide_index=True)
    if plan_id is None: return
    labels={p['id']:f"Versión {p['id']} · {p['status']}" for p in proposals}
    other=st.selectbox('Comparar con',list(labels),index=min(1,len(labels)-1),format_func=labels.get)
    differences=versions.compare(session,plan_id,other)
    service=PlanningService(store,auth)
    left,right=service.proposal(session,plan_id),service.proposal(session,other)
    def index(plan):
        people={s['id']:s for g in plan['groups'] for s in g['students']}
        people.update({s['student_id']:s for s in plan['pending']})
        return people
    def describe(value,plan,people):
        if value is None: return 'Sin grupo'
        teachers={t['id']:t['name'] for t in plan['teachers']}
        block=next((b['name'] for b in plan['blocks'] if block_identity({'blocks':plan['blocks']},b['id'])==value['block']),str(value['block']))
        members=[people.get(i,{}).get('enrollment',str(i)) for i in value['members']]
        return {'docente':teachers.get(value['teacher'],str(value['teacher'])),
                'bloque':block,
                'nivel':plan['levels'].get(str(value['level']),{}).get('name',str(value['level'])),
                'matrículas_del_grupo':members}
    left_people,right_people=index(left),index(right)
    st.caption('Las diferencias consideran alumnos, compañeros, nivel, docente y bloque, sin depender del código del grupo.')
    st.dataframe([{'matrícula':(left_people.get(d['student_id']) or right_people.get(d['student_id']) or {}).get('enrollment',''),
                   'alumno':(left_people.get(d['student_id']) or right_people.get(d['student_id']) or {}).get('name',''),
                   'antes':json.dumps(describe(d['before'],left,left_people),ensure_ascii=False),
                   'después':json.dumps(describe(d['after'],right,right_people),ensure_ascii=False)} for d in differences],hide_index=True)
