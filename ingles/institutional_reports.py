"""Reportes históricos por versión; solo Secretaría puede exportarlos."""
from collections import Counter
from io import BytesIO
import json
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle

from ingles.relational_audit import audit_snapshot
from ingles.relational_planning import load_snapshot
from ingles.version_service import _read, _effective


REPORTS={
    'alumnos_ingles':('Alumnos por grupo de inglés',['Grupo','Nivel','Matrícula','Nombre','Carrera','Grupo académico','Docente','Bloque']),
    'alumnos_academico':('Alumnos por grupo académico',['Carrera','Grupo académico','Matrícula','Nombre','Nivel','Grupo inglés','Situación']),
    'grupos_bloque':('Grupos por bloque horario',['Bloque','Horario','Grupo','Niveles','Alumnos','Docente']),
    'grupos_docente':('Grupos por docente',['Docente','Grupo','Niveles','Alumnos','Bloque','Horario']),
    'carga_docente':('Carga horaria docente',['Docente','Tipo','Grupos','Horas clase','Máximo horas','Máximo bloques']),
    'pendientes':('Alumnos sin asignación',['Matrícula','Nombre','Carrera','Grupo académico','Nivel','Categoría','Detalle']),
    'conflictos':('Conflictos y advertencias',['Tipo','Detalle']),
    'resumen':('Resumen general',['Indicador','Valor']),
}


def _schedule(block):
    days={1:'Lun',2:'Mar',3:'Mié',4:'Jue',5:'Vie'}
    return '; '.join(f"{days.get(s['day'],s['day'])} {s['starts']}-{s['ends']}" for s in sorted(block.get('slots',[]),key=lambda s:(s['day'],s['starts'])))


class InstitutionalReports:
    def __init__(self,store,auth):
        self.store,self.auth=store,auth

    def collect(self,session,plan_id,kind):
        self.auth.authorize(session,{'SECRETARIA'})
        if kind not in REPORTS: raise ValueError('Reporte desconocido.')
        with self.store.connect() as db:
            db.execute('BEGIN')
            row,base,plan,changes=_read(db,plan_id)
            data=_effective(base,changes)
            period=db.execute('SELECT code FROM periods WHERE id=?',(row['period_id'],)).fetchone()[0]
            metrics=json.loads(row['metrics'] or '{}')
            issues=audit_snapshot(data,plan)
            has_inactive_snapshot=db.execute('SELECT 1 FROM plan_report_meta WHERE plan_id=?',(plan_id,)).fetchone() is not None
            inactive=[dict(r) for r in db.execute('SELECT * FROM plan_inactive_students WHERE plan_id=?',(plan_id,))]
            current_issues=[]
            if row['status']=='PUBLICADA':
                try:
                    current_issues=audit_snapshot(load_snapshot(db,row['period_id']),plan)
                except ValueError as exc:
                    current_issues=[{'rule':'CONFIGURACION','detail':str(exc)}]
        students={s['id']:s for s in data['students']}; teachers={t['id']:t for t in data['teachers']}
        blocks={b['id']:b for b in data['blocks']}; levels=data['levels']
        groups={g['id']:g for g in plan['groups']}; members={g:[] for g in groups}
        assigned={}
        for a in plan['assignments']:
            if a['group'] in groups and a['student'] in students:
                members[a['group']].append(a['student']); assigned[a['student']]=a['group']
        pending={p['student']:p for p in plan['pending']}
        def name_level(s): return levels.get(s.get('level'),{}).get('name','Sin nivel')
        def teacher(g): return teachers.get(g['teacher'],{}).get('name','Sin docente')
        def block(g): return blocks.get(g['block'],{'name':'Bloque no disponible','slots':[]})
        def group_levels(g): return ', '.join(levels.get(l,{}).get('name',str(l)) for l in g['levels'])
        rows=[]
        if kind=='alumnos_ingles':
            for gid,g in groups.items():
                for sid in members[gid]:
                    s=students[sid]
                    rows.append([gid,name_level(s),s.get('enrollment',''),s.get('name',''),s.get('career',''),s.get('academic_group',''),teacher(g),block(g)['name']])
        elif kind=='alumnos_academico':
            for sid,s in students.items():
                situation='Exento' if s['exempt'] else 'Asignado' if sid in assigned else 'Sin nivel' if s['level'] is None else 'Pendiente'
                rows.append([s.get('career',''),s.get('academic_group',''),s.get('enrollment',''),s.get('name',''),name_level(s),assigned.get(sid,''),situation])
            for s in inactive:
                rows.append([s['career'],s['academic_group'],s['enrollment'],s['name'],s['level'] or 'Sin nivel','','Inactivo'])
        elif kind in ('grupos_bloque','grupos_docente'):
            for gid,g in groups.items():
                b=block(g); n=len(members[gid]); level=group_levels(g)
                rows.append([b['name'],_schedule(b),gid,level,n,teacher(g)] if kind=='grupos_bloque' else [teacher(g),gid,level,n,b['name'],_schedule(b)])
        elif kind=='carga_docente':
            counts=Counter(g['teacher'] for g in groups.values())
            for tid,t in teachers.items():
                n=counts[tid]; rows.append([t['name'],t['employment_type'],n,n*7,t['max_hours'],t['max_blocks']])
        elif kind=='pendientes':
            for sid,p in pending.items():
                s=students.get(sid,{})
                rows.append([s.get('enrollment',''),s.get('name',''),s.get('career',''),s.get('academic_group',''),name_level(s),p['reason'],p.get('detail') or ''])
        elif kind=='conflictos':
            rows.extend([['Instantánea: '+i['rule'],i['detail']] for i in issues])
            rows.extend([['Datos actuales: '+i['rule'],i['detail']] for i in current_issues])
            rows.extend([['Advertencia',str(w)] for w in metrics.get('warnings',[])])
            if not rows: rows=[['Sin conflictos','La auditoría de la instantánea no detectó errores.']]
        else:
            rows=[['Alumnos inscritos',len(students)+len(inactive) if has_inactive_snapshot else 'No disponible'],
                  ['Alumnos inactivos',len(inactive) if has_inactive_snapshot else 'No disponible'],
                  ['Alumnos activos',len(students)],['Elegibles',sum(s['level'] is not None and not s['exempt'] for s in students.values())],
                  ['Sin nivel',sum(s['level'] is None for s in students.values())],['Exentos',sum(bool(s['exempt']) for s in students.values())],
                  ['Grupos',len(groups)],['Alumnos asignados',len(assigned)],['Alumnos pendientes',len(pending)],
                  ['Docentes asignados',len({g['teacher'] for g in groups.values()})],['Conflictos en instantánea',len(issues)],
                  ['Conflictos frente a datos actuales',len(current_issues) if row['status']=='PUBLICADA' else 'No aplica']]
        rows.sort(key=lambda row:tuple(str(v).casefold() for v in row))
        scope=('Inscripciones activas e inactivas conservadas al crear la versión.' if kind=='alumnos_academico' and has_inactive_snapshot else
               'Alumnos activos de la instantánea; esta versión no conserva inscripciones inactivas.' if kind=='alumnos_academico' else
               'Alumnos activos de la instantánea; las inscripciones inactivas no forman parte del plan.')
        return {'period':period,'version':plan_id,'state':row['status'],'title':REPORTS[kind][0],
                'columns':REPORTS[kind][1],'rows':rows,'warnings':metrics.get('warnings',[]),
                'scope':scope}

    def excel(self,session,plan_id,kind):
        report=self.collect(session,plan_id,kind)
        book=Workbook(); ws=book.active; ws.title='Reporte'
        for row in ([report['title']],[f"Periodo: {report['period']}"],[f"Versión: {report['version']} · Estado: {report['state']}"],[report['scope']],report['columns'],*report['rows']):
            ws.append(row)
        for cell in ws[5]:
            cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='17324D')
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value,str): cell.data_type='s'
        ws.freeze_panes='A6'; ws.auto_filter.ref=f'A5:{ws.cell(ws.max_row,len(report["columns"])).coordinate}'
        for column in ws.columns:
            letter=column[0].column_letter
            ws.column_dimensions[letter].width=min(48,max(14,max(len(str(c.value or '')) for c in column)+2))
        out=BytesIO(); book.save(out)
        self.auth.authorize(session,{'SECRETARIA'})
        return out.getvalue()

    def pdf(self,session,plan_id,kind):
        report=self.collect(session,plan_id,kind)
        out=BytesIO(); doc=SimpleDocTemplate(out,pagesize=landscape(A4),leftMargin=25,rightMargin=25,topMargin=28,bottomMargin=28)
        styles=getSampleStyleSheet(); cell_style=styles['BodyText'].clone('report_cell'); cell_style.fontSize=7; cell_style.leading=9
        def cell(value): return Paragraph(escape(str(value if value is not None else '')).replace('\n','<br/>'),cell_style)
        table_data=[[cell(x) for x in report['columns']]]+[[cell(x) for x in row] for row in report['rows']]
        if len(table_data)==1: table_data.append([cell('Sin registros')]+[cell('') for _ in report['columns'][1:]])
        table=LongTable(table_data,repeatRows=1,colWidths=[(landscape(A4)[0]-50)/len(report['columns'])]*len(report['columns']))
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dcefed')),('GRID',(0,0),(-1,-1),0.3,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP')]))
        title=Paragraph(escape(report['title']),styles['Title'])
        context=Paragraph(escape(f"Periodo: {report['period']} · Versión: {report['version']} · Estado: {report['state']}"),styles['Normal'])
        scope=Paragraph(escape(report['scope']),styles['Normal'])
        doc.build([title,context,scope,Spacer(1,12),table])
        self.auth.authorize(session,{'SECRETARIA'})
        return out.getvalue()
