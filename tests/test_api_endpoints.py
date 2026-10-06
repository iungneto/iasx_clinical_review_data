"""API do JEV de ponta a ponta (src/app/app.py) sobre a base mockada (tools/mock_db).

Cada teste cita o item da Matriz Regulatória que verifica (docs/regulatory/risk_and_compliance.md).
"""

import re

import pytest

from conftest import ROOT
from test_api_contracts import ATTESTATION

PDFS = ROOT / "data/synthetic/pdfs"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _queue(api, case_id):
    resp = api.get(f"/api/cases/{case_id}/queue")
    assert resp.status_code == 200
    return resp.json()


# --- §1, §5, §14: finalidade pretendida anunciada ---------------------------------------------------

@pytest.mark.parametrize("path", ["/api/health", "/api/cases", "/api/cases/CASE-C/queue", "/api/cases/../x", "/api/nao-existe"])
def test_every_response_declares_intended_use(api, path):
    assert api.get(path).headers["X-IASX-Intended-Use"] == "synthetic-demo; review-support-only; not-for-clinical-use"


def test_health_exposes_intended_use_text(api):
    body = api.get("/api/health").json()
    assert body["status"] == "ok"
    assert "100% sintéticos" in body["intended_use"] and "não diagnostica" in body["intended_use"]


# --- Leitura --------------------------------------------------------------------------------------

def test_cases_are_the_synthetic_scenarios(api):
    cases = api.get("/api/cases").json()
    assert {c["case_id"] for c in cases} == {"CASE-A", "CASE-B", "CASE-C", "CASE-D"}
    assert {c["review_state"] for c in cases if c["case_id"] == "CASE-A"} == {"AI_REVIEW_READY"}


def test_queue_covers_every_scenario_the_matrix_asks_to_test(api):
    """§10: casos normais, mudanças temporais, conflitos, lacunas, unidades diferentes, ambíguos e contraditórios."""
    seen = {(f["finding_type"], f["finding_subtype"]) for case in ("CASE-B", "CASE-C", "CASE-D") for f in _queue(api, case)}
    assert _queue(api, "CASE-A") == []  # normal: nenhum achado
    for expected in [
        ("TEMPORAL_VARIATION", "UP"),
        ("CONFLICT", "DIVERGENT_VALUES"),
        ("GAP", "MISSING_DATE"),
        ("TEMPORAL_VARIATION", "UNIT_CHANGED"),
        ("GAP", "AMBIGUOUS_VALUE"),
        ("GAP", "NOT_SYNTHETIC_DOCUMENT"),
    ]:
        assert expected in seen, expected


@pytest.mark.parametrize("case_id", ["CASE-B", "CASE-C", "CASE-D"])
def test_every_decision_has_an_objective_traceable_reason(api, case_id):
    """§10: justificativa objetiva e rastreável; versão do modelo e das perguntas."""
    for f in _queue(api, case_id):
        assert f["priority_reason"] and f["review_reasons"], f["finding_id"]
        assert f["jev_model"] and f["jev_prompt_version"], f["finding_id"]


@pytest.mark.parametrize("case_id", ["CASE-C", "CASE-D"])
def test_conflicts_and_gaps_always_go_to_a_human(api, case_id):
    """§14: regras para conflitos, lacunas e ausência de informação."""
    for f in _queue(api, case_id):
        if f["finding_type"] in ("CONFLICT", "GAP"):
            assert f["needs_review_final"] and f["priority_final"] != "baixa", f
            assert f["finding_state"] == "HUMAN_REVIEW_REQUIRED"


@pytest.mark.parametrize("case_id", ["CASE-B", "CASE-C", "CASE-D"])
def test_every_finding_has_source_evidence_matching_the_page(api, case_id):
    """§14: evidência/fonte preservada para cada achado (documento, página e o trecho exato)."""
    for f in _queue(api, case_id):
        evidence = api.get(f"/api/findings/{f['finding_id']}/evidence").json()
        assert evidence, f["finding_id"]
        for e in evidence:
            if e["char_start"] is None:  # página sem texto: a fonte é a própria página
                assert f["finding_subtype"] in ("NON_TEXTUAL_PAGE", "NOT_SYNTHETIC_DOCUMENT")
                continue
            page = api.get(f"/api/documents/{e['document_id']}/pages/{e['page_num']}").json()["page_text"]
            assert page[e["char_start"]:e["char_end"]] == e["source_text"]


def test_pages_expose_no_direct_identifiers(api):
    """§3 (LGPD): mesmo sintéticos, nome/CPF/contato chegam mascarados ao frontend."""
    for doc, page in [("A_lab_20260310", 1), ("C_resumo_alta", 1), ("D_lab_20260115", 1)]:
        text = api.get(f"/api/documents/{doc}/pages/{page}").json()["page_text"]
        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", text)  # CPF
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text)  # e-mail
        assert re.search(r"Paciente: \*+", text)


def test_document_without_synthetic_declaration_is_not_propagated(api):
    """§3: o texto de PDF sem a declaração de dado sintético não chega à API."""
    assert api.get("/api/documents/D_sem_marcacao/pages/1").json()["page_text"] in (None, "")


def test_missing_information_is_not_filled(api):
    """§10: não preencher informações ausentes por inferência."""
    no_unit = [r for r in api.get("/api/cases/CASE-D/timeline").json() if r["test_code"] == "K" and r["unit"] is None]
    assert no_unit, "Caso D tem potássio sem unidade"


def test_temporal_summaries_are_descriptive_dates_not_epoch_days(api):
    """§10: variação descrita como diferença entre datas, sem causalidade; datas legíveis para o revisor."""
    for case in ("CASE-B", "CASE-D"):
        for f in _queue(api, case):
            if f["finding_type"] == "TEMPORAL_VARIATION":
                assert re.search(r"entre \d{2}/\d{2}/\d{4} .* e \d{2}/\d{2}/\d{4}", f["summary"]), f["summary"]
                assert not re.search(r"(?i)piora|melhora|causa|devido|indica", f["summary"])


def test_attestation_payload_is_technical_only(api):
    """§12: on-chain só hashes, versões, status e IDs técnicos."""
    payload = api.get("/api/reviews/rev-c-0001/attestation-payload").json()
    assert set(payload) == {
        "review_id", "input_hash", "analysis_hash", "reviewed_hash", "workflow_version", "model_version",
        "target_status", "reviewer_tech_id", "signoff_at", "ready_for_attestation",
    }
    for h in ("input_hash", "analysis_hash", "reviewed_hash"):
        assert SHA256.match(payload[h])
    assert payload["model_version"].startswith("extract-rules-")  # versão que realmente rodou (§10)


def test_unknown_resources_are_404(api):
    assert api.get("/api/reviews/rev-x/attestation-payload").status_code == 404
    assert api.get("/api/documents/A_lab_20260310/pages/9").status_code == 404


def test_free_text_and_path_traversal_are_refused_in_ids(api):
    assert api.get("/api/cases/Maria da Silva/queue").status_code == 422
    assert api.get("/api/findings/..%2F..%2Fsecret/evidence").status_code in (404, 422)


def test_metrics_report_benchmark_against_expected_answers(api):
    """§14: casos de teste com respostas esperadas (gabarito × saída)."""
    body = api.get("/api/metrics").json()
    assert {c["case_id"] for c in body["cases"]} == {"CASE-A", "CASE-B", "CASE-C", "CASE-D"}
    assert body["benchmark"] == [{"outcome": "MATCHED", "n": 20}]


# --- Escrita (landing mockada) --------------------------------------------------------------------

def test_case_registration_requires_synthetic_classification(api, mock_db):
    """§3, §14: dados 100% sintéticos."""
    assert api.post("/api/cases", json={"case_id": "CASE-X", "review_id": "rev-x"}).status_code == 422
    resp = api.post("/api/cases", json={"case_id": "CASE-X", "review_id": "rev-x", "data_classification": "SYNTHETIC"})
    assert resp.status_code == 201
    [record] = mock_db.feed_records("cases")
    assert record["data_classification"] == "SYNTHETIC" and record["created_at"]


def test_upload_accepts_synthetic_pdf_and_never_overwrites(api, mock_db):
    pdf = (PDFS / "CASE-A/A_lab_20260310.pdf").read_bytes()
    url = "/api/cases/CASE-X/documents/X_lab_1"
    assert api.post(url, files={"file": ("x.pdf", pdf, "application/pdf")}).status_code == 201
    assert api.post(url, files={"file": ("x.pdf", pdf, "application/pdf")}).status_code == 409
    assert list(mock_db.LANDING) == ["/Volumes/mock/iasx_clinical/landing/pdfs/CASE-X/X_lab_1.pdf"]


def test_upload_refuses_pdf_without_synthetic_declaration_before_writing(api, mock_db):
    """§3: documento possivelmente real não chega nem à landing."""
    pdf = (PDFS / "CASE-D/D_sem_marcacao.pdf").read_bytes()
    resp = api.post("/api/cases/CASE-X/documents/X_real", files={"file": ("x.pdf", pdf, "application/pdf")})
    assert resp.status_code == 422 and not mock_db.LANDING


def test_upload_refuses_non_pdf(api, mock_db):
    resp = api.post("/api/cases/CASE-X/documents/X_txt", files={"file": ("x.txt", b"Documento sintetico", "text/plain")})
    assert resp.status_code == 415 and not mock_db.LANDING


def test_review_decisions_follow_the_signoff_contract(api, mock_db):
    """§1: o profissional decide; SIGNOFF só no nível da revisão."""
    ok = {"review_id": "rev-c-0001", "scope": "REVIEW", "action": "SIGNOFF", "reviewer_tech_id": "reviewer-7f3a"}
    assert api.post("/api/review-decisions", json=ok).status_code == 201
    bad = {**ok, "scope": "FINDING", "finding_id": "abc"}
    assert api.post("/api/review-decisions", json=bad).status_code == 422
    assert [r["action"] for r in mock_db.feed_records("review_decisions")] == ["SIGNOFF"]


def test_attestation_receipt_only_on_devnet(api, mock_db):
    """§12, §14: Solana apenas para atestação técnica na Devnet."""
    assert api.post("/api/attestations", json={**ATTESTATION, "cluster": "mainnet-beta"}).status_code == 422
    assert api.post("/api/attestations", json=ATTESTATION).status_code == 201
    [record] = mock_db.feed_records("attestations")
    assert record["cluster"] == "devnet" and record["status"] == "SUBMITTED"


def test_review_cycle_can_be_triggered_and_followed(api):
    run_id = api.post("/api/review-cycle/runs").json()["run_id"]
    assert api.get(f"/api/review-cycle/runs/{run_id}").json()["result_state"] == "SUCCESS"
    assert api.get("/api/review-cycle/runs/999999").status_code == 404


def test_review_cycle_after_signoff_skips_extraction(api):
    assert api.post("/api/review-cycle/runs").json()["mode"] == "full"
    assert api.post("/api/review-cycle/runs", json={"mode": "decisions_only"}).json()["mode"] == "decisions_only"
    assert api.post("/api/review-cycle/runs", json={"mode": "tudo"}).status_code == 422
