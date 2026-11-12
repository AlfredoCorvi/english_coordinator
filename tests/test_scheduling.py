from copy import deepcopy
import json

import pytest

from ingles.audit import audit, errors_only
from ingles.domain import DAYS, demo_bundle, empty_bundle, periods, propose_blocks, slots, validate_bundle
from ingles.scheduler import solve
from ingles.storage import ConcurrentEdit, Store


@pytest.fixture
def small():
    b = empty_bundle()
    b["settings"]["solver_seconds"] = 3
    b["blocks"] = propose_blocks(8)[:2]
    b["teachers"] = [{"ID": "D1", "Nombre": "Ana", "Edificios": "1,2", "Horas máximas": "14", **{d: "*" for d in DAYS}}]
    b["rooms"] = [{"ID": "R1", "Salón": "101", "Edificio": "1", "Capacidad": "30", **{d: "*" for d in DAYS}}]
    b["students"] = [{"Matricula": f"{i:05}", "Nombre": f"Alumno {i}", "Carrera": "Ingeniería", "Grupo": "1A", "Edificio": "1", "Nivel": "Basic 1", "Bloque fijo": ""} for i in range(8)]
    return b


def solved(b):
    result = solve(b)
    assert result.success, result.message
    assert not errors_only(audit(b, result.payload()))
    assert len(result.assignments) == len(b["students"])
    return result.payload()


def test_demo_complete_and_family_groups():
    b = demo_bundle()
    plan = solved(b)
    assert len(plan["groups"]) == 7
    assert {g["level"] for g in plan["groups"]} == {"A", "B", "C"}
    group_blocks = {g["id"]: g["block"] for g in plan["groups"]}
    by_student = {a["student"]: group_blocks[a["group"]] for a in plan["assignments"]}
    for cohort in {(a["Carrera"], a["Grupo"]) for a in b["students"]}:
        assert len({by_student[a["Matricula"]] for a in b["students"] if (a["Carrera"], a["Grupo"]) == cohort}) == 1


def test_grouping_modes(small):
    small["rooms"].append(dict(small["rooms"][0], ID="R2", **{"Salón": "102"}))
    small["teachers"].append(dict(small["teachers"][0], ID="D2", Nombre="Bea"))
    small["students"][0]["Nivel"] = "Basic 3"
    assert len(solved(small)["groups"]) == 1
    small["settings"]["grouping"] = "cefr"
    assert len(solved(small)["groups"]) == 2
    small["settings"]["grouping"] = "course"
    assert {g["level"] for g in solved(small)["groups"]} == {"Basic 1", "Basic 3"}


def test_conflicting_fixed_blocks_in_same_cohort_are_rejected(small):
    small["students"][0]["Bloque fijo"] = "Bloque 1"
    small["students"][1]["Bloque fijo"] = "Bloque 2"
    result = solve(small)
    assert result.status == "INVALID"
    assert "Ingeniería / 1A: bloques fijos incompatibles" in result.message


def test_one_fixed_block_reserves_the_entire_cohort(small):
    small["students"][0]["Bloque fijo"] = "Bloque 2"
    assert {g["block"] for g in solved(small)["groups"]} == {"Bloque 2"}


def test_same_group_code_in_different_careers_is_independent(small):
    small["students"][0].update({"Carrera": "Diseño", "Bloque fijo": "Bloque 1"})
    small["students"][1]["Bloque fijo"] = "Bloque 2"
    assert {g["block"] for g in solved(small)["groups"]} == {"Bloque 1", "Bloque 2"}


def test_cannot_split_classmates_to_work_around_missing_resources(small):
    small["settings"]["cohort_block"] = False  # Old configurations cannot bypass the rule.
    small["students"][0]["Nivel"] = "Advanced 1"
    # Enough total time, but only one teacher/room: A and C cannot run together.
    assert solve(small).status == "INFEASIBLE"


def test_splitting_is_joint_with_capacity(small):
    small["rooms"][0]["Capacidad"] = "5"
    small["rooms"].append(dict(small["rooms"][0], ID="R2", **{"Salón": "102"}))
    small["teachers"].append(dict(small["teachers"][0], ID="D2", Nombre="Bea"))
    small["settings"]["min_group"] = 4
    result = solved(small)
    assert len(result["groups"]) == 2
    assert sorted(sum(a["group"] == g["id"] for a in result["assignments"]) for g in result["groups"]) == [4, 4]


@pytest.mark.parametrize("change", ["hours", "availability", "room", "building", "minimum"])
def test_impossible_constraints(small, change):
    if change == "hours":
        small["teachers"][0]["Horas máximas"] = "6"
    elif change == "availability":
        small["teachers"][0].update({d: "8" for d in DAYS})
    elif change == "room":
        small["rooms"][0].update({d: "8" for d in DAYS})
    elif change == "building":
        small["teachers"][0]["Edificios"] = "4"
    else:
        small["settings"]["min_group"] = 9
    assert solve(small).status == "INFEASIBLE"


def test_strict_student_building(small):
    small["students"][0]["Edificio"] = "4"
    solved(small)
    small["settings"]["strict_building"] = True
    assert solve(small).status == "INFEASIBLE"


def test_overlap_different_block_names(small):
    small["blocks"][1].update({d: small["blocks"][0][d] for d in DAYS})
    small["students"][0]["Bloque fijo"] = "Bloque 1"
    small["students"][1]["Bloque fijo"] = "Bloque 2"
    small["students"][1]["Grupo"] = "2A"
    assert solve(small).status == "INFEASIBLE"


def test_multiple_groups_in_same_block(small):
    small["students"][0]["Nivel"] = "Advanced 1"
    small["rooms"].append(dict(small["rooms"][0], ID="R2", **{"Salón": "102"}))
    small["teachers"].append(dict(small["teachers"][0], ID="D2", Nombre="Bea"))
    plan = solved(small)
    assert len(plan["groups"]) == 2
    assert {g["level"] for g in plan["groups"]} == {"A", "C"}
    assert len({g["block"] for g in plan["groups"]}) == 1


def test_transfer_time_is_enforced(small):
    small["settings"]["strict_building"] = True
    small["blocks"] = [{"Bloque": "Uno", "Lunes": "1,2", "Martes": "1,2", "Miércoles": "1", "Jueves": "1", "Viernes": "1"},
                       {"Bloque": "Dos", "Lunes": "3,4", "Martes": "3,4", "Miércoles": "2", "Jueves": "2", "Viernes": "2"}]
    small["rooms"].append(dict(small["rooms"][0], ID="R2", Edificio="2"))
    for i, a in enumerate(small["students"]):
        a["Edificio"] = "1" if i < 4 else "2"
        a["Grupo"] = "1A" if i < 4 else "2A"
        a["Bloque fijo"] = "Uno" if i < 4 else "Dos"
    assert solve(small).status == "INFEASIBLE"
    small["settings"]["transfer_periods"] = 0
    plan = solved(small)
    small["settings"]["transfer_periods"] = 1
    assert "Traslado docente" in {i["Regla"] for i in audit(small, plan)}


def test_audit_detects_omission_duplicates_and_level(small):
    plan = solved(small)
    plan["assignments"][0] = plan["assignments"][1].copy()
    plan["groups"][0]["level"] = "B"
    rules = {i["Regla"] for i in audit(small, plan)}
    assert {"Cobertura", "Nivel"} <= rules


def test_audit_detects_teacher_room_collisions(small):
    plan = solved(small)
    g = plan["groups"][0]
    plan["groups"].append(dict(g, id="OTHER"))
    plan["assignments"][0]["group"] = "OTHER"
    rules = {i["Regla"] for i in audit(small, plan)}
    assert {"Choque docente", "Choque de salón"} <= rules


def test_audit_rechecks_changed_inputs(small):
    plan = solved(small)
    small["rooms"][0]["Capacidad"] = "1"
    small["teachers"][0]["Horas máximas"] = "1"
    rules = {i["Regla"] for i in audit(small, plan)}
    assert {"Cupo", "Carga docente"} <= rules


def test_manual_split_cohort_fails_audit_and_export(small):
    from ingles.exchange import export_excel
    from ingles.reports import export_pdf

    plan = solved(small)
    small["settings"]["cohort_block"] = False
    original = plan["groups"][0]
    other_block = next(b["Bloque"] for b in small["blocks"] if b["Bloque"] != original["block"])
    plan["groups"].append(dict(original, id="OTHER", block=other_block))
    plan["assignments"][0]["group"] = "OTHER"
    assert {i["Regla"] for i in errors_only(audit(small, plan))} == {"Grupo de carrera"}
    for exporter in (export_excel, export_pdf):
        with pytest.raises(ValueError):
            exporter(small, plan)


def test_validation_unknown_duplicate_and_hours(small):
    small["students"].append(small["students"][0].copy())
    small["students"][0]["Nivel"] = "Inventado"
    small["blocks"][0]["Lunes"] = "8"
    errors = validate_bundle(small)
    assert any("duplicado" in e for e in errors)
    assert any("desconocido" in e for e in errors)
    assert any("exactamente 7" in e for e in errors)


@pytest.mark.parametrize("value", ["0", "9", "3-1", "1,1", "1,,2", "abc", "1-9"])
def test_invalid_periods(value):
    with pytest.raises(ValueError):
        periods(value, 8)


def test_proposals_have_seven_hours_without_overlap():
    blocks = propose_blocks(8)
    assert len(blocks) == 5
    occupied = set()
    for b in blocks:
        times = slots(b, 8)
        assert len(times) == 7 and not occupied & times
        occupied |= times


def test_physical_room_duplicate(small):
    small["rooms"].append(dict(small["rooms"][0], ID="SECOND"))
    assert any("ya existe" in e for e in validate_bundle(small))


def test_sqlite_persistence_history_and_concurrency(tmp_path, small):
    path = tmp_path / "db.sqlite3"
    store = Store(path)
    assert store.load()[1] == 0
    revision = store.save(small, 0, "initial")
    plan = solved(small)
    pid = store.save_plan(plan, revision, "automatic")
    second = Store(path)
    assert second.load() == (small, revision)
    assert second.get_plan(pid)["payload"] == plan
    changed = deepcopy(small)
    changed["students"][0]["Nombre"] = "Corregido"
    second.save(changed, revision, "edit")
    assert store.get_plan(pid)["revision"] == revision
    with pytest.raises(ConcurrentEdit):
        store.save(small, revision, "stale")
    with pytest.raises(ConcurrentEdit):
        store.save_plan(plan, revision, "stale generation")


@pytest.mark.parametrize("legacy_flag", [False, True])
def test_upgrading_existing_database_preserves_history(tmp_path, small, legacy_flag):
    path = tmp_path / "legacy.sqlite3"
    old_store = Store(path)
    old_bundle = deepcopy(small)
    old_bundle["settings"]["cohort_block"] = legacy_flag
    with old_store.connect() as db:
        rev = db.execute("INSERT INTO revisions(created, note, payload) VALUES (?, ?, ?)",
                         ("2026-11-10T00:00:00+00:00", "Antes de actualizar", json.dumps(old_bundle))).lastrowid
    plan_id = old_store.save_plan(solved(small), rev, "Horario anterior")
    updated_store = Store(path)
    current, revision = updated_store.load()
    assert current == small
    assert revision == rev + 1
    assert updated_store.get_plan(plan_id)["revision"] == rev
    assert Store(path).load() == (small, revision)  # Upgrade happens exactly once.
    with updated_store.connect() as db:
        historical = db.execute("SELECT payload FROM revisions WHERE id=?", (rev,)).fetchone()[0]
        assert json.loads(historical) == old_bundle
    with pytest.raises(ConcurrentEdit):
        old_store.save(small, rev, "Sesión anterior a la actualización")
