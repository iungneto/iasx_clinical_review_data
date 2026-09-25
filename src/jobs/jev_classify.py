# Databricks notebook source
# MAGIC %md
# MAGIC # IASX — classificação estruturada com o Jev (server-side)
# MAGIC Para cada achado sem decisão do Jev, faz três perguntas de **workflow** (nunca diagnóstico/tratamento):
# MAGIC
# MAGIC | Pergunta | Schema Jev | Saída |
# MAGIC |---|---|---|
# MAGIC | O achado precisa de revisão humana? | Noul | `needs_review` (bool) |
# MAGIC | Qual a prioridade da revisão? | Choice (baixa/media/alta) | `priority` |
# MAGIC | A informação está clara o suficiente para apresentação? | Noul | `is_clear` (bool) |
# MAGIC
# MAGIC O resultado é gravado como JSON em `landing/jev_decisions/`, e a pipeline o ingere (bronze → silver via Auto CDC).
# MAGIC Resposta fora do schema **não** é descartada: vai com `jev_response_valid = false` e a regra de segurança
# MAGIC da gold força revisão humana com prioridade alta.
# MAGIC
# MAGIC A chave fica no secret scope (`databricks secrets put-secret iasx jev_api_key`), nunca no código.
# MAGIC **Confirme o formato de request/response em https://api.typesafe.ai/docs** — está isolado em
# MAGIC `build_request` e `extract_answer` abaixo.

# COMMAND ----------

dbutils.widgets.text("fq_schema", "workspace.iasx_clinical")
dbutils.widgets.text("landing_root", "/Volumes/workspace/iasx_clinical/landing")
dbutils.widgets.text("secret_scope", "iasx")
dbutils.widgets.text("workflow_version", "iasx-wf-1.0.0")
dbutils.widgets.dropdown("jev_mode", "live", ["live", "mock"])
dbutils.widgets.text("jev_base_url", "https://api.typesafe.ai")
dbutils.widgets.text("jev_model", "")  # vazio = primeiro modelo retornado por GET /v1/models

fq_schema = dbutils.widgets.get("fq_schema")
landing_root = dbutils.widgets.get("landing_root").rstrip("/")
jev_mode = dbutils.widgets.get("jev_mode")
base_url = dbutils.widgets.get("jev_base_url").rstrip("/")

# COMMAND ----------

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

import requests

PRIORITIES = ["baixa", "media", "alta"]

QUESTIONS = {
    "needs_review": (
        "noul",
        "Este achado extraído de um documento clínico sintético precisa ser revisado por um profissional "
        "antes de ser apresentado como confirmado? Responda sim ou não. Não faça diagnóstico.",
    ),
    "priority": (
        "choice",
        "Qual a prioridade de revisão deste achado para o fluxo de trabalho (não é prioridade clínica)?",
    ),
    "is_clear": (
        "noul",
        "A informação deste achado está clara e completa o suficiente para ser apresentada ao profissional? "
        "Responda sim ou não.",
    ),
}


def finding_context(row) -> str:
    # Só o necessário para a decisão de workflow: tipo, subtipo e resumo. Sem case_id/review_id.
    return f"Tipo: {row.finding_type}. Subtipo: {row.finding_subtype}. Resumo: {row.summary}"


def build_request(model: str, schema: str, question: str, context: str) -> dict:
    """Monta o corpo de POST /v1/systemone. Ajuste aqui se o contrato publicado divergir."""
    body = {"model": model, "schema": schema, "input": f"{question}\n\n{context}"}
    if schema == "choice":
        body["options"] = PRIORITIES
    return body


def extract_answer(schema: str, payload: dict):
    """Normaliza a resposta para bool (Noul) ou uma das PRIORITIES (Choice). None = fora do schema."""
    raw = payload.get("output", payload)
    if isinstance(raw, dict):
        raw = raw.get("answer", raw.get("value", raw.get("choice")))
    if schema == "noul":
        if isinstance(raw, bool):
            return raw
        token = str(raw).strip().lower()
        return {"yes": True, "sim": True, "true": True, "no": False, "nao": False, "não": False, "false": False}.get(token)
    token = str(raw).strip().lower().replace("é", "e")
    return token if token in PRIORITIES else None


class JevClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        self.model = model or self._first_model()

    def _first_model(self) -> str:
        resp = self.session.get(f"{self.base_url}/v1/models", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", data) if isinstance(data, dict) else data
        return models[0]["id"] if isinstance(models[0], dict) else models[0]

    def ask(self, schema: str, question: str, context: str):
        body = build_request(self.model, schema, question, context)
        for attempt in range(3):
            resp = self.session.post(f"{self.base_url}/v1/systemone", json=body, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return extract_answer(schema, resp.json())


class MockJev:
    """Determinístico, apenas para ensaio da demo sem chave. Nunca usar como resultado real."""

    model = "mock-jev"

    def ask(self, schema: str, question: str, context: str):
        risky = any(t in context for t in ("CONFLICT", "GAP", "UNIT_CHANGED"))
        if schema == "choice":
            return "alta" if risky else "media"
        return True if "precisa ser revisado" in question else not risky


# COMMAND ----------

pending = (
    spark.table(f"{fq_schema}.gold_review_queue")
    .where("jev_status = 'PENDING'")
    .select("finding_id", "review_id", "finding_type", "finding_subtype", "summary")
    .collect()
)
print(f"{len(pending)} achados aguardando o Jev")

if pending:
    if jev_mode == "live":
        api_key = dbutils.secrets.get(dbutils.widgets.get("secret_scope"), "jev_api_key")
        jev = JevClient(base_url, api_key, dbutils.widgets.get("jev_model"))
    else:
        jev = MockJev()

    records = []
    for row in pending:
        context = finding_context(row)
        answers, valid = {}, True
        for field, (schema, question) in QUESTIONS.items():
            try:
                answers[field] = jev.ask(schema, question, context)
            except requests.RequestException as exc:
                print(f"Falha no Jev para {row.finding_id[:12]}: {type(exc).__name__}")
                answers[field] = None
            valid = valid and answers[field] is not None
        records.append(
            {
                "finding_id": row.finding_id,
                "review_id": row.review_id,
                "needs_review": answers["needs_review"],
                "priority": answers["priority"],
                "is_clear": answers["is_clear"],
                "jev_model": jev.model,
                "jev_request_hash": hashlib.sha256(context.encode()).hexdigest(),
                "jev_response_valid": valid,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    out = f"{landing_root}/jev_decisions/jev_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}.json"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    print(f"{len(records)} decisões gravadas em {out} ({sum(not r['jev_response_valid'] for r in records)} inválidas)")
