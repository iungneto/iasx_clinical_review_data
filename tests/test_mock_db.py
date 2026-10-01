"""A base mockada (tools/mock_db) precisa continuar fiel à API real e conforme à matriz (só dado sintético, mascarado)."""

import json
import re

import pytest

from conftest import ROOT

TABLES = ROOT / "tools/mock_db/tables"
READ_FUNCTIONS = {
    "list_cases": "gold_review_status",
    "review_queue": "gold_review_queue",
    "document_page": "silver_document_pages",
    "timeline": "gold_timeline",
    "temporal_comparison": "gold_temporal_comparison",
    "attestation_payload": "gold_attestation_payload",
}


@pytest.mark.parametrize("function, table", READ_FUNCTIONS.items())
def test_backend_sql_columns_exist_in_the_mock_tables(mock_db, function, table):
    """Se uma coluna for renomeada na gold ou no backend.py, o mock (e a API) deixam de bater: reexporte."""
    columns = set().union(*(row.keys() for row in mock_db.table(table)))
    assert set(mock_db.select_columns(function)) <= columns


def test_evidence_columns_exist_in_the_mock_findings(mock_db):
    evidence = [e for f in mock_db.table("gold_findings") for e in f["evidence"]]
    assert evidence and set(mock_db.select_columns("finding_evidence")) <= set(evidence[0])


def test_mock_holds_only_registered_synthetic_cases():
    lines = (ROOT / "data/synthetic/cases.json").read_text(encoding="utf-8").splitlines()
    registered = {json.loads(line)["case_id"] for line in lines if line.strip()}
    for path in TABLES.glob("*.json"):
        assert {row["case_id"] for row in json.loads(path.read_text(encoding="utf-8"))} <= registered, path.name


def test_mock_never_contains_raw_documents_or_unmasked_identifiers():
    """§3: a base mockada sai da silver/gold (mascarada); a bronze com o PDF bruto nunca é exportada."""
    assert not list(TABLES.glob("bronze_*"))
    for path in TABLES.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", text), path.name  # CPF
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w{2,}", text), path.name  # e-mail
        assert "Paciente: " not in text or not re.search(r"Paciente: [A-ZÀ-Ú][a-zà-ú]", text), path.name
