# Databricks notebook source
# MAGIC %md
# MAGIC # IASX — bootstrap da landing zone
# MAGIC Cria as subpastas do volume `landing` e, se `load_synthetic = true`, copia os casos sintéticos
# MAGIC (PDFs A–D, registro de casos e gabarito) que o bundle sincronizou em `data/synthetic/`.
# MAGIC Idempotente e sem sobrescrever a landing (o Auto Loader ingere cada arquivo uma única vez):
# MAGIC PDFs existentes são mantidos e o registro de casos ganha um nome pelo hash do conteúdo.

# COMMAND ----------

dbutils.widgets.text("landing_root", "/Volumes/workspace/iasx_clinical/landing")
dbutils.widgets.dropdown("load_synthetic", "true", ["true", "false"])

landing_root = dbutils.widgets.get("landing_root").rstrip("/")
load_synthetic = dbutils.widgets.get("load_synthetic") == "true"

FOLDERS = [
    "pdfs",
    "cases",
    "jev_decisions",
    "review_decisions",
    "attestations",
    "attestation_verifications",
    "gabarito",
]

# COMMAND ----------

import hashlib
import os
import shutil

for folder in FOLDERS:
    os.makedirs(f"{landing_root}/{folder}", exist_ok=True)
print("Pastas prontas:", ", ".join(FOLDERS))

# COMMAND ----------

if load_synthetic:
    # O notebook roda em <raiz>/src/jobs e os dados ficam em <raiz>/data/synthetic, onde <raiz> é a cópia do
    # bundle (.bundle/.../files) ou a Git folder, quando o notebook é aberto direto nela.
    synthetic_dir = os.path.abspath(os.path.join(os.getcwd(), "..", "..", "data", "synthetic"))
    if not os.path.isdir(synthetic_dir):
        raise FileNotFoundError(
            f"{synthetic_dir} não encontrado. Gere os casos com tools/generate_synthetic_cases.py e rode 'databricks bundle deploy'."
        )

    copied = skipped = 0
    for root, _, files in os.walk(os.path.join(synthetic_dir, "pdfs")):
        for name in files:
            if name.endswith(".pdf"):
                case_id = os.path.basename(root)
                target = f"{landing_root}/pdfs/{case_id}/{name}"
                if os.path.exists(target):
                    skipped += 1
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(os.path.join(root, name), target)
                copied += 1

    cases_src = os.path.join(synthetic_dir, "cases.json")
    with open(cases_src, "rb") as fh:
        cases_target = f"{landing_root}/cases/cases_seed_{hashlib.sha256(fh.read()).hexdigest()[:12]}.json"
    if not os.path.exists(cases_target):
        shutil.copyfile(cases_src, cases_target)
    # O gabarito é lido em batch (materialized view), então pode ser substituído.
    shutil.copyfile(os.path.join(synthetic_dir, "gabarito.csv"), f"{landing_root}/gabarito/gabarito.csv")
    print(f"{copied} PDFs sintéticos copiados ({skipped} já existiam) + {os.path.basename(cases_target)} + gabarito.csv")
