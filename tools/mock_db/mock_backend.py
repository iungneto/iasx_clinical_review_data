"""Backend mockado da API do JEV: mesma interface de src/app/backend.py, sem Databricks.

Leitura: tabelas exportadas do workspace em tools/mock_db/tables/*.json (export_from_workspace.py), com o
mesmo filtro e a mesma ordenação das consultas reais. As colunas devolvidas são lidas do SQL de
src/app/backend.py, então o mock não diverge do contrato da API real.
Escrita: landing em memória (LANDING), com a mesma regra de nunca sobrescrever arquivo.

Uso: tests/test_api_endpoints.py (pytest) e tools/mock_db/serve.py (API local para o frontend JEV).
"""

import ast
import json
import re
import uuid
from datetime import datetime, timezone
from functools import cache
from pathlib import Path

from databricks.sdk.errors import AlreadyExists, NotFound

ROOT = Path(__file__).resolve().parents[2]
TABLES_DIR = Path(__file__).resolve().parent / "tables"

FQ_SCHEMA = "mock.iasx_clinical"
LANDING_ROOT = "/Volumes/mock/iasx_clinical/landing"

LANDING: dict[str, bytes] = {}
RUNS: dict[int, dict] = {}


def reset() -> None:
    """Esvazia a landing e as execuções (isolamento entre testes)."""
    LANDING.clear()
    RUNS.clear()


@cache
def table(name: str) -> tuple[dict, ...]:
    return tuple(json.loads((TABLES_DIR / f"{name}.json").read_text(encoding="utf-8")))


@cache
def select_columns(function: str) -> tuple[str, ...]:
    """Colunas do SELECT da função homônima em src/app/backend.py (alias ou nome sem prefixo de tabela)."""
    tree = ast.parse((ROOT / "src/app/backend.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
    sql = next(n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str) and "SELECT" in n.value)
    select = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.S).group(1)
    names = []
    for expr in select.split(","):
        expr = expr.strip()
        alias = re.search(r"\bAS\s+(\w+)$", expr, re.I)
        names.append(alias.group(1) if alias else expr.split(".")[-1])
    return tuple(names)


def _project(rows, function: str) -> list[dict]:
    cols = select_columns(function)
    return [{c: row.get(c) for c in cols} for row in rows]


def _sorted(rows, *keys, desc=False, nulls_last=()):
    # Spark: NULL vem primeiro em ASC e por último em DESC, salvo NULLS LAST explícito.
    def key(row):
        out = []
        for k in keys:
            v = row.get(k)
            null_rank = (1 if k in nulls_last else 0) if v is None else (0 if k in nulls_last else 1)
            out.append((null_rank, v if v is not None else ""))
        return out

    return sorted(rows, key=key, reverse=desc)


def query(statement: str, **params) -> list[dict]:
    if statement.strip().upper() == "SELECT 1 AS OK":
        return [{"ok": 1}]
    raise NotImplementedError("o backend mockado só responde às consultas nomeadas (list_cases, review_queue, ...)")


# --- Leitura (mesmas consultas de src/app/backend.py) -----------------------------------------

def list_cases() -> list[dict]:
    return _project(_sorted(table("gold_review_status"), "created_at", desc=True), "list_cases")


def review_queue(case_id: str) -> list[dict]:
    rows = [r for r in table("gold_review_queue") if r["case_id"] == case_id]
    return _project(_sorted(rows, "priority_rank", "finding_type", "exam_date"), "review_queue")


def finding_evidence(finding_id: str) -> list[dict]:
    rows = [e for r in table("gold_findings") if r["finding_id"] == finding_id for e in r["evidence"]]
    return _project(rows, "finding_evidence")


def document_page(document_id: str, page_num: int) -> list[dict]:
    rows = [r for r in table("silver_document_pages") if r["document_id"] == document_id and r["page_num"] == page_num]
    return _project(rows, "document_page")


def timeline(case_id: str) -> list[dict]:
    rows = [r for r in table("gold_timeline") if r["case_id"] == case_id]
    return _project(_sorted(rows, "exam_date", "test_code", nulls_last=("exam_date",)), "timeline")


def temporal_comparison(case_id: str) -> list[dict]:
    rows = [r for r in table("gold_temporal_comparison") if r["case_id"] == case_id]
    return _project(_sorted(rows, "test_code", "exam_date"), "temporal_comparison")


def attestation_payload(review_id: str) -> list[dict]:
    rows = [r for r in table("gold_attestation_payload") if r["review_id"] == review_id]
    return _project(rows, "attestation_payload")


def metrics() -> dict:
    outcomes: dict[str, int] = {}
    for r in table("gold_benchmark"):
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {
        "cases": [dict(r) for r in _sorted(table("gold_mvp_metrics"), "case_id")],
        "benchmark": [{"outcome": k, "n": v} for k, v in outcomes.items()],
    }


# --- Escrita na landing (em memória) ----------------------------------------------------------

def _upload(relative_path: str, data: bytes) -> str:
    path = f"{LANDING_ROOT}/{relative_path}"
    if path in LANDING:  # mesmo comportamento de files.upload(overwrite=False)
        raise AlreadyExists(f"{path} já existe")
    LANDING[path] = data
    return path


def write_feed(feed: str, records: list[dict]) -> str:
    name = f"jev_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}.json"
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    return _upload(f"{feed}/{name}", body.encode("utf-8"))


def write_pdf(case_id: str, document_id: str, content: bytes) -> str:
    return _upload(f"pdfs/{case_id}/{document_id}.pdf", content)


def feed_records(feed: str) -> list[dict]:
    """Registros gravados num feed da landing mockada (para conferir o que a API escreveu)."""
    prefix = f"{LANDING_ROOT}/{feed}/"
    return [json.loads(line) for path, body in LANDING.items() if path.startswith(prefix)
            for line in body.decode("utf-8").splitlines()]


def run_review_cycle(mode: str = "full") -> int:
    run_id = 1000 + len(RUNS)
    RUNS[run_id] = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS", "mode": mode}
    return run_id


def run_status(run_id: int) -> dict:
    if run_id not in RUNS:
        raise NotFound(f"run {run_id} não existe")
    return {"run_id": run_id, **RUNS[run_id], "run_page_url": f"https://mock.invalid/jobs/runs/{run_id}"}
