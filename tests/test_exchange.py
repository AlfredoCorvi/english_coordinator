from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader

from ingles.domain import demo_bundle
from ingles.exchange import (HEADERS, export_excel, map_rows, read_excel, reservations,
                             suggested_mapping, template_excel)
from ingles.reports import export_pdf
from ingles.scheduler import solve


@pytest.fixture(scope="module")
def sample():
    bundle = demo_bundle()
    plan = solve(bundle).payload()
    return bundle, plan


def test_import_aliases_and_leading_zeros():
    book = Workbook()
    ws = book.active
    ws.append(["Matrícula", "Nombre completo", "Grupo", "Carrera", "Edificio", "Nivel de inglés"])
    ws.append([12, "José Álvarez", "1A", "Diseño", 1, "prebasic"])
    ws["A2"].number_format = "0000000"
    stream = BytesIO()
    book.save(stream)
    headers, rows = read_excel(stream.getvalue(), ws.title)
    imported = map_rows("students", rows, suggested_mapping("students", headers))
    assert imported[0]["Matricula"] == "0000012"
    assert imported[0]["Nivel"] == "Prebasic"
    assert imported[0]["Nombre"] == "José Álvarez"
    assert imported[0]["Edificio"] == "1"


def test_formula_input_rejected():
    book = Workbook()
    book.active.append(["Nombre"])
    book.active.append(['=HYPERLINK("https://example.com")'])
    stream = BytesIO()
    book.save(stream)
    with pytest.raises(ValueError, match="fórmulas"):
        read_excel(stream.getvalue(), book.active.title)


def test_exports_rosters_and_pdf(sample):
    bundle, plan = sample
    book = load_workbook(BytesIO(export_excel(bundle, plan)))
    ws = book["Listado"]
    assert [c.value for c in ws[1]] == HEADERS
    assert ws.max_row == 181
    assert all(c.data_type == "s" and len(c.value) == 7 for row in ws.iter_rows(min_row=2, max_col=1) for c in row)
    assert len([name for name in book.sheetnames if name.startswith("Grupo ")]) == len(plan["groups"])
    assert book["Horarios"].max_row == 7 * len(plan["groups"]) + 1
    pdf = PdfReader(BytesIO(export_pdf(bundle, plan)))
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "Planeación de inglés" in text
    assert "0000001" in text and "0000180" in text
    assert all(g["id"] in text for g in plan["groups"])


def test_export_untrusted_text_is_literal(sample):
    bundle, plan = sample
    original = bundle["students"][0]["Nombre"]
    try:
        bundle["students"][0]["Nombre"] = '=HYPERLINK("https://example.com")'
        book = load_workbook(BytesIO(export_excel(bundle, plan)), data_only=False)
        cell = next(c for row in book["Listado"].iter_rows() for c in row if c.value == bundle["students"][0]["Nombre"])
        assert cell.data_type == "s"
    finally:
        bundle["students"][0]["Nombre"] = original


def test_templates_round_trip():
    b = demo_bundle()
    for kind in ("students", "teachers", "rooms", "blocks"):
        headers, rows = read_excel(template_excel(kind, b), kind)
        assert map_rows(kind, rows, suggested_mapping(kind, headers)) == b[kind]


def test_invalid_plan_cannot_be_exported(sample):
    b, p = sample
    invalid = dict(p, assignments=p["assignments"][:-1])
    with pytest.raises(ValueError):
        export_excel(b, invalid)
    with pytest.raises(ValueError):
        export_pdf(b, invalid)


def test_reservations_are_seven_shared_hours_per_cohort(sample):
    b, p = sample
    rows = reservations(b, p)
    tuples = [tuple(row.values()) for row in rows]
    assert len(tuples) == len(set(tuples))
    assert all(row["Periodo reservado"] in range(1, 9) for row in rows)
    for cohort in {(a["Carrera"], a["Grupo"]) for a in b["students"]}:
        assert sum((r["Carrera"], r["Grupo"]) == cohort for r in rows) == 7
