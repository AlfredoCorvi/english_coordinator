"""CP-SAT para el modelo relacional, sin salones y con cobertura parcial."""
from collections import defaultdict
import time

from ortools.sat.python import cp_model


def overlap(first, second):
    return any(a['day']==b['day'] and a['starts']<b['ends'] and b['starts']<a['ends']
               for a in first for b in second)


def solve_snapshot(snapshot, excluded=None, minimum_coverage=0):
    start=time.monotonic()
    settings=snapshot['settings']
    students=[s for s in snapshot['students'] if s['level'] is not None and not s['exempt']]
    missing=[s['id'] for s in snapshot['students'] if s['level'] is None]
    exempt=[s['id'] for s in snapshot['students'] if s['level'] is not None and s['exempt']]
    teachers=snapshot['teachers']; blocks=snapshot['blocks']
    demand=defaultdict(list)
    for student in students:
        demand[student['cohort'],student['level']].append(student['id'])
    cells=list(sorted(demand))
    group_limit=min(len(students)//settings['min_size'],sum(min(t['max_blocks'],t['max_hours']//7,5 if t['employment_type']=='PTC' else 4 if t['employment_type']=='PA' else 0) for t in teachers))
    if group_limit == 0:
        has_empty=any(not p for p in (excluded or []))
        return {'status':'INFEASIBLE' if has_empty else 'NO_ASSIGNMENTS','message':'No existe otra organización válida con las entradas actuales.' if has_empty else 'No es posible formar grupos con los alumnos y recursos disponibles.',
                'groups':[],'assignments':[],'pending':[{'student':s['id'],'reason':'SIN_ASIGNACION'} for s in students]+[{'student':i,'reason':'SIN_NIVEL'} for i in missing],
                'exempt':exempt,'proven_stages':[],'seconds':time.monotonic()-start}
    model=cp_model.CpModel(); n=group_limit; maximum=settings['max_size']; minimum=settings['min_size']
    eligible_levels=sorted({s['level'] for s in students},key=lambda i:snapshot['levels'][i]['position'])
    opened={g:model.new_bool_var(f'open_{g}') for g in range(n)}
    counts={}; choice={}; level_used={}; cell_used={}; cohort_block={}; sizes={}; mixed={}; mixed_students=[]; deviations=[]; maxdev=model.new_int_var(0,maximum,'max_deviation')
    for cohort in sorted({key[0] for key in cells}):
        for bi in range(len(blocks)):
            cohort_block[cohort,bi]=model.new_bool_var(f'cohort_{cohort}_{bi}')
        model.add(sum(cohort_block[cohort,bi] for bi in range(len(blocks))) <= 1)
    for g in range(n):
        if g: model.add(opened[g-1]>=opened[g])
        for bi,b in enumerate(blocks):
            for ti,t in enumerate(teachers):
                if {s['id'] for s in b['slots']} <= set(t['availability']):
                    choice[g,bi,ti]=model.new_bool_var(f'choice_{g}_{bi}_{ti}')
        model.add(sum(v for (gg,_,_),v in choice.items() if gg==g)==opened[g])
        for level in eligible_levels:
            level_used[g,level]=model.new_bool_var(f'level_{g}_{level}')
        model.add(sum(level_used[g,l] for l in eligible_levels)<=2*opened[g])
        model.add(sum(level_used[g,l] for l in eligible_levels)>=opened[g])
        for i,l in enumerate(eligible_levels):
            for k in eligible_levels[i+1:]:
                if abs(snapshot['levels'][l]['position']-snapshot['levels'][k]['position'])!=1:
                    model.add(level_used[g,l]+level_used[g,k]<=1)
        for ci,(cohort,level) in enumerate(cells):
            count=model.new_int_var(0,len(demand[cohort,level]),f'count_{g}_{ci}'); counts[g,ci]=count
            used=model.new_bool_var(f'used_{g}_{ci}'); cell_used[g,ci]=used
            model.add(count<=len(demand[cohort,level])*used); model.add(count>=used)
            model.add(used<=level_used[g,level])
            for bi in range(len(blocks)):
                block_selected=sum(v for (gg,b,_),v in choice.items() if gg==g and b==bi)
                model.add(used+block_selected<=1+cohort_block[cohort,bi])
        for level in eligible_levels:
            model.add(sum(counts[g,ci] for ci,(_,l) in enumerate(cells) if l==level)>=level_used[g,level])
        sizes[g]=model.new_int_var(0,maximum,f'size_{g}')
        model.add(sizes[g]==sum(counts[g,ci] for ci in range(len(cells))))
        model.add(sizes[g]>=minimum*opened[g]); model.add(sizes[g]<=maximum*opened[g])
        mixed[g]=model.new_bool_var(f'mixed_{g}')
        model.add(sum(level_used[g,l] for l in eligible_levels)==opened[g]+mixed[g])
        mcount=model.new_int_var(0,maximum,f'mixed_count_{g}')
        model.add(mcount==sizes[g]).only_enforce_if(mixed[g]); model.add(mcount==0).only_enforce_if(mixed[g].Not())
        mixed_students.append(mcount)
        dev=model.new_int_var(0,maximum,f'deviation_{g}'); deviations.append(dev)
        model.add_abs_equality(dev,sizes[g]-settings['target_size']*opened[g]); model.add(maxdev>=dev)
    for ci,key in enumerate(cells): model.add(sum(counts[g,ci] for g in range(n))<=len(demand[key]))
    model.add(sum(sizes.values())>=minimum_coverage)
    # For alternatives, preserve aggregate counts but model each student's actual
    # membership so two partitions of an otherwise interchangeable cell differ.
    student_cell={student:key for key,members in demand.items() for student in members}
    block_index={b['id']:i for i,b in enumerate(blocks)}
    teacher_index={t['id']:i for i,t in enumerate(teachers)}
    membership={}
    if excluded:
        for ci,key in enumerate(cells):
            for student in demand[key]:
                for g in range(n):
                    membership[g,student]=model.new_bool_var(f'member_{g}_{student}')
                model.add(sum(membership[g,student] for g in range(n))<=1)
            for g in range(n):
                model.add(sum(membership[g,student] for student in demand[key])==counts[g,ci])
    for pi,previous in enumerate(excluded or []):
        if not previous:
            model.add(sum(opened.values())>=1)
            continue
        if len(previous)>n or any(g['block'] not in block_index or g['teacher'] not in teacher_index
                                  or any(s not in student_cell for s in g['students']) for g in previous):
            continue
        descriptors=[(block_index[g['block']],teacher_index[g['teacher']],set(g['students'])) for g in previous]
        matches=[]
        for g in range(n):
            for j,(bi,ti,required) in enumerate(descriptors):
                selected=choice.get((g,bi,ti))
                if selected is None: continue
                conditions=[selected]+[membership[g,s] if s in required else membership[g,s].Not() for s in student_cell]
                match=model.new_bool_var(f'excl_match_{pi}_{g}_{j}')
                model.add_bool_and(conditions).only_enforce_if(match)
                model.add_bool_or([c.Not() for c in conditions]+[match])
                matches.append(match)
        if matches:
            same_count=model.new_bool_var(f'excl_group_count_{pi}')
            model.add(sum(opened.values())==len(previous)).only_enforce_if(same_count)
            model.add(sum(opened.values())!=len(previous)).only_enforce_if(same_count.Not())
            model.add(sum(matches)<=len(previous)-1).only_enforce_if(same_count)
    for ti,t in enumerate(teachers):
        choices=[v for (g,b,k),v in choice.items() if k==ti]
        cap=min(t['max_blocks'],5 if t['employment_type']=='PTC' else 4 if t['employment_type']=='PA' else 0)
        model.add(sum(choices)<=cap); model.add(7*sum(choices)<=min(t['max_hours'],35 if t['employment_type']=='PTC' else t['max_hours']))
        for g in range(n):
            for h in range(g+1,n):
                for bi in range(len(blocks)):
                    for bj in range(len(blocks)):
                        if (g,bi,ti) in choice and (h,bj,ti) in choice and overlap(blocks[bi]['slots'],blocks[bj]['slots']):
                            model.add(choice[g,bi,ti]+choice[h,bj,ti]<=1)
    # The number of used groups for a cell minus its presence is its fragmentation.
    fragment=[]; presence={}
    for ci,key in enumerate(cells):
        present=model.new_bool_var(f'present_{ci}')
        presence[ci]=present
        model.add_max_equality(present,[cell_used[g,ci] for g in range(n)])
        fragment.append(sum(cell_used[g,ci] for g in range(n))-present)
    # A previous audited organization often has an unused compatible teacher.
    # Suggesting that real alternative helps CP-SAT find a feasible incumbent;
    # hints do not add constraints or change the lexicographic objectives.
    if excluded and membership:
        def signature(groups):
            return sorted(((g['block'],g['teacher'],tuple(sorted(g['students']))) for g in groups),key=repr)
        known=[signature(p) for p in excluded]
        hint=None
        for old in reversed(excluded):
            if not old or len(old)>n or any(g['block'] not in block_index or g['teacher'] not in teacher_index or
                    any(s not in student_cell for s in g['students']) for g in old):
                continue
            used_teachers={g['teacher'] for g in old}
            for gi,group in enumerate(old):
                bi=block_index[group['block']]
                for ti,teacher in enumerate(teachers):
                    if teacher['id'] in used_teachers or teacher['employment_type'] not in ('PA','PTC') or teacher['max_hours']<7 or teacher['max_blocks']<1:
                        continue
                    if (gi,bi,ti) not in choice: continue
                    candidate=[dict(g,students=list(g['students'])) for g in old]
                    candidate[gi]['teacher']=teacher['id']
                    if signature(candidate) not in known:
                        hint=candidate; break
                if hint: break
            if hint: break
        if hint:
            by_group={g:set(item['students']) for g,item in enumerate(hint)}
            assigned_blocks={}
            for g,item in enumerate(hint):
                for student in item['students']:
                    assigned_blocks[student_cell[student][0]]=block_index[item['block']]
            for g in range(n):
                active=g<len(hint); members=by_group.get(g,set()); size=len(members)
                model.add_hint(opened[g],int(active)); model.add_hint(sizes[g],size)
                actual_levels={student_cell[s][1] for s in members}
                model.add_hint(mixed[g],int(len(actual_levels)==2))
                model.add_hint(mixed_students[g],size if len(actual_levels)==2 else 0)
                model.add_hint(deviations[g],abs(size-settings['target_size']) if active else 0)
                for level in eligible_levels: model.add_hint(level_used[g,level],int(level in actual_levels))
                for ci,key in enumerate(cells):
                    amount=sum(s in members for s in demand[key])
                    model.add_hint(counts[g,ci],amount); model.add_hint(cell_used[g,ci],int(amount>0))
                for student in student_cell: model.add_hint(membership[g,student],int(student in members))
            for (g,bi,ti),var in choice.items():
                selected=g<len(hint) and hint[g]['block']==blocks[bi]['id'] and hint[g]['teacher']==teachers[ti]['id']
                model.add_hint(var,int(selected))
            for (cohort,bi),var in cohort_block.items(): model.add_hint(var,int(assigned_blocks.get(cohort)==bi))
            for ci,key in enumerate(cells): model.add_hint(presence[ci],int(any(s in members for members in by_group.values() for s in demand[key])))
            model.add_hint(maxdev,max((abs(len(g['students'])-settings['target_size']) for g in hint),default=0))
    objectives=[('cobertura',sum(sizes.values()),True),('multinivel',sum(mixed_students),False),
                ('fragmentacion',sum(fragment),False),('cupo_ideal',sum(deviations),False),('equilibrio',maxdev,False)]
    solver=None; proven=[]; status=None
    for name,expr,maximize in objectives:
        remaining=settings['solver_seconds']-(time.monotonic()-start)
        if remaining<=0: break
        model.maximize(expr) if maximize else model.minimize(expr)
        candidate=cp_model.CpSolver(); candidate.parameters.max_time_in_seconds=remaining; candidate.parameters.num_search_workers=8
        status=candidate.solve(model)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            break
        solver=candidate
        if status!=cp_model.OPTIMAL: break
        value=round(candidate.objective_value); proven.append({'stage':name,'value':value})
        model.add(expr==value)
    if solver is None:
        label='INFEASIBLE' if status==cp_model.INFEASIBLE else 'TIMEOUT'
        message=('No existe otra organización válida que conserve la cobertura alcanzada.' if label=='INFEASIBLE' and excluded else
                 'No se encontró una solución; revisa el estado y tiempo de búsqueda.')
        return {'status':label,'message':message, 'groups':[],'assignments':[],
                'pending':[{'student':s['id'],'reason':'SIN_SOLUCION'} for s in students]+[{'student':i,'reason':'SIN_NIVEL'} for i in missing],
                'exempt':exempt,'proven_stages':proven,'seconds':time.monotonic()-start}
    groups=[]; assignments=[]; offset=defaultdict(int)
    for g in range(n):
        if not solver.value(opened[g]): continue
        bi,ti=next((b,t) for (gg,b,t),v in choice.items() if gg==g and solver.value(v))
        gid=f'ING-{len(groups)+1:03}'
        groups.append({'id':gid,'block':blocks[bi]['id'],'teacher':teachers[ti]['id'],
                       'levels':[l for l in eligible_levels if solver.value(level_used[g,l])]})
        for ci,key in enumerate(cells):
            amount=solver.value(counts[g,ci])
            if membership:
                members=[sid for sid in demand[key] if solver.value(membership[g,sid])]
            else:
                members=demand[key][offset[key]:offset[key]+amount]; offset[key]+=amount
            assignments.extend({'student':s,'group':gid} for s in members)
    assigned={a['student'] for a in assignments}
    pending=[{'student':s['id'],'reason':'SIN_ASIGNACION'} for s in students if s['id'] not in assigned]+[{'student':i,'reason':'SIN_NIVEL'} for i in missing]
    status='OPTIMAL' if len(proven)==len(objectives) else 'FEASIBLE'
    if not assignments and students and proven and proven[0]['value']==0:
        status='NO_ASSIGNMENTS'
    message=('Cobertura completa.' if not pending else 'Propuesta parcial: hay alumnos pendientes.')
    if status=='FEASIBLE': message+=' No se demostraron todas las prioridades óptimas.'
    if status=='NO_ASSIGNMENTS': message='No se pudo asignar ningún alumno elegible.'
    return {'status':status,'message':message,
            'groups':groups,'assignments':assignments,'pending':pending,'exempt':exempt,'proven_stages':proven,'seconds':time.monotonic()-start}
