"""IASX — API consumida pelo JEV (frontend externo).

O JEV chama esta API servidor-a-servidor com um token OAuth do Databricks (service principal com CAN_USE no app).
A API lê as tabelas gold pelo SQL Warehouse e grava eventos na landing; nunca escreve tabelas diretamente.
Só aceita dados sintéticos e marca toda resposta com a finalidade pretendida (docs/regulatory/intended_use.md).
Documentação interativa: <url do app>/docs
"""

from datetime import datetime, timezone
from typing import Annotated

from databricks.sdk.errors import AlreadyExists, NotFound, ResourceConflict
from fastapi import FastAPI, File, HTTPException, Path, Request, UploadFile

import backend
from guards import INTENDED_USE, INTENDED_USE_HEADER, declares_synthetic
from models import TECH_ID, AttestationIn, CaseIn, ReviewCycleIn, ReviewDecisionIn

MAX_PDF_BYTES = 20 * 1024 * 1024

app = FastAPI(title="IASX Clinical Review — API do JEV", version="1.1.0", description=INTENDED_USE)


@app.middleware("http")
async def intended_use_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-IASX-Intended-Use"] = INTENDED_USE_HEADER
    return response

TechId = Annotated[str, Path(pattern=TECH_ID)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(rows: list[dict], what: str) -> dict:
    if not rows:
        raise HTTPException(404, f"{what} não encontrado")
    return rows[0]


def _write(feed: str, record: dict) -> dict:
    try:
        return {"landing_path": backend.write_feed(feed, [record]), "record": record}
    except (AlreadyExists, ResourceConflict):
        raise HTTPException(409, "arquivo já existe na landing; reenvie")


# --- Saúde e identidade -----------------------------------------------------------------------

@app.get("/api/health")
def health():
    backend.query("SELECT 1 AS ok")
    return {"status": "ok", "schema": backend.FQ_SCHEMA, "intended_use": INTENDED_USE}


@app.get("/api/whoami")
def whoami(request: Request):
    # Cabeçalhos injetados pelo proxy do Databricks Apps com a identidade de quem chamou.
    return {
        "user": request.headers.get("x-forwarded-user"),
        "email": request.headers.get("x-forwarded-email"),
    }


# --- Leitura ----------------------------------------------------------------------------------

@app.get("/api/cases")
def list_cases():
    return backend.list_cases()


@app.get("/api/cases/{case_id}/queue")
def review_queue(case_id: TechId):
    return backend.review_queue(case_id)


@app.get("/api/cases/{case_id}/timeline")
def timeline(case_id: TechId):
    return backend.timeline(case_id)


@app.get("/api/cases/{case_id}/comparison")
def temporal_comparison(case_id: TechId):
    return backend.temporal_comparison(case_id)


@app.get("/api/findings/{finding_id}/evidence")
def finding_evidence(finding_id: TechId):
    return backend.finding_evidence(finding_id)


@app.get("/api/documents/{document_id}/pages/{page_num}")
def document_page(document_id: TechId, page_num: Annotated[int, Path(ge=1)]):
    return _one(backend.document_page(document_id, page_num), "página")


@app.get("/api/reviews/{review_id}/attestation-payload")
def attestation_payload(review_id: TechId):
    return _one(backend.attestation_payload(review_id), "payload de atestação")


@app.get("/api/metrics")
def metrics():
    return backend.metrics()


# --- Escrita (landing) ------------------------------------------------------------------------

@app.post("/api/cases", status_code=201)
def create_case(case: CaseIn):
    return _write("cases", {**case.model_dump(), "created_at": _now()})


@app.post("/api/cases/{case_id}/documents/{document_id}", status_code=201)
async def upload_document(case_id: TechId, document_id: TechId, file: UploadFile = File(...)):
    content = await file.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF maior que 20 MB")
    if not content.startswith(b"%PDF"):
        raise HTTPException(415, "o arquivo não é um PDF")
    if not declares_synthetic(content):
        # Recusado antes de gravar: documento real não pode nem chegar à landing (LGPD).
        raise HTTPException(422, 'o MVP aceita somente PDFs sintéticos: o texto precisa conter "Documento sintético"')
    try:
        return {"landing_path": backend.write_pdf(case_id, document_id, content)}
    except (AlreadyExists, ResourceConflict):
        raise HTTPException(409, "document_id já existe para este caso; use outro document_id")


@app.post("/api/review-decisions", status_code=201)
def create_review_decision(decision: ReviewDecisionIn):
    return _write("review_decisions", {**decision.model_dump(), "decided_at": _now()})


@app.post("/api/attestations", status_code=201)
def create_attestation(attestation: AttestationIn):
    return _write("attestations", {**attestation.model_dump(), "submitted_at": _now()})


# --- Orquestração -----------------------------------------------------------------------------

@app.post("/api/review-cycle/runs", status_code=202)
def run_review_cycle(cycle: ReviewCycleIn | None = None):
    """Dispara iasx_review_cycle (pipeline → Jev → verificação on-chain → pipeline).
    Corpo opcional {"mode": "decisions_only"} depois do signoff: pula a extração e o Jev."""
    mode = (cycle or ReviewCycleIn()).mode
    return {"run_id": backend.run_review_cycle(mode), "mode": mode}


@app.get("/api/review-cycle/runs/{run_id}")
def review_cycle_status(run_id: int):
    try:
        return backend.run_status(run_id)
    except NotFound:
        raise HTTPException(404, "execução não encontrada")
