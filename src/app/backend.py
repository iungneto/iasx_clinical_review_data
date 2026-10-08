"""Acesso a dados da API do JEV.

Leitura: tabelas gold/silver pelo SQL Warehouse (mesmas consultas de src/sql/portal_queries.sql).
Escrita: somente arquivos novos na landing (JSON lines / PDF); a pipeline é a única que escreve tabelas.
Credenciais: service principal do app, injetado pelo Databricks Apps e lido por Config().
"""

import io
import json
import os
import re
import uuid
from datetime import datetime, timezone

from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

FQ_SCHEMA = os.environ["IASX_FQ_SCHEMA"]
LANDING_ROOT = os.environ["IASX_LANDING_ROOT"].rstrip("/")
WAREHOUSE_ID = os.environ["DATABRICKS_WAREHOUSE_ID"]
REVIEW_CYCLE_JOB_ID = os.getenv("IASX_REVIEW_CYCLE_JOB_ID")

if not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+", FQ_SCHEMA):
    raise RuntimeError(f"IASX_FQ_SCHEMA inválido: {FQ_SCHEMA!r}")

cfg = Config()
w = WorkspaceClient(config=cfg)


def _plain(value):
    # Arrays/structs chegam como numpy/pyarrow; o JSON da resposta precisa de tipos Python.
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "as_py"):
        return value.as_py()
    return value


def query(statement: str, **params) -> list[dict]:
    with sql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    ) as conn, conn.cursor() as cur:
        cur.execute(statement.format(s=FQ_SCHEMA), params or None)
        cols = [c[0] for c in cur.description]
        return [{k: _plain(v) for k, v in zip(cols, row)} for row in cur.fetchall()]


# --- Leitura (portal_queries.sql) -------------------------------------------------------------

def list_cases() -> list[dict]:
    return query(
        """SELECT case_id, review_id, scenario, review_state, onchain_status, is_finalized,
                  n_documents, n_findings, n_pending_human, tx_signature, cluster, submitted_at, verified_at
           FROM {s}.gold_review_status
           ORDER BY created_at DESC"""
    )


def review_queue(case_id: str) -> list[dict]:
    return query(
        """SELECT finding_id, finding_type, finding_subtype, test_code, exam_date, summary,
                  jev_status, jev_needs_review, jev_priority, jev_is_clear,
                  jev_model, jev_prompt_version,
                  needs_review_final, review_reasons, priority_final, priority_reason, safety_flags, finding_state,
                  reviewer_action, corrected_value, corrected_unit
           FROM {s}.gold_review_queue
           WHERE case_id = :case_id
           ORDER BY priority_rank, finding_type, exam_date""",
        case_id=case_id,
    )


def finding_evidence(finding_id: str) -> list[dict]:
    return query(
        """SELECT e.document_id, e.page_num, e.line_no, e.char_start, e.char_end, e.source_text
           FROM {s}.gold_findings
           LATERAL VIEW explode(evidence) t AS e
           WHERE finding_id = :finding_id""",
        finding_id=finding_id,
    )


def document_page(document_id: str, page_num: int) -> list[dict]:
    return query(
        """SELECT page_text
           FROM {s}.silver_document_pages
           WHERE document_id = :document_id AND page_num = :page_num""",
        document_id=document_id,
        page_num=page_num,
    )


def timeline(case_id: str) -> list[dict]:
    return query(
        """SELECT exam_date, timeline_position, test_code, test_name_raw, value_raw, unit, value_status,
                  document_id, page_num, source_text
           FROM {s}.gold_timeline
           WHERE case_id = :case_id
           ORDER BY exam_date NULLS LAST, test_code""",
        case_id=case_id,
    )


def temporal_comparison(case_id: str) -> list[dict]:
    return query(
        """SELECT test_code, test_name_raw, previous_date, exam_date, previous_value, value, unit,
                  delta_abs, delta_pct, direction
           FROM {s}.gold_temporal_comparison
           WHERE case_id = :case_id
           ORDER BY test_code, exam_date""",
        case_id=case_id,
    )


def attestation_payload(review_id: str) -> list[dict]:
    return query(
        """SELECT review_id, input_hash, analysis_hash, reviewed_hash, workflow_version, model_version,
                  target_status, reviewer_tech_id, signoff_at, ready_for_attestation
           FROM {s}.gold_attestation_payload
           WHERE review_id = :review_id""",
        review_id=review_id,
    )


def metrics() -> dict:
    return {
        "cases": query("SELECT * FROM {s}.gold_mvp_metrics ORDER BY case_id"),
        "benchmark": query("SELECT outcome, count(*) AS n FROM {s}.gold_benchmark GROUP BY outcome"),
    }


# --- Escrita na landing (docs/data_contracts.md) ----------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upload(relative_path: str, data: bytes) -> str:
    path = f"{LANDING_ROOT}/{relative_path}"
    # overwrite=False: o Auto Loader ingere cada arquivo uma vez, então nunca reescrevemos.
    w.files.upload(path, io.BytesIO(data), overwrite=False)
    return path


def write_feed(feed: str, records: list[dict]) -> str:
    name = f"jev_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}.json"
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    return _upload(f"{feed}/{name}", body.encode("utf-8"))


def write_pdf(case_id: str, document_id: str, content: bytes) -> str:
    return _upload(f"pdfs/{case_id}/{document_id}.pdf", content)


def run_review_cycle(mode: str = "full") -> int:
    if not REVIEW_CYCLE_JOB_ID:
        raise RuntimeError("IASX_REVIEW_CYCLE_JOB_ID não configurado")
    return w.jobs.run_now(job_id=int(REVIEW_CYCLE_JOB_ID), job_parameters={"mode": mode}).run_id


def run_status(run_id: int) -> dict:
    run = w.jobs.get_run(run_id=run_id)
    state = run.state
    return {
        "run_id": run_id,
        "life_cycle_state": state.life_cycle_state.value if state and state.life_cycle_state else None,
        "result_state": state.result_state.value if state and state.result_state else None,
        "run_page_url": run.run_page_url,
    }
