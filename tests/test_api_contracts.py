"""Contratos de entrada da API do JEV (src/app/models.py) e travas de conformidade (src/app/guards.py)."""

import pytest
from pydantic import ValidationError

from guards import SYNTHETIC_MARKER, declares_synthetic
from models import AttestationIn, CaseIn, ReviewDecisionIn
from utilities.clinical_rules import SYNTHETIC_MARKER as PIPELINE_MARKER

SHA = "a" * 64
ATTESTATION = {
    "review_id": "rev-c-0001",
    "program_id": "11111111111111111111111111111111",
    "pda_address": "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
    "tx_signature": "5" * 88,
    "input_hash": SHA,
    "analysis_hash": SHA,
    "reviewed_hash": SHA,
    "workflow_version": "iasx-wf-1.0.0",
    "model_version": "extract-rules-1.1.0+mock-jev",
    "reviewer_tech_id": "reviewer-7f3a",
}


# --- casos: somente dados sintéticos ---------------------------------------------------------------

def test_case_requires_synthetic_declaration():
    assert CaseIn(case_id="CASE-X", review_id="rev-x", data_classification="SYNTHETIC").case_id == "CASE-X"
    with pytest.raises(ValidationError):
        CaseIn(case_id="CASE-X", review_id="rev-x")
    with pytest.raises(ValidationError):
        CaseIn(case_id="CASE-X", review_id="rev-x", data_classification="REAL")


@pytest.mark.parametrize("field,value", [("scenario", "Maria, 54 anos, diabética"), ("case_id", "../pdfs"), ("case_id", "João Silva")])
def test_case_rejects_free_text_in_technical_fields(field, value):
    with pytest.raises(ValidationError):
        CaseIn(**{"case_id": "CASE-X", "review_id": "rev-x", "data_classification": "SYNTHETIC", field: value})


# --- decisões do profissional ----------------------------------------------------------------------

def test_review_decision_rules():
    ok = ReviewDecisionIn(review_id="r", scope="FINDING", finding_id="f1", action="CORRECT", corrected_value=4.9,
                          corrected_unit="mEq/L", reviewer_tech_id="rv-1")
    assert ok.corrected_unit == "mEq/L"
    for bad in [
        {"scope": "FINDING", "action": "SIGNOFF", "finding_id": "f1"},
        {"scope": "FINDING", "action": "CONFIRM"},  # sem finding_id
        {"scope": "FINDING", "action": "CORRECT", "finding_id": "f1"},  # correção sem valor/unidade
        {"scope": "REVIEW", "action": "CONFIRM"},
        {"scope": "FINDING", "action": "CORRECT", "finding_id": "f1", "corrected_unit": "suspeita de hipercalemia"},
    ]:
        with pytest.raises(ValidationError):
            ReviewDecisionIn(review_id="r", reviewer_tech_id="rv-1", **bad)


# --- atestação: Devnet e só dados técnicos ----------------------------------------------------------

def test_attestation_defaults_to_devnet_submitted():
    a = AttestationIn(**ATTESTATION)
    assert (a.cluster, a.status) == ("devnet", "SUBMITTED")


@pytest.mark.parametrize(
    "field,value",
    [
        ("cluster", "mainnet-beta"),
        ("status", "ATTESTED"),
        ("input_hash", "Potássio 5,9 mEq/L"),
        ("analysis_hash", "A" * 64),  # hash fora do formato hex minúsculo da gold
        ("tx_signature", "assinatura com espaço"),
        ("pda_address", "0OIl" * 10),  # fora do alfabeto base58
        ("model_version", "x" * 33),  # não cabe no campo de 32 bytes on-chain
    ],
)
def test_attestation_rejects_non_technical_or_non_devnet(field, value):
    with pytest.raises(ValidationError):
        AttestationIn(**{**ATTESTATION, field: value})


# --- upload: só PDF sintético ------------------------------------------------------------------------

def test_marker_is_the_same_in_api_and_pipeline():
    assert SYNTHETIC_MARKER == PIPELINE_MARKER


def test_upload_guard_accepts_synthetic_and_refuses_the_rest(synthetic):
    pdfs = synthetic.OUT / "pdfs"
    assert declares_synthetic((pdfs / "CASE-C" / "C_laudo_laboratorio.pdf").read_bytes())
    assert not declares_synthetic((pdfs / "CASE-D" / "D_sem_marcacao.pdf").read_bytes())
    assert not declares_synthetic(b"%PDF-1.4 corrompido")
