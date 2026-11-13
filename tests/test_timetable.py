from copy import deepcopy
from datetime import time
from io import BytesIO
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from ingles.audit import audit, errors_only
from ingles.domain import (DAYS, DEFAULT_SETTINGS, block_minutes, daily_agenda, daily_periods,
                           empty_bundle, period_count, period_label, time_minutes, validate_settings)
from ingles.exchange import export_excel, reservations, schedule_rows, teacher_load
from ingles.reports import export_pdf
from ingles.scheduler import solve
from ingles.storage import ConcurrentEdit, Store


@pytest.fixture
def around_break():
    b = empty_bundle()
    b["students"] = [{"Matricula": "00001", "Nombre": "Ana", "Carrera": "Diseño", "Grupo": "1A",
                      "Nivel": "Basic 1", "Edificio": "1", "Bloque fijo": "B1"}]
    b["teachers"] = [{"ID": "D1", "matricula_docente": "D1", "Nombre": "Docente", "Edificios": "1", "Horas máximas": "6", **{d: "*" for d in DAYS}}]
    b["rooms"] = [{"ID": "R1", "Salón": "101", "Edificio": "1", "Capacidad": "30", **{d: "*" for d in DAYS}}]
    b["blocks"] = [{"Bloque": "B1", "Lunes": "6,7", "Martes": "7", "Miércoles": "7", "Jueves": "7", "Viernes": "7,8"}]
    return b


def test_default_day_skips_break_without_losing_periods():
    s = DEFAULT_SETTINGS
    rows = daily_periods(s)
    assert s["period_minutes"] == 45
    assert [(r["start"], r["end"]) for r in rows] == [
        (420, 465), (465, 510), (510, 555), (555, 600),
        (600, 645), (645, 690), (715, 760), (760, 805), (805, 850), (850, 895), (895, 940)]
    assert sum(r["kind"] == "class" for r in daily_agenda(s)) == 11
    assert sum(r["kind"] == "break" for r in daily_agenda(s)) == 1
    assert block_minutes(s) == 315


@pytest.mark.parametrize("start,duration,expected", [
    ("10:45", 45, "10:45–11:30"),
    ("11:30", 45, "11:55–12:40"),
    ("11:40", 45, "11:55–12:40"),
    ("11:55", 45, "11:55–12:40"),
    ("11:00", 60, "11:55–12:55"),
    ("10:00", 120, "11:55–13:55"),
    ("11:29", 1, "11:29–11:30"),
])
def test_periods_at_break_boundaries(start, duration, expected):
    s = dict(DEFAULT_SETTINGS, start_time=start, period_minutes=duration, periods_per_day=1)
    assert not validate_settings(s)
    assert period_label(s, 1) == expected
    row = daily_periods(s)[0]
    assert row["end"] - row["start"] == duration


@pytest.mark.parametrize("change", [
    {"period_minutes": 0}, {"period_minutes": 181}, {"period_minutes": True}, {"period_minutes": 45.5},
    {"break_start": "11:55", "break_end": "11:30"}, {"break_start": "11:55", "break_end": "11:55"},
    {"break_start": ""}, {"break_end": "25:00"}, {"start_time": "24:00"},
    {"start_time": "23:00", "periods_per_day": 1, "period_minutes": 60, "break_start": "23:30", "break_end": "23:55"},
])
def test_invalid_duration_break_or_day_end(change):
    assert validate_settings(dict(DEFAULT_SETTINGS, **change))


def test_break_outside_day_does_not_shift_classes():
    s = dict(DEFAULT_SETTINGS, start_time="14:00", periods_per_day=2)
    assert period_label(s, 1) == "14:00–14:45"
    assert period_label(s, 2) == "14:45–15:30"
    assert all(r["kind"] == "class" for r in daily_agenda(s))


def test_generated_classes_and_reservations_never_occupy_break(around_break):
    result = solve(around_break)
    assert result.success, result.message
    assert not errors_only(audit(around_break, result.payload()))
    rows = schedule_rows(around_break, result.payload())
    assert len(rows) == 7
    assert "10:45–11:30" in {r["Horario"] for r in rows}
    assert "11:55–12:40" in {r["Horario"] for r in rows}
    for row in rows:
        start, end = map(time_minutes, row["Horario"].split("–"))
        assert end - start == 45
        assert end <= 690 or start >= 715
    assert len(reservations(around_break, result.payload())) == 7
    loads = teacher_load(around_break, result.payload())
    assert loads[0]["Horas asignadas"] == 5.25
    assert loads[0]["Horas libres"] == .75


def test_teacher_limits_use_actual_minutes(around_break):
    assert solve(around_break).success  # 6 clock hours suffice for seven 45-minute periods.
    around_break["teachers"][0]["Horas máximas"] = "5"
    assert solve(around_break).status == "INFEASIBLE"
    around_break["settings"]["period_minutes"] = 90
    around_break["blocks"][0].update(Lunes="1,2", Martes="1,2", **{"Miércoles": "1", "Jueves": "1", "Viernes": "1"})
    around_break["teachers"][0]["Horas máximas"] = "10"
    assert solve(around_break).status == "INFEASIBLE"  # 630 minutes > 600.
    around_break["teachers"][0]["Horas máximas"] = "11"
    result = solve(around_break)
    assert result.success
    assert teacher_load(around_break, result.payload())[0]["Horas asignadas"] == 10.5
    around_break["teachers"][0]["Horas máximas"] = "10"
    assert "Carga docente" in {r["Regla"] for r in audit(around_break, result.payload())}


def test_independent_auditor_detects_overlapping_clock_period(around_break, monkeypatch):
    import importlib
    audit_module = importlib.import_module("ingles.audit")
    plan = solve(around_break).payload()
    bad_grid = daily_periods(around_break["settings"])
    bad_grid[6].update(start=690, end=735)
    monkeypatch.setattr(audit_module, "daily_periods", lambda _: bad_grid)
    assert "Receso" in {r["Regla"] for r in audit_module.audit(around_break, plan)}


def test_exports_show_break_and_actual_duration(around_break):
    plan = solve(around_break).payload()
    book = load_workbook(BytesIO(export_excel(around_break, plan)))
    assert list(book["Jornada"].values)[7] == ("Receso", "11:30", "11:55", 25, "No")
    assert "11:55–12:40" in {row[4] for row in list(book["Horarios"].values)[1:]}
    assert book["Carga docente"]["C2"].value == 5.25
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(export_pdf(around_break, plan))).pages)
    assert "45 min" in text and "5 h 15 min" in text
    assert "11:30" in text and "11:55" in text and "Receso" in text


def test_legacy_jornada_migration_preserves_history(tmp_path, around_break):
    path = tmp_path / "legacy.sqlite3"
    store = Store(path)
    old = deepcopy(around_break)
    old["settings"].pop("break_start")
    old["settings"].pop("break_end")
    old["settings"]["period_minutes"] = 60
    with store.connect() as db:
        old_rev = db.execute("INSERT INTO revisions(created, note, payload) VALUES (?, ?, ?)",
                             ("2026-11-11", "Jornada anterior", json.dumps(old))).lastrowid
    plan = solve(around_break).payload()
    plan_id = store.save_plan(plan, old_rev, "Anterior")
    migrated = Store(path)
    new, rev = migrated.load()
    assert new == around_break
    assert rev == old_rev + 1
    assert migrated.get_plan(plan_id)["revision"] == old_rev
    assert Store(path).load()[1] == rev
    with migrated.connect() as db:
        assert json.loads(db.execute("SELECT payload FROM revisions WHERE id=?", (old_rev,)).fetchone()[0]) == old
    new["settings"].update(period_minutes=50, break_start="10:20", break_end="10:45")
    new["settings"]["periods_per_day"] = period_count(new["settings"])
    migrated.save(new, rev, "Personalizado")
    assert Store(path).load()[0]["settings"] == new["settings"]
    with pytest.raises(ConcurrentEdit):
        store.save_plan(plan, old_rev, "Sesión antigua")


def test_rules_ui_persists_duration_and_break_and_invalidates_plan(tmp_path, monkeypatch, around_break):
    path = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(path))
    store = Store(path)
    old_revision = store.save(around_break, 0, "Inicial")
    old_plan = store.save_plan(solve(around_break).payload(), old_revision, "Inicial")
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    at.radio(key="nav").set_value("Bloques y reglas").run()
    duration = next(w for w in at.number_input if w.label == "Duración de cada periodo (minutos)")
    assert duration.value == 45
    inputs = {w.label: w for w in at.time_input}
    assert inputs["Inicio del receso"].value == time(11, 30)
    assert inputs["Fin del receso"].value == time(11, 55)
    duration.set_value(50)
    inputs["Inicio del receso"].set_value(time(10, 20))
    inputs["Fin del receso"].set_value(time(10, 45))
    next(b for b in at.button if b.label == "Guardar reglas").click().run()
    assert not at.exception
    saved, revision = Store(path).load()
    assert store.get_plan(old_plan)["revision"] != revision
    assert (saved["settings"]["period_minutes"], saved["settings"]["break_start"], saved["settings"]["break_end"]) == (50, "10:20", "10:45")
    next(w for w in at.time_input if w.label == "Fin del receso").set_value(time(10, 0))
    next(b for b in at.button if b.label == "Guardar reglas").click().run()
    assert not at.exception
    assert at.error
    assert Store(path).load()[1] == revision
    at.radio(key="nav").set_value("Resultados").run()
    assert not at.exception
    assert any("cambiaron" in warning.value for warning in at.warning)
    assert not any(b.label == "Preparar Excel y PDF" for b in at.button)
