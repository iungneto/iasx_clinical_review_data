# Databricks notebook source
# MAGIC %md
# MAGIC # IASX — bootstrap da landing zone
# MAGIC Cria as subpastas do volume `landing` e, se `load_synthetic = true`, copia os casos sintéticos
# MAGIC (PDFs A/B/C, registro de casos e gabarito) que o bundle sincronizou em `data/synthetic/`.
# MAGIC Idempotente: pode ser executado várias vezes.

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

import os
import shutil

for folder in FOLDERS:
    os.makedirs(f"{landing_root}/{folder}", exist_ok=True)
print("Pastas prontas:", ", ".join(FOLDERS))

# COMMAND ----------

if load_synthetic:
    # O notebook roda a partir de <bundle>/files/src/jobs; os dados ficam em <bundle>/files/data/synthetic.
    synthetic_dir = os.path.abspath(os.path.join(os.getcwd(), "..", "..", "data", "synthetic"))
    if not os.path.isdir(synthetic_dir):
        raise FileNotFoundError(
            f"{synthetic_dir} não encontrado. Gere os casos com tools/generate_synthetic_cases.py e rode 'databricks bundle deploy'."
        )

    copied = 0
    for root, _, files in os.walk(os.path.join(synthetic_dir, "pdfs")):
        for name in files:
            if name.endswith(".pdf"):
                case_id = os.path.basename(root)
                os.makedirs(f"{landing_root}/pdfs/{case_id}", exist_ok=True)
                shutil.copyfile(os.path.join(root, name), f"{landing_root}/pdfs/{case_id}/{name}")
                copied += 1

    shutil.copyfile(os.path.join(synthetic_dir, "cases.json"), f"{landing_root}/cases/cases_seed.json")
    shutil.copyfile(os.path.join(synthetic_dir, "gabarito.csv"), f"{landing_root}/gabarito/gabarito.csv")
    print(f"{copied} PDFs sintéticos copiados + cases_seed.json + gabarito.csv")
