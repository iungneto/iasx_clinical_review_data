import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "pipeline"))

from utilities.clinical_rules import mask_identifiers, normalize_test_name, parse_page  # noqa: E402

PAGE = """LABORATÓRIO SINTÉTICO IASX — LAUDO DE EXAMES
Paciente: Paciente Sintético C
CPF: 123.456.789-09
Hemoglobina glicada: 6,4 %
Data da coleta: 12/03/2026
Hemoglobina: 10,9 g/dL (VR: 12,0 - 16,0)
Sódio: ilegível mEq/L (VR: 135 - 145)
Glicemia de jejum: 105 mg/dL
Exame externo trazido pelo paciente:
"""


def by_code(results):
    return {r["test_code"]: r for r in results}


def test_extracts_only_result_lines():
    assert sorted(by_code(parse_page(PAGE))) == ["GLU", "HBA1C", "HGB", "NA"]


def test_value_unit_range_and_date():
    hgb = by_code(parse_page(PAGE))["HGB"]
    assert (hgb["value"], hgb["unit"], hgb["ref_low"], hgb["ref_high"]) == (10.9, "g/dL", 12.0, 16.0)
    assert hgb["exam_date"] == "2026-03-12"
    assert hgb["value_status"] == "OK"


def test_source_offsets_point_to_the_line():
    hgb = by_code(parse_page(PAGE))["HGB"]
    assert PAGE[hgb["char_start"] : hgb["char_end"]] == hgb["source_text"]
    assert hgb["source_text"].startswith("Hemoglobina: 10,9")


def test_missing_information_is_never_filled():
    results = by_code(parse_page(PAGE))
    assert results["HBA1C"]["exam_date"] is None  # linha antes de qualquer data
    assert results["GLU"]["ref_low"] is None and results["GLU"]["ref_high"] is None
    assert results["NA"]["value_status"] == "ILLEGIBLE" and results["NA"]["value"] is None


def test_impossible_date_is_a_gap_not_a_guess():
    results = parse_page("Data da coleta: 31/02/2026\nCreatinina: 1,0 mg/dL (VR: 0,6 - 1,2)")
    assert results[0]["exam_date"] is None


@pytest.mark.parametrize("raw,code", [("Potássio", "K"), ("GLICOSE", "GLU"), ("Hb", "HGB"), ("Ferritina", "UNK_FERRITINA")])
def test_normalize_test_name(raw, code):
    assert normalize_test_name(raw)[0] == code


def test_cpf_is_masked():
    assert mask_identifiers("CPF: 123.456.789-09") == "CPF: ***.***.***-**"


def test_synthetic_pdfs_roundtrip():
    """Gera os PDFs sintéticos e confere a extração ponta a ponta (requer pypdf)."""
    pytest.importorskip("pypdf")
    sys.path.insert(0, str(ROOT / "tools"))
    import generate_synthetic_cases as gen
    from utilities.pdf_parsing import extract_pages

    gen.main()
    pdf = (gen.OUT / "pdfs" / "CASE-C" / "C_laudo_laboratorio.pdf").read_bytes()
    result = extract_pages(pdf)
    assert result["error"] is None
    assert [p["page_num"] for p in result["pages"]] == [1, 2]
    assert result["pages"][1]["text"].strip() == ""  # página digitalizada → lacuna NON_TEXTUAL_PAGE
    codes = by_code(parse_page(mask_identifiers(result["pages"][0]["text"])))
    assert codes["K"]["value"] == 5.9 and codes["NA"]["value_status"] == "ILLEGIBLE"
