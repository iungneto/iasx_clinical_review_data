# Databricks notebook source
# MAGIC %md
# MAGIC # IASX — verificação da atestação on-chain (Solana Devnet)
# MAGIC Para cada atestação ainda não verificada (ou cuja última verificação falhou):
# MAGIC 0. recusa qualquer RPC fora da Devnet (o MVP só atesta na Devnet);
# MAGIC 1. confirma a transação (`getSignatureStatuses`);
# MAGIC 2. lê a conta PDA da revisão (`getAccountInfo`), checa o owner = programa IASX e decodifica o layout
# MAGIC    descrito em `docs/onchain_account_layout.md` (`onchain_layout.py`);
# MAGIC 3. grava o resultado em `landing/attestation_verifications/`.
# MAGIC
# MAGIC A comparação dos hashes on-chain com o payload recalculado é feita na pipeline (`gold_review_status`):
# MAGIC é ela que decide se a revisão passa para **ATTESTED**.

# COMMAND ----------

dbutils.widgets.text("fq_schema", "workspace.iasx_clinical")
dbutils.widgets.text("landing_root", "/Volumes/workspace/iasx_clinical/landing")
dbutils.widgets.text("solana_rpc_url", "https://api.devnet.solana.com")
dbutils.widgets.text("solana_program_id", "")

fq_schema = dbutils.widgets.get("fq_schema")
landing_root = dbutils.widgets.get("landing_root").rstrip("/")
rpc_url = dbutils.widgets.get("solana_rpc_url")
program_id = dbutils.widgets.get("solana_program_id")

# COMMAND ----------

import base64
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.getcwd())  # o notebook roda em src/jobs, ao lado de onchain_layout.py
from onchain_layout import assert_devnet, decode_account, review_id_hash  # noqa: E402

assert_devnet(rpc_url)


def rpc(method: str, params: list):
    resp = requests.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"{method}: {body['error']}")
    return body["result"]


def verify(att) -> dict:
    result = {
        "review_id": att.review_id,
        "pda_address": att.pda_address,
        "tx_signature": att.tx_signature,
        "account_found": False,
        "tx_confirmed": False,
        "onchain_input_hash": None,
        "onchain_analysis_hash": None,
        "onchain_reviewed_hash": None,
        "onchain_status": None,
        "slot": None,
        "error": None,
    }
    try:
        status = rpc("getSignatureStatuses", [[att.tx_signature], {"searchTransactionHistory": True}])["value"][0]
        result["tx_confirmed"] = bool(
            status and status.get("err") is None and status.get("confirmationStatus") in ("confirmed", "finalized")
        )
        info = rpc("getAccountInfo", [att.pda_address, {"encoding": "base64", "commitment": "confirmed"}])
        result["slot"] = info["context"]["slot"]
        account = info["value"]
        if account is None:
            result["error"] = "PDA não encontrada"
            return result
        if program_id and account["owner"] != program_id:
            result["error"] = f"owner inesperado: {account['owner']}"
            return result
        decoded = decode_account(base64.b64decode(account["data"][0]))
        if decoded["review_id_hash"] != review_id_hash(att.review_id):
            result["error"] = "review_id_hash on-chain não corresponde ao review_id"
            return result
        result.update(
            account_found=True,
            onchain_input_hash=decoded["input_hash"],
            onchain_analysis_hash=decoded["analysis_hash"],
            onchain_reviewed_hash=decoded["reviewed_hash"],
            onchain_status=decoded["status"],
        )
    except Exception as exc:  # noqa: BLE001 - falha de verificação é um resultado, não um crash do job
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    return result


# COMMAND ----------

to_verify = spark.sql(f"""
  SELECT a.review_id, a.pda_address, a.tx_signature
  FROM {fq_schema}.silver_attestations a
  LEFT JOIN {fq_schema}.silver_attestation_verifications v ON v.review_id = a.review_id
  WHERE v.review_id IS NULL
     OR v.tx_signature <> a.tx_signature
     OR v.error IS NOT NULL
     OR NOT v.tx_confirmed
""").collect()
print(f"{len(to_verify)} atestações para verificar em {rpc_url}")

if to_verify:
    now = datetime.now(timezone.utc).isoformat()
    results = [{**verify(att), "verified_at": now} for att in to_verify]
    out = f"{landing_root}/attestation_verifications/verify_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}.json"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in results))
    ok = sum(r["account_found"] and r["tx_confirmed"] for r in results)
    print(f"{ok}/{len(results)} verificadas com sucesso → {out}")
