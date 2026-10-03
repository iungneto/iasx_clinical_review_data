# Databricks notebook source
# MAGIC %md
# MAGIC # IASX — políticas de mascaramento (Unity Catalog)
# MAGIC Cria ou atualiza as funções de column mask de `src/sql/access_policies.sql` no schema do target.
# MAGIC Precisa rodar antes da pipeline: as tabelas referenciam estas funções na própria definição.
# MAGIC Os grupos e seus membros são criados por `tools/setup_access_groups.py` (fora do bundle).

# COMMAND ----------

dbutils.widgets.text("fq_schema", "workspace.iasx_clinical")
fq_schema = dbutils.widgets.get("fq_schema")

# COMMAND ----------

import os
import re

if not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+", fq_schema):
    raise ValueError(f"fq_schema inválido: {fq_schema!r}")

# O notebook roda a partir de <bundle>/files/src/jobs; o SQL fica em <bundle>/files/src/sql.
path = os.path.join(os.getcwd(), "..", "sql", "access_policies.sql")
with open(path, encoding="utf-8") as fh:
    script = "\n".join(line for line in fh.read().splitlines() if not line.lstrip().startswith("--"))

# Cada comando termina com ";" no fim da linha (pode haver ";" dentro de textos).
statements = [s.strip() for s in re.split(r";\s*$", script, flags=re.M) if s.strip()]
for statement in statements:
    spark.sql(statement.replace("{fq_schema}", fq_schema))
print(f"{len(statements)} funções de máscara aplicadas em {fq_schema}")
