import pytest

from utilities.clinical_rules import (
    EXTRACTOR_VERSION,
    is_synthetic_declared,
    mask_identifiers,
    normalize_test_name,
    parse_page,
)
from utilities.pdf_parsing import extract_pages

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


# --- extração -------------------------------------------------------------------------------------

def test_extracts_only_result_lines():
    assert sorted(by_code(parse_page(PAGE))) == ["GLU", "HBA1C", "HGB", "NA"]


def test_value_unit_range_and_date():
    hgb = by_code(parse_page(PAGE))["HGB"]
    assert (hgb["value"], hgb["unit"], hgb["ref_low"], hgb["ref_high"]) == (10.9, "g/dL", 12.0, 16.0)
    assert hgb["exam_date"] == "2026-03-12"
    assert hgb["value_status"] == "OK"
    assert hgb["extractor_version"] == EXTRACTOR_VERSION


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


def test_missing_unit_is_not_inferred():
    k = parse_page("Data da coleta: 15/01/2026\nPotássio: 4,5 (VR: 3,5 - 5,1)")[0]
    assert (k["value"], k["unit"], k["ref_low"], k["ref_high"]) == (4.5, None, 3.5, 5.1)


@pytest.mark.parametrize(
    "line,code",
    [
        ("Creatinina: 1,0 ou 1,3 mg/dL (VR: 0,6 - 1,2)", "CREA"),  # dois valores
        ("Proteína C reativa: < 0,5 mg/dL (VR: 0,0 - 0,5)", "CRP"),  # valor censurado
        ("Glicose: aprox. 100 mg/dL", "GLU"),
    ],
)
def test_ambiguous_value_is_flagged_never_picked(line, code):
    """Valor que não é número simples vira AMBIGUOUS: sem valor, unidade ou faixa escolhidos pelo IASX."""
    (r,) = parse_page(line)
    assert r["test_code"] == code and r["value_status"] == "AMBIGUOUS"
    assert (r["value"], r["unit"], r["ref_low"], r["ref_high"]) == (None, None, None, None)
    assert r["source_text"] == line


def test_free_text_with_colon_is_not_a_result():
    assert parse_page("Observação: paciente em jejum de 12 h\nConclusão: ver laudo anexo") == []


@pytest.mark.parametrize("raw,code", [("Potássio", "K"), ("GLICOSE", "GLU"), ("Hb", "HGB"), ("Ferritina", "UNK_FERRITINA")])
def test_normalize_test_name(raw, code):
    assert normalize_test_name(raw)[0] == code


# --- minimização (LGPD) ---------------------------------------------------------------------------

def test_cpf_is_masked():
    assert mask_identifiers("CPF: 123.456.789-09") == "CPF: ***.***.***-**"


@pytest.mark.parametrize(
    "line,secret",
    [
        ("Paciente: Maria da Silva", "Maria"),
        ("Nome do paciente: João Souza", "Souza"),
        ("Data de nascimento: 01/01/1970", "1970"),
        ("Telefone: (11) 91234-5678", "91234"),
        ("Médico solicitante: Dr. Fulano", "Fulano"),
        ("CRM: 123456-SP", "123456"),
        ("CNS: 700 0000 0000 0000", "700 0000"),
        ("Contato: maria@example.com", "maria@"),
        ("Cartão SUS: 898001160660000", "898001160660000"),
    ],
)
def test_direct_identifiers_are_masked(line, secret):
    masked = mask_identifiers(line)
    assert secret not in masked
    assert len(masked) == len(line)  # comprimento preservado


def test_masking_preserves_offsets_and_results():
    text = "Paciente: Maria da Silva\nTelefone: (11) 91234-5678\nData da coleta: 12/03/2026\nHemoglobina: 10,9 g/dL (VR: 12,0 - 16,0)\n"
    masked = mask_identifiers(text)
    assert len(masked) == len(text)
    assert parse_page(masked) == parse_page(text)  # mesmos achados, mesmos offsets


def test_masking_keeps_clinical_lines_intact():
    assert mask_identifiers(PAGE).splitlines()[5:8] == PAGE.splitlines()[5:8]


def test_synthetic_declaration():
    assert is_synthetic_declared(["...", "Documento sintético para demonstração — não contém dados reais."])
    assert is_synthetic_declared(["DOCUMENTO SINTETICO"])
    assert not is_synthetic_declared(["Laudo de exames", ""])
    assert not is_synthetic_declared([])


# --- PDFs sintéticos ponta a ponta ------------------------------------------------------------------

def _parse_pdf(gen, case_id, document_id):
    result = extract_pages((gen.OUT / "pdfs" / case_id / f"{document_id}.pdf").read_bytes())
    assert result["error"] is None
    return result


def test_case_c_roundtrip(synthetic):
    result = _parse_pdf(synthetic, "CASE-C", "C_laudo_laboratorio")
    assert [p["page_num"] for p in result["pages"]] == [1, 2]
    assert result["pages"][1]["text"].strip() == ""  # página digitalizada → lacuna NON_TEXTUAL_PAGE
    page = mask_identifiers(result["pages"][0]["text"])
    assert "123.456.789-09" not in page and "Paciente Sintético C" not in page
    codes = by_code(parse_page(page))
    assert codes["K"]["value"] == 5.9 and codes["NA"]["value_status"] == "ILLEGIBLE"


def test_case_d_units_and_ambiguity(synthetic):
    first = by_code(parse_page(mask_identifiers(_parse_pdf(synthetic, "CASE-D", "D_lab_20260115")["pages"][0]["text"])))
    second = by_code(parse_page(mask_identifiers(_parse_pdf(synthetic, "CASE-D", "D_lab_20260301")["pages"][0]["text"])))
    assert (first["GLU"]["unit"], second["GLU"]["unit"]) == ("mmol/L", "mg/dL")
    assert first["K"]["unit"] is None and second["K"]["unit"] == "mEq/L"
    assert second["CREA"]["value_status"] == "AMBIGUOUS" and second["CRP"]["value_status"] == "AMBIGUOUS"
    assert first["GLU"]["exam_date"] == "2026-01-15" and second["GLU"]["exam_date"] == "2026-03-01"


def test_every_synthetic_pdf_declares_itself_except_the_negative_case(synthetic):
    declared = {
        pdf.stem: is_synthetic_declared([p["text"] for p in extract_pages(pdf.read_bytes())["pages"]])
        for pdf in (synthetic.OUT / "pdfs").rglob("*.pdf")
    }
    assert declared.pop("D_sem_marcacao") is False
    assert declared and all(declared.values())


def test_gabarito_covers_every_case_with_expected_findings(synthetic):
    cases_in_gabarito = {row[0] for row in synthetic.GABARITO}
    assert cases_in_gabarito == {c["case_id"] for c in synthetic.CASES} - {"CASE-A"}  # A: nenhum achado esperado
    covered = {(row[1], row[2]) for row in synthetic.GABARITO}
    for expected in [
        ("TEMPORAL_VARIATION", "UP"),
        ("TEMPORAL_VARIATION", "UNIT_CHANGED"),
        ("CONFLICT", "DIVERGENT_VALUES"),
        ("GAP", "AMBIGUOUS_VALUE"),
        ("GAP", "MISSING_UNIT"),
        ("GAP", "NOT_SYNTHETIC_DOCUMENT"),
        ("GAP", "NON_TEXTUAL_PAGE"),
    ]:
        assert expected in covered
