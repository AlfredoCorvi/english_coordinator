"""Escenario ficticio aislado; nunca reemplaza datos preexistentes."""
from datetime import datetime, timezone
from pathlib import Path
import os


class DemoService:
    def __init__(self,store,auth):
        self.store,self.auth=store,auth

    def load(self,session):
        actor=self.auth.authorize(session,{'SECRETARIA'})
        path=os.environ.get('INGLES_DEMO_DB_PATH')
        if os.environ.get('INGLES_DEMO_MODE')!='1' or not path or Path(path).resolve()!=self.store.path.resolve():
            raise ValueError('Activa INGLES_DEMO_MODE=1 y configura INGLES_DEMO_DB_PATH con la base separada del escenario.')
        if self.store.path.resolve()==Path(os.environ.get('INGLES_DB_PATH','data/ingles.sqlite3')).resolve():
            raise ValueError('La base de demostración debe ser distinta de la base anterior.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.auth.authorize(session,{'SECRETARIA'})
            existing=db.execute("SELECT period_id FROM demo_scenarios WHERE id='escenario-v1'").fetchone()
            if existing:
                return {'period_id':existing[0],'created':False}
            if db.execute('SELECT count(*) FROM users').fetchone()[0]!=1:
                raise ValueError('La base contiene otras cuentas: usa una base de demostración nueva y separada.')
            for table in ('periods','students','teachers','careers','academic_groups','enrollments','settings',
                          'time_slots','block_versions','plans','level_decisions','incidents','history','sync_runs'):
                if db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                    raise ValueError('La base ya contiene datos académicos: usa una base de demostración nueva y separada.')
            now=datetime.now(timezone.utc).isoformat()
            period=db.execute("INSERT INTO periods(code,start_date,end_date) VALUES ('DEMO-SEP-DIC-2026','2026-09-01','2026-12-31')").lastrowid
            db.execute("INSERT INTO periods(code,start_date,end_date) VALUES ('DEMO-ENE-ABR-2027','2027-01-01','2027-04-30')")
            careers=[]; cohorts=[]
            for i in range(4):
                careers.append(db.execute("INSERT INTO careers(provider,external_id,name) VALUES ('demo',?,?)",(f'C{i+1}',f'Carrera ficticia {i+1}')).lastrowid)
            for i in range(10):
                cohorts.append(db.execute("INSERT INTO academic_groups(career_id,provider,external_id,code) VALUES (?,'demo',?,?)",(careers[i%4],f'G{i+1}',f'DEMO-{i+1:02}')).lastrowid)
            for i in range(200):
                active=i<190
                sid=db.execute("INSERT INTO students(provider,external_id,enrollment,name,building,shift,school_status) VALUES ('demo',?,?,?,?,?,?)",(f'S{i+1:03}',f'DEMO{i+1:04}',f'Alumno ficticio {i+1:03}',str(i%4+1),'Matutino','Activo' if active else 'Inactivo')).lastrowid
                eid=db.execute('INSERT INTO enrollments(student_id,period_id,academic_group_id,active) VALUES (?,?,?,?)',(sid,period,cohorts[i%10],int(active))).lastrowid
                db.execute('INSERT INTO enrollment_snapshots VALUES (?,?,?,?,?,?,?,?)',(eid,f'Alumno ficticio {i+1:03}',f'DEMO{i+1:04}',f'Carrera ficticia {(i%10)%4+1}',f'DEMO-{i%10+1:02}',str(i%4+1),'Matutino','Activo' if active else 'Inactivo'))
                level=6 if i<7 else 7 if i<12 else (i%10)%5+1
                if 158<=i<178: level=9 if i%2==0 else 10
                if not 178<=i<190:
                    db.execute("INSERT INTO level_decisions(student_id,target_period_id,level_id,actor_id,decided_at,reason) VALUES (?,?,?,?,?,'Escenario ficticio')",(sid,period,level,actor,now))
            times=[('08:30','09:15'),('09:15','10:00'),('10:00','10:45'),('10:45','11:30'),
                   ('11:55','12:40'),('12:40','13:25'),('13:25','14:10'),('14:10','14:55')]
            slot={}
            for day in range(1,6):
                for index,(start,end) in enumerate(times):
                    slot[day,index]=db.execute("INSERT INTO time_slots(calendar_version,day,slot_number,starts,ends) VALUES ('DEMO-FICTICIO',?,?,?,?)",(day,index+1,start,end)).lastrowid
            pairs=[(0,1),(1,2),(2,3),(4,5),(6,7)]; block_slots=[]
            for index,(a,b) in enumerate(pairs):
                ids=[slot[d,h] for d in range(1,6) for h in ((a,b) if d<=2 else (a,))]
                version=db.execute('INSERT INTO block_versions(block_id,version) VALUES (?,1)',(index+1,)).lastrowid
                db.executemany('INSERT INTO block_slots VALUES (?,?)',[(version,s) for s in ids])
                db.execute('INSERT INTO period_blocks(period_id,block_version_id,active) VALUES (?,?,1)',(period,version)); block_slots.append(ids)
            all_slots=set(s for group in block_slots for s in group)
            for i in range(12):
                typ='PTC' if i<5 else 'PA'; subject='docente.demo' if i==0 else f'docente.demo.{i+1:02}'
                tid=db.execute("INSERT INTO teachers(provider,external_id,name,employment_type) VALUES ('demo',?,?,?)",(f'D{i+1:02}',f'Docente ficticio {i+1:02}',typ)).lastrowid
                uid=db.execute("INSERT INTO users(identity_provider,subject,teacher_id) VALUES ('desarrollo',?,?)",(subject,tid)).lastrowid
                db.execute("INSERT INTO user_roles VALUES (?,'DOCENTE')",(uid,))
                hours=35 if typ=='PTC' else 26 if i%2 else 28; limit=5 if typ=='PTC' else 4
                rid=db.execute('INSERT INTO teacher_period_rules(teacher_id,period_id,participates,max_hours,max_blocks) VALUES (?,?,1,?,?)',(tid,period,hours,limit)).lastrowid
                availability=all_slots if i<8 else set(block_slots[(i-8)%5]) if i<11 else set()
                db.executemany('INSERT INTO teacher_availability VALUES (?,?)',[(rid,s) for s in sorted(availability)])
            db.execute('INSERT INTO settings(period_id,version,min_size,target_size,max_size,solver_seconds) VALUES (?,1,8,28,35,60)',(period,))
            db.execute('INSERT INTO demo_scenarios VALUES (?,?,?)',('escenario-v1',period,now))
            return {'period_id':period,'created':True}
