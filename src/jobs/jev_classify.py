# Databricks notebook source
# MAGIC %md
# MAGIC # IASX — classificação estruturada com o Jev (server-side)
# MAGIC Para cada achado sem decisão do Jev (ou com decisão de outra versão das perguntas, em revisão ainda não
# MAGIC finalizada), faz três perguntas de **workflow** (nunca diagnóstico/tratamento):
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
# MAGIC Cada decisão registra a versão das perguntas (`jev_prompt_version`), o modelo, o hash do que foi enviado e a
# MAGIC resposta bruta, para reconstruir qual versão gerou qual saída.
# MAGIC
# MAGIC A chave fica no secret scope (`databricks secrets put-secret iasx jev_api_key`), nunca no código.
# MAGIC **Confirme o formato de request/response em https://api.typesafe.ai/docs** — está isolado em
# MAGIC `build_request` e `extract_answer` de `jev_contract.py`.

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

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())  # o notebook roda em src/jobs, ao lado de jev_contract.py
from jev_contract import PROMPT_VERSION, JevClient, MockJev, classify  # noqa: E402

workflow_version = dbutils.widgets.get("workflow_version")

# COMMAND ----------

# Pendente = sem decisão, ou decisão gerada por outra versão das perguntas (mudança de prompt é rastreada e reavaliada).
# Revisão já finalizada (ATTESTED) não é reclassificada: mudaria o analysis_hash que está on-chain.
open_reviews = spark.table(f"{fq_schema}.gold_review_status").where("NOT is_finalized").select("review_id")
pending = (
    spark.table(f"{fq_schema}.gold_review_queue")
    .join(open_reviews, "review_id")
    .where(f"jev_status = 'PENDING' OR coalesce(jev_prompt_version, '') <> '{PROMPT_VERSION}'")
    .select("finding_id", "review_id", "finding_type", "finding_subtype", "summary")
    .collect()
)
print(f"{len(pending)} achados aguardando o Jev (perguntas {PROMPT_VERSION})")

if pending:
    if jev_mode == "live":
        api_key = dbutils.secrets.get(dbutils.widgets.get("secret_scope"), "jev_api_key")
        jev = JevClient(base_url, api_key, dbutils.widgets.get("jev_model"))
    else:
        jev = MockJev()

    records = [
        {
            "finding_id": row.finding_id,
            "review_id": row.review_id,
            **classify(jev, row.finding_type, row.finding_subtype, row.summary),
            "workflow_version": workflow_version,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        for row in pending
    ]

    out = f"{landing_root}/jev_decisions/jev_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}.json"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    print(f"{len(records)} decisões gravadas em {out} ({sum(not r['jev_response_valid'] for r in records)} inválidas)")
