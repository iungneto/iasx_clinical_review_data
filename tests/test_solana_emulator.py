"""Emulador da Solana (solana_mode = emulated): recibo válido, conta no layout real e nunca ATTESTED na gold."""

import hashlib
from types import SimpleNamespace

import pytest

from conftest import ROOT
from models import AttestationIn
from onchain_layout import ACCOUNT_SIZE, decode_account, emulated_account, encode_account, review_id_hash
from solana_emulator import EMULATOR_PROGRAM_ID, b58encode, receipt
from test_api_contracts import ATTESTATION

PAYLOAD = {
    "review_id": "rev-c-0001",
    "input_hash": hashlib.sha256(b"in").hexdigest(),
    "analysis_hash": hashlib.sha256(b"an").hexdigest(),
    "reviewed_hash": hashlib.sha256(b"rv").hexdigest(),
    "workflow_version": "iasx-wf-1.0.0",
    "model_version": "extract-rules-1.1.0+mock-jev",
    "target_status": "CONFIRMED",
    "reviewer_tech_id": "reviewer-7f3a",
    "signoff_at": "2026-10-08T12:00:00+00:00",
    "ready_for_attestation": True,
}
SUBMITTED_AT = "2026-10-08T12:05:00+00:00"


@pytest.mark.parametrize(
    "data, expected",
    [(b"hello world", "StV1DL6CwTryKyV"), (b"\0\0\x01", "112"), (bytes(32), "1" * 32)],
)
def test_base58_matches_the_reference_alphabet(data, expected):
    assert b58encode(data) == expected


def test_receipt_is_a_valid_attestation_marked_as_emulated():
    r = receipt(PAYLOAD, SUBMITTED_AT)
    assert r["cluster"] == "emulated" and r["status"] == "SUBMITTED"
    assert r["program_id"] == EMULATOR_PROGRAM_ID
    # Mesmo formato do recibo real, exceto o cluster: a silver aplica as mesmas expectations.
    AttestationIn(**{**r, "cluster": "devnet"})
    assert {k: r[k] for k in ("input_hash", "analysis_hash", "reviewed_hash")} == {
        k: PAYLOAD[k] for k in ("input_hash", "analysis_hash", "reviewed_hash")
    }


def test_receipt_is_deterministic_per_submission():
    assert receipt(PAYLOAD, SUBMITTED_AT) == receipt(PAYLOAD, SUBMITTED_AT)
    other = receipt(PAYLOAD, "2026-10-08T13:00:00+00:00")
    assert other["tx_signature"] != receipt(PAYLOAD, SUBMITTED_AT)["tx_signature"]
    assert other["pda_address"] == receipt(PAYLOAD, SUBMITTED_AT)["pda_address"]  # PDA é por revisão


def test_encode_is_the_inverse_of_decode():
    data = encode_account("rev-c-0001", PAYLOAD["input_hash"], PAYLOAD["analysis_hash"], PAYLOAD["reviewed_hash"],
                          "iasx-wf-1.0.0", "extract-rules-1.1.0+mock-jev", attested_at=1_790_000_000)
    assert len(data) == ACCOUNT_SIZE
    d = decode_account(data)
    assert d["review_id_hash"] == review_id_hash("rev-c-0001")
    assert (d["input_hash"], d["analysis_hash"], d["reviewed_hash"]) == (
        PAYLOAD["input_hash"], PAYLOAD["analysis_hash"], PAYLOAD["reviewed_hash"])
    assert d["status"] == "ATTESTED" and d["attested_at"] == 1_790_000_000


def test_encode_refuses_versions_that_do_not_fit_onchain():
    with pytest.raises(ValueError):
        encode_account("r", *(PAYLOAD[k] for k in ("input_hash", "analysis_hash", "reviewed_hash")), "x" * 33, "m")


def test_emulated_account_carries_the_receipt_hashes():
    att = SimpleNamespace(**{**receipt(PAYLOAD, SUBMITTED_AT), "submitted_at": SUBMITTED_AT})
    d = decode_account(emulated_account(att))
    assert d["review_id_hash"] == review_id_hash("rev-c-0001")
    assert d["reviewed_hash"] == PAYLOAD["reviewed_hash"] and d["status"] == "ATTESTED"


def test_gold_never_finalizes_an_emulated_attestation():
    sql = (ROOT / "src/pipeline/transformations/gold/gold_review_status.sql").read_text(encoding="utf-8")
    assert "WHEN a.cluster = 'emulated' THEN 'EMULATED_VERIFIED'" in sql
    assert "WHEN onchain_status = 'EMULATED_VERIFIED' THEN 'ATTESTED_EMULATED'" in sql
    assert "onchain_status = 'VERIFIED' AS is_finalized" in sql


# --- API: POST /api/reviews/{review_id}/emulated-attestation -----------------------------------------

@pytest.fixture
def ready_payload(mock_db, monkeypatch):
    monkeypatch.setattr(mock_db, "attestation_payload", lambda rid: [{**PAYLOAD, "review_id": rid}])


def test_emulated_attestation_is_off_by_default(api, mock_db, ready_payload, monkeypatch):
    monkeypatch.delenv("IASX_SOLANA_MODE", raising=False)
    assert api.get("/api/health").json()["solana_mode"] == "devnet"
    assert api.post("/api/reviews/rev-c-0001/emulated-attestation").status_code == 409
    assert not mock_db.LANDING


def test_emulated_attestation_writes_receipt_and_runs_full_cycle(api, mock_db, ready_payload, monkeypatch):
    monkeypatch.setenv("IASX_SOLANA_MODE", "emulated")
    assert api.get("/api/health").json()["solana_mode"] == "emulated"
    resp = api.post("/api/reviews/rev-c-0001/emulated-attestation")
    assert resp.status_code == 201
    body = resp.json()
    [record] = mock_db.feed_records("attestations")
    assert record["cluster"] == "emulated" and record["review_id"] == "rev-c-0001" and record["submitted_at"]
    # Ciclo completo: só ele ingere o recibo antes do verify_onchain (decisions_only pula a pipeline inicial).
    assert body["mode"] == "full" and mock_db.RUNS[body["run_id"]]["mode"] == "full"


def test_emulated_attestation_requires_a_ready_payload(api, mock_db, monkeypatch):
    monkeypatch.setenv("IASX_SOLANA_MODE", "emulated")
    # Payloads do mock exportado ainda não têm signoff (ready_for_attestation = false).
    assert api.post("/api/reviews/rev-c-0001/emulated-attestation").status_code == 409
    assert api.post("/api/reviews/rev-nao-existe/emulated-attestation").status_code == 404
    assert not mock_db.LANDING


def test_clients_cannot_post_emulated_receipts_directly(api, mock_db):
    assert api.post("/api/attestations", json={**ATTESTATION, "cluster": "emulated"}).status_code == 422
