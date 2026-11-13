from pathlib import Path
import re

from streamlit.testing.v1 import AppTest

from ingles.storage import Store
from ingles.domain import DAYS, empty_bundle

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_coordinator_workflow(tmp_path, monkeypatch):
    db = tmp_path / "app.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(db))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    button(at, "Cargar datos de demostración").click().run()
    assert not at.exception
    assert len(Store(db).load()[0]["students"]) == 180
    at.radio(key="nav").set_value("Bloques y reglas").run()
    assert not at.exception
    assert any("Esta regla es obligatoria" in message.value for message in at.info)
    assert not any("mismo bloque" in checkbox.label for checkbox in at.checkbox)
    at.radio(key="nav").set_value("Generar").run()
    button(at, "Generar propuesta").click().run()
    assert not at.exception
    assert at.radio(key="nav").value == "Resultados"
    assert len(Store(db).plans()) == 1
    button(at, "Preparar Excel y PDF").click().run()
    assert not at.exception
    assert at.session_state["exports"]["excel"][:2] == b"PK"
    assert at.session_state["exports"]["career_excel"][:2] == b"PK"
    assert at.session_state["exports"]["pdf"][:4] == b"%PDF"
    at.radio(key="nav").set_value("Auditoría").run()
    assert not at.exception
    assert any("sin errores" in s.value for s in at.success)
    at.radio(key="nav").set_value("Resultados").run()
    button(at, "Auditar y guardar nueva versión").click().run()
    assert not at.exception
    assert len(Store(db).plans()) == 2
    # A later input change makes exports unavailable until a fresh audit is saved.
    store = Store(db)
    bundle, rev = store.load()
    bundle["students"][0]["Nombre"] = "Nombre corregido"
    store.save(bundle, rev, "Corrección")
    at.run()
    assert not at.exception
    assert any("cambiaron" in w.value for w in at.warning)
    assert not any(b.label == "Preparar Excel y PDF" for b in at.button)
    restarted = AppTest.from_file(APP, default_timeout=30).run()
    assert not restarted.exception
    assert next(m for m in restarted.metric if m.label == "Alumnos").value == "180"


def test_audit_calendar_filters_english_groups_and_distinguishes_careers(tmp_path, monkeypatch):
    path = tmp_path / "calendar.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(path))
    bundle = empty_bundle()
    bundle["blocks"] = [{"Bloque": "Común", "Lunes": "1,2", "Martes": "1,2", "Miércoles": "1", "Jueves": "1", "Viernes": "1"}]
    plan = {"groups": [], "assignments": []}
    for i, (career, level) in enumerate([("Diseño", "A1"), ("Diseño", "B1"), ("Medicina", "C1")], 1):
        sid, tid, rid, gid = f"000{i}", f"D{i}", f"R{i}", f"ING-{i:03}"
        bundle["students"].append({"Matricula": sid, "Nombre": f"Alumno {i}", "Carrera": career,
                                   "Grupo": "1A", "Nivel": level, "Edificio": "1", "Bloque fijo": ""})
        bundle["teachers"].append({"ID": tid, "matricula_docente": tid, "Nombre": f"Docente {i}",
                                   "Edificios": "1", "Horas máximas": "6", **{d: "*" for d in DAYS}})
        bundle["rooms"].append({"ID": rid, "Salón": str(100 + i), "Edificio": "1", "Capacidad": "30", **{d: "*" for d in DAYS}})
        plan["groups"].append({"id": gid, "level": level[0], "block": "Común", "teacher": tid, "room": rid})
        plan["assignments"].append({"student": sid, "group": gid})
    store = Store(path)
    revision = store.save(bundle, 0, "Calendario de prueba")
    store.save_plan(plan, revision, "Tres grupos simultáneos")
    at = AppTest.from_file(APP).run()
    at.radio(key="nav").set_value("Auditoría").run()

    def visible_groups():
        assert not at.exception and not at.error
        calendar = at.tabs[0].dataframe[0].value
        cells = [str(value) for value in calendar.to_numpy().flatten()]
        assert sum("ING-" in value for value in cells) == 7
        assert sum("Receso" in value for value in cells) == 5
        return set(re.findall(r"ING-\d+", "\n".join(cells)))

    at.radio(key="audit_calendar_kind").set_value("Grupo de inglés").run()
    at.selectbox(key="audit_english_group").set_value("ING-002").run()
    assert visible_groups() == {"ING-002"}
    at.radio(key="audit_calendar_kind").set_value("Grupo de carrera").run()
    at.selectbox(key="audit_career").set_value("Diseño").run()
    assert at.selectbox(key="audit_career_group").value == "1A"
    assert visible_groups() == {"ING-001", "ING-002"}
    at.selectbox(key="audit_career").set_value("Medicina").run()
    assert at.selectbox(key="audit_career_group").value == "1A"
    assert visible_groups() == {"ING-003"}
    for view, expected in [("Docente", {"ING-001"}), ("Salón", {"ING-001"}), ("Bloque", {"ING-001", "ING-002", "ING-003"})]:
        at.radio(key="audit_calendar_kind").set_value(view).run()
        assert visible_groups() == expected
