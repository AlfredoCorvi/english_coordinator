"""Vistas académicas; las validaciones y permisos viven en AcademicService."""
from datetime import time
import sqlite3
import pandas as pd
import streamlit as st


DAYS = {1:'Lunes', 2:'Martes', 3:'Miércoles', 4:'Jueves', 5:'Viernes'}


def pick_period(portal, session, label, key):
    periods = portal.periods(session)
    options = {p['id']:p['code'] for p in periods}
    return st.selectbox(label, list(options), format_func=options.get, key=key) if options else None


def select_map(label, rows, key, *, name='nombre'):
    opts={r['id']:str(r[name]) for r in rows}
    return st.selectbox(label,list(opts),format_func=opts.get,key=key) if opts else None


def render(page, admin, session, portal, academic):
    if page == 'Niveles':
        st.subheader('Catálogo de niveles')
        st.dataframe(academic.levels(session),hide_index=True)
        st.caption('Advance 1 y Advance 2 son exentos. El catálogo es informativo.')
        return
    period=pick_period(portal,session,'Cuatrimestre actual','academic_period_'+page)
    if period is None:
        st.info('No hay periodos disponibles.')
        return
    if page == 'Alumnos':
        st.subheader('Alumnos' if admin else 'Mis alumnos autorizados')
        target=pick_period(portal,session,'Consultar próximo nivel para','target_students')
        rows=academic.students(session,period,target)
        if rows:
            df=pd.DataFrame(rows)
            query=st.text_input('Buscar por nombre o matrícula').strip()
            if query:
                df=df[df['nombre'].str.contains(query,case=False,regex=False)|df['matricula'].str.contains(query,case=False,regex=False)]
            for col,label in [('carrera','Carrera'),('grupo','Grupo académico'),('turno','Turno'),('nivel_actual','Nivel actual'),('estatus','Estatus'),('proximo_nivel','Próximo nivel')]:
                values=sorted(str(v) for v in df[col].dropna().unique())
                chosen=st.selectbox(label,['Todos','Sin asignar']+values,key='filter_'+col)
                if chosen=='Sin asignar': df=df[df[col].isna()]
                elif chosen!='Todos': df=df[df[col].astype(str)==chosen]
            st.dataframe(df.drop(columns=['id','nivel_actual_id']),hide_index=True)
        else:
            st.info('No hay alumnos disponibles para este periodo y usuario.')
        if admin and rows:
            st.markdown('**Nivel inicial y autorización docente**')
            student=select_map('Alumno',rows,'admin_student')
            levels=academic.levels(session)
            level=select_map('Nivel actual inicial',levels,'initial_level',name='name')
            if st.button('Registrar nivel inicial'):
                academic.set_level(session,student,period,period,level,initial=True)
                st.success('Nivel inicial registrado.')
            teachers=academic.teachers(session,period)
            teacher=select_map('Docente autorizado',teachers,'grant_teacher')
            if teacher is not None:
                if st.button('Autorizar docente para alumno'):
                    academic.grant(session,teacher,student,period)
                    st.success('Autorización guardada.')
                if st.button('Revocar autorización explícita'):
                    academic.grant(session,teacher,student,period,False)
                    st.success('Autorización explícita revocada; la asignación publicada también puede otorgar acceso.')
            st.dataframe(academic.permissions(session,period),hide_index=True)
        elif not admin and rows:
            student=select_map('Alumno autorizado',rows,'teacher_student')
            levels=academic.levels(session)
            current=next(r['nivel_actual_id'] for r in rows if r['id']==student)
            ordered=[l['id'] for l in levels]
            suggestion=ordered[min(ordered.index(current)+1,len(ordered)-1)] if current in ordered else None
            st.write('Nivel sugerido:', next((l['name'] for l in levels if l['id']==suggestion),'Sin nivel actual'))
            level=st.selectbox('Nivel para el siguiente cuatrimestre',ordered,index=(ordered.index(suggestion) if suggestion else 0),format_func=lambda x:next(l['name']+(' · exento' if l['exempt'] else '') for l in levels if l['id']==x))
            reason=st.text_input('Motivo o comentario')
            if st.button('Guardar próximo nivel'):
                academic.set_level(session,student,period,target,level,reason)
                st.success('Decisión guardada con historial.')
            st.markdown('**Historial de nivel**')
            st.dataframe(academic.level_history(session,student,period),hide_index=True)
    elif page == 'Docentes':
        st.subheader('Docentes y restricciones por cuatrimestre')
        rows=academic.teachers(session,period)
        st.dataframe(rows,hide_index=True)
        teacher=select_map('Docente',rows,'teacher_rules')
        if teacher is None: return
        row=next(r for r in rows if r['id']==teacher)
        st.caption(f"Carga publicada: {row['grupos']} grupos / {row['grupos']*7} horas clase.")
        load=academic.teacher_load(session,teacher,period)
        if load['remaining_hours'] is not None:
            st.write(f"Límite restante: {load['remaining_hours']} horas clase y {load['remaining_blocks']} bloques.")
            with st.expander('Grupos asignados e intervalos configurados sin asignar'):
                st.dataframe(load['groups'],hide_index=True)
                st.dataframe([{'Día':DAYS[s['day']],'Inicio':s['starts'],'Fin':s['ends']} for s in load['remaining']],hide_index=True)
        participates=st.checkbox('Participa este cuatrimestre',value=bool(row['participa']) if row['participa'] is not None else True)
        hours=st.number_input('Límite individual de horas clase',min_value=0,value=int(row['max_horas'] or 0))
        blocks=st.number_input('Límite de bloques',min_value=0,value=int(row['max_bloques'] or 0))
        slots=academic.slots(session)
        labels={s['id']:f"{DAYS[s['day']]} {s['starts']}–{s['ends']}" for s in slots}
        selected=st.multiselect('Disponibilidad semanal',list(labels),default=academic.availability(session,teacher,period),format_func=labels.get)
        if st.button('Guardar restricciones'):
            academic.set_teacher_rules(session,teacher,period,participates,int(hours),int(blocks),selected)
            st.success('Restricciones guardadas.')
        if not slots: st.info('Configura primero los intervalos en Bloques horarios.')
    elif page == 'Bloques horarios':
        st.subheader('Bloques horarios')
        st.caption('Define los intervalos confirmados de 45 minutos. No se generan horarios automáticamente.')
        with st.form('new_block_form'):
            block_code=st.text_input('Identificador del nuevo bloque')
            block_name=st.text_input('Nombre del nuevo bloque')
            add_block=st.form_submit_button('Crear bloque institucional')
        if add_block:
            academic.create_block(session,block_code,block_name)
            st.success('Bloque creado; configura sus intervalos antes de activarlo.')
        with st.form('slot_form'):
            day=st.selectbox('Día',list(DAYS),format_func=DAYS.get)
            start=st.time_input('Inicio',value=time(8,30),step=60)
            end=st.time_input('Fin',value=time(9,15),step=60)
            save=st.form_submit_button('Agregar intervalo confirmado')
        if save:
            academic.add_slot(session,day,start.strftime('%H:%M'),end.strftime('%H:%M'))
            st.success('Intervalo agregado.')
        slots=academic.slots(session)
        labels={s['id']:f"{DAYS[s['day']]} {s['starts']}–{s['ends']}" for s in slots}
        rows=academic.blocks(session,period)
        st.dataframe(rows,hide_index=True)
        block=select_map('Bloque',rows,'block_choice',name='name')
        row=next(r for r in rows if r['id']==block)
        selected=st.multiselect('Horas del bloque',list(labels),default=academic.block_slots(session,row['version_id']) if row['version_id'] else [],format_func=labels.get)
        active=st.checkbox('Activo para el periodo',value=bool(row['active']) if row['active'] is not None else True)
        if st.button('Guardar nueva versión del bloque'):
            academic.save_block(session,period,block,selected,active)
            st.success('Versión guardada; las versiones anteriores se conservan.')
        grid={DAYS[d]:[labels[s['id']] for s in slots if s['day']==d and s['id'] in selected] for d in DAYS}
        st.dataframe(pd.DataFrame({k:pd.Series(v) for k,v in grid.items()}),hide_index=True)
    elif page == 'Configuración del algoritmo':
        st.subheader('Configuración del algoritmo')
        current=academic.settings(session,period)
        st.caption(f"Configuración vigente: versión {current['version']}. Los planes anteriores conservan sus parámetros.")
        with st.form('algorithm_settings'):
            minimum=int(st.number_input('Cupo mínimo',min_value=8,max_value=35,value=current['min_size']))
            target=int(st.number_input('Cupo ideal',min_value=8,max_value=35,value=current['target_size']))
            maximum=int(st.number_input('Cupo máximo',min_value=8,max_value=35,value=current['max_size']))
            seconds=int(st.number_input('Límite de búsqueda en segundos',min_value=1,max_value=300,value=current['solver_seconds']))
            saved=st.form_submit_button('Guardar configuración')
        if saved:
            version=academic.set_settings(session,period,minimum,target,maximum,seconds)
            st.success(f'Configuración versión {version} guardada.')
    elif page == 'Incidencias':
        st.subheader('Incidencias de cambio de nivel')
        rows=academic.incidents(session,period)
        st.dataframe(rows,hide_index=True)
        if admin:
            open_rows=[r for r in rows if r['estado'] in ('ABIERTA','EN_REVISION')]
            incident=select_map('Incidencia pendiente',open_rows,'incident_admin',name='alumno')
            if incident:
                resolution=st.text_input('Resolución')
                decision=st.radio('Decisión',['Aprobar','Rechazar'],horizontal=True)
                if st.button('Guardar resolución'):
                    academic.resolve_incident(session,incident,decision=='Aprobar',resolution)
                    st.success('Resolución guardada. Revisa la columna de aplicación para conocer el resultado.')
        else:
            students=academic.students(session,period)
            student=select_map('Alumno autorizado',students,'incident_student')
            if student:
                levels=academic.levels(session)
                level=select_map('Nivel solicitado',levels,'incident_level',name='name')
                reason=st.text_area('Motivo')
                if st.button('Enviar incidencia'):
                    academic.create_incident(session,period,student,level,reason)
                    st.success('Incidencia enviada.')
