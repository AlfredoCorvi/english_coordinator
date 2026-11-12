from pathlib import Path

from streamlit.testing.v1 import AppTest

from ingles.storage import Store

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
