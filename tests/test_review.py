from copy import deepcopy
from datetime import time
from io import BytesIO
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from ingles.audit import audit, errors_only
from ingles.domain import (DAYS, DEFAULT_SETTINGS, canonical_rows, daily_periods, demo_bundle,
                           period_count, propose_blocks, slots, validate_settings, validate_table)
from ingles.exchange import (HEADERS, export_career_excel, map_rows, read_excel,
                             suggested_mapping, template_excel)
from ingles.scheduler import solve
from ingles.storage import Store

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def sample():
    b = demo_bundle()
    b["students"] = [dict(b["students"][0], Matricula=f"{i:05}", Nombre=f"Alumno {i}") for i in range(10)]
    b["teachers"] = b["teachers"][:1]
    b["rooms"] = b["rooms"][:1]
    b["settings"]["solver_seconds"] = 3
    return b


def test_search_limit_can_be_saved_reloaded_and_used_by_solver(tmp_path, monkeypatch, sample):
    from ortools.sat.python import cp_model

    path = tmp_path / "search_limit.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(path))
    sample["settings"]["solver_seconds"] = 30  # A saved value predating the new default.
    store = Store(path)
    revision = store.save(sample, 0, "Inicial")
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.radio(key="nav").set_value("Bloques y reglas").run()
    control = next(w for w in at.number_input if w.label == "Tiempo máximo de búsqueda (segundos)")
    assert control.value == 30
    assert control.proto.min == 1 and control.proto.max == 300
    control.set_value(120)
    next(b for b in at.button if b.label == "Guardar reglas").click().run()
    assert not at.exception
    saved, new_revision = store.load()
    assert new_revision == revision + 1
    assert saved["settings"]["solver_seconds"] == 120
    assert all(saved[kind] == sample[kind] for kind in ("students", "teachers", "rooms", "blocks"))

    restarted = AppTest.from_file(APP, default_timeout=30).run()
    restarted.radio(key="nav").set_value("Bloques y reglas").run()
    assert not restarted.exception
    assert next(w for w in restarted.number_input if w.label == "Tiempo máximo de búsqueda (segundos)").value == 120

    limits = []
    original_solve = cp_model.CpSolver.solve

    def record_limit(solver, *args, **kwargs):
        limits.append(solver.parameters.max_time_in_seconds)
        return original_solve(solver, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "solve", record_limit)
    restarted.radio(key="nav").set_value("Generar").run()
    next(b for b in restarted.button if b.label == "Generar propuesta").click().run()
    assert not restarted.exception
    assert limits == [120]
    assert restarted.radio(key="nav").value == "Resultados"
    plan = store.get_plan(store.plans()[0]["id"])
    assert plan["revision"] == new_revision
    assert not errors_only(audit(saved, plan["payload"]))


def test_full_day_and_templates_use_final_periods():
    s = dict(DEFAULT_SETTINGS, start_time="08:30", end_time="15:40")
    assert not validate_settings(s)
    periods = daily_periods(s)
    assert len(periods) == 9
    assert periods[-1] == {"period": 9, "start": 895, "end": 940}
    used = set()
    for block in propose_blocks(9):
        times = slots(block, 9)
        assert len(times) == 7 and not times & used
        used |= times
    assert {(d, 9) for d in DAYS} <= used
    assert all(r["end"] <= 940 and (r["end"] <= 690 or r["start"] >= 715) for r in periods)


@pytest.mark.parametrize("daily", [2, 8, 9, 11])
def test_requested_block_count_preserves_seven_periods_and_no_overlap(daily):
    maximum = daily * len(DAYS) // 7
    for desired in range(1, maximum + 1):
        blocks = propose_blocks(daily, desired)
        assert len(blocks) == desired
        assert [b["Bloque"] for b in blocks] == [f"Bloque {i + 1}" for i in range(desired)]
        occupied = set()
        for block in blocks:
            times = slots(block, daily)
            assert len(times) == 7 and not occupied & times
            occupied |= times
        if desired > 1:
            assert min(p for _, p in occupied) == 1
            assert max(p for _, p in occupied) == daily


@pytest.mark.parametrize("desired", [0, -1, 1.5, True, 8])
def test_invalid_requested_block_count_is_rejected(desired):
    with pytest.raises(ValueError):
        propose_blocks(11, desired)


def test_block_quantity_is_reviewed_then_persisted(tmp_path, monkeypatch, sample):
    path = tmp_path / "block_count.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(path))
    store = Store(path)
    revision = store.save(sample, 0, "Inicial")
    at = AppTest.from_file(APP).run()
    at.radio(key="nav").set_value("Bloques y reglas").run()
    at.session_state["rule_tabs"] = "Bloques semanales"
    at.run()
    count = next(w for w in at.number_input if w.label == "Cantidad de bloques a proponer")
    assert count.value == len(sample["blocks"])
    count.set_value(5).run()
    next(b for b in at.button if b.label == "Proponer bloques sin superposición").click().run()
    assert not at.exception
    assert len(at.session_state[f"draft_blocks_{revision}"]) == 5
    assert store.load() == (sample, revision)  # Preview never overwrites saved blocks.
    at.button(key="save_blocks").click().run()
    saved, new_revision = store.load()
    assert not at.exception and new_revision == revision + 1
    assert len(saved["blocks"]) == 5
    assert at.session_state["rule_tabs"] == "Bloques semanales"
    assert not validate_table("blocks", saved["blocks"], saved["settings"])
    restarted = AppTest.from_file(APP).run()
    restarted.radio(key="nav").set_value("Bloques y reglas").run()
    assert not restarted.exception
    assert next(w for w in restarted.number_input if w.label == "Cantidad de bloques a proponer").value == 5


def test_short_week_cannot_propose_blocks(tmp_path, monkeypatch, sample):
    path = tmp_path / "short_week.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(path))
    sample["settings"]["end_time"] = "07:45"
    Store(path).save(sample, 0, "Un periodo al día")
    at = AppTest.from_file(APP).run()
    at.radio(key="nav").set_value("Bloques y reglas").run()
    assert not at.exception
    assert next(b for b in at.button if b.label == "Proponer bloques sin superposición").disabled
    assert any("menos de siete periodos" in w.value for w in at.warning)
    with pytest.raises(ValueError, match="máximo 0"):
        propose_blocks(1, 1)


def test_solver_can_use_only_last_periods(sample):
    sample["settings"].update(start_time="08:30", end_time="15:40")
    block = {"Bloque": "Tarde", **{d: "9" for d in DAYS}}
    block.update(Lunes="8,9", Martes="8,9")
    sample["blocks"] = [block]
    for kind in ("teachers", "rooms"):
        sample[kind][0].update({d: block[d] for d in DAYS})
    result = solve(sample)
    assert result.success, result.message
    assert {g["block"] for g in result.groups} == {"Tarde"}
    assert not errors_only(audit(sample, result.payload()))


def test_maximum_35_and_room_capacity_both_enforced(sample):
    sample["settings"]["max_group"] = 35
    sample["rooms"][0]["Capacidad"] = "35"
    sample["students"] = [dict(sample["students"][0], Matricula=str(i)) for i in range(35)]
    assert len(solve(sample).groups) == 1
    sample["rooms"][0]["Capacidad"] = "30"
    result = solve(sample)
    assert result.status == "INFEASIBLE" and result.diagnostics
    assert validate_settings(dict(DEFAULT_SETTINGS, max_group=36))


@pytest.mark.parametrize("changes", [
    {"end_time": "07:00"}, {"end_time": "06:00"}, {"end_time": "24:00"},
    {"end_time": "07:30"}, {"start_time": "11:30", "end_time": "11:55"},
])
def test_invalid_day_end(changes):
    assert validate_settings(dict(DEFAULT_SETTINGS, **changes))


def test_import_uses_public_keys_preserves_internal_references(sample):
    for kind in ("teachers", "rooms"):
        headers, rows = read_excel(template_excel(kind, sample), kind)
        assert "ID" not in headers
        parsed = map_rows(kind, rows, suggested_mapping(kind, headers), sample[kind])
        assert parsed == sample[kind]
        assert parsed[0]["ID"] == sample[kind][0]["ID"]
        new = map_rows(kind, rows, suggested_mapping(kind, headers))
        assert new[0]["ID"]
    duplicate = dict(sample["teachers"][0], ID="different-internal-id")
    assert any("matrícula docente duplicada" in e for e in validate_table("teachers", [sample["teachers"][0], duplicate], sample["settings"]))
    edited = canonical_rows("teachers", [dict(sample["teachers"][0], matricula_docente="000033")])
    assert edited[0]["ID"] == sample["teachers"][0]["ID"]


def test_migration_preserves_catalogs_plans_and_history(tmp_path, sample):
    store = Store(tmp_path / "old.sqlite3")
    old = deepcopy(sample)
    old["settings"].pop("end_time")
    old["settings"].update(periods_per_day=8, transfer_periods=4)
    old["teachers"][0].pop("matricula_docente")
    with store.connect() as db:
        rev = db.execute("INSERT INTO revisions(created,note,payload) VALUES(?,?,?)", ("2026-11-12", "Anterior", json.dumps(old))).lastrowid
    pid = store.save_plan(solve(sample).payload(), rev, "Anterior")
    updated = Store(store.path)
    b, new_rev = updated.load()
    assert new_rev == rev + 1
    assert b["settings"]["end_time"] == "15:45" and b["settings"]["periods_per_day"] == 11
    assert "transfer_periods" not in b["settings"]
    assert b["teachers"][0]["matricula_docente"] == old["teachers"][0]["ID"]
    assert b["rooms"] == old["rooms"] and b["students"] == old["students"] and b["blocks"] == old["blocks"]
    assert updated.get_plan(pid)["revision"] == rev
    assert Store(store.path).load()[1] == new_rev
    with updated.connect() as db:
        assert json.loads(db.execute("SELECT payload FROM revisions WHERE id=?", (rev,)).fetchone()[0]) == old


@pytest.mark.parametrize("tab,kind", [("Docentes", "teachers"), ("Salones", "rooms")])
def test_save_retains_tab_hides_ids_and_toasts(tmp_path, monkeypatch, sample, tab, kind):
    path = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(path))
    store = Store(path)
    store.save(sample, 0, "Inicial")
    at = AppTest.from_file(APP).run()
    at.radio(key="nav").set_value("Datos").run()
    at.session_state["data_tabs"] = tab
    at.run()
    assert not at.exception
    assert all("ID" not in df.value.columns for df in at.dataframe)
    key = f"edit_{kind}_1_0"
    field = "matricula_docente" if kind == "teachers" else "Salón"
    value = "000012" if kind == "teachers" else "102"
    at.session_state[key] = {"edited_rows": {0: {field: value}}, "added_rows": [], "deleted_rows": []}
    at.button(key=f"save_{kind}").click().run()
    assert not at.exception
    assert at.session_state["data_tabs"] == tab
    assert at.toast and "Cambios guardados" in at.toast[0].value
    assert at.toast[0].proto.duration == 4
    saved, rev = store.load()
    assert rev == 2 and saved[kind][0][field] == value
    assert saved[kind][0]["ID"] == sample[kind][0]["ID"]
    at.run()
    assert not at.toast
    added = {k: v for k, v in sample[kind][0].items() if k != "ID"}
    added[field] = "000099" if kind == "teachers" else "103"
    at.session_state[f"edit_{kind}_2_0"] = {"edited_rows": {}, "added_rows": [added], "deleted_rows": []}
    at.button(key=f"save_{kind}").click().run()
    assert not at.exception
    saved, rev = store.load()
    assert rev == 3 and len(saved[kind]) == 2
    assert saved[kind][0]["ID"] == sample[kind][0]["ID"]
    assert saved[kind][1]["ID"] and saved[kind][1]["ID"] != saved[kind][0]["ID"]
    deleted_id = saved[kind][1]["ID"]
    added[field] = "000100" if kind == "teachers" else "104"
    at.session_state[f"edit_{kind}_3_0"] = {"edited_rows": {}, "added_rows": [added], "deleted_rows": [1]}
    at.button(key=f"save_{kind}").click().run()
    assert not at.exception
    saved, rev = store.load()
    assert rev == 4 and len(saved[kind]) == 2
    assert saved[kind][0]["ID"] == sample[kind][0]["ID"]
    assert saved[kind][1]["ID"] not in (deleted_id, saved[kind][0]["ID"])


def test_rules_and_failure_navigation(tmp_path, monkeypatch, sample):
    path = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("INGLES_DB_PATH", str(path))
    sample["teachers"][0]["Horas máximas"] = "1"
    Store(path).save(sample, 0, "Inicial")
    at = AppTest.from_file(APP).run()
    at.radio(key="nav").set_value("Bloques y reglas").run()
    assert next(w for w in at.time_input if w.label == "Fin de la jornada").value == time(15, 45)
    assert not any("traslado" in w.label or w.label == "Periodos por día" for w in at.number_input)
    at.radio(key="nav").set_value("Generar").run()
    at.button[0].click().run()
    assert at.error and not at.exception
    assert at.session_state["generation_failure"][1]["diagnostics"]
    next(b for b in at.button if b.label == "Revisar docentes").click().run()
    assert at.radio(key="nav").value == "Datos"
    assert at.session_state["data_tabs"] == "Docentes"


def test_joint_conflict_explains_cohorts_and_resource_rules(sample):
    sample["blocks"] = [sample["blocks"][0], dict(sample["blocks"][0], Bloque="Otro")]
    for i, a in enumerate(sample["students"]):
        a["Grupo"] = "1A" if i < 5 else "2A"
        a["Bloque fijo"] = sample["blocks"][0]["Bloque"] if i < 5 else "Otro"
    result = solve(sample)
    assert result.status == "INFEASIBLE"
    assert any(d["Parámetro"] in ("Salones sin choques", "Docentes sin choques") for d in result.diagnostics)
    assert any(d["Parámetro"] == "Grupo de carrera" for d in result.diagnostics)
    assert all(d["Cómo corregir"] and d["Sección"] for d in result.diagnostics)


def test_career_excel_separates_cohorts_and_is_printable(sample):
    for i, a in enumerate(sample["students"]):
        a["Carrera"] = ("Carrera/muy larga:con caracteres [especiales] A" if i < 5 else "Carrera/muy larga:con caracteres [especiales] B")
        a["Grupo"] = "1A"
    sample["students"][0]["Nombre"] = '=HYPERLINK("bad")'
    plan = solve(sample).payload()
    book = load_workbook(BytesIO(export_career_excel(sample, plan)), data_only=False)
    assert len(book.sheetnames) == 2 and len(set(book.sheetnames)) == 2
    exported = []
    for ws in book:
        assert len(ws.title) <= 31 and ws.max_row == 8
        assert [c.value for c in ws[3]] == HEADERS
        assert "Grupo 1A" in ws["A1"].value and "Horario común:" in ws["A2"].value
        assert ws.print_title_rows == "$1:$3" and ws.freeze_panes == "A4"
        assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
        for row in ws.iter_rows(min_row=4):
            exported.append(row[0].value)
            assert row[0].data_type == "s" and row[1].data_type == "s"
            assert row[5].value and row[6].value and row[7].value
    assert sorted(exported) == sorted(a["Matricula"] for a in sample["students"])
    with pytest.raises(ValueError):
        export_career_excel(sample, dict(plan, assignments=plan["assignments"][:-1]))
