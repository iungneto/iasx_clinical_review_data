"""Exporta as tabelas que a API do JEV lê para tools/mock_db/tables/*.json (base mockada dos testes).

Uso (depois de um iasx_review_cycle no workspace):
    uv run python tools/mock_db/export_from_workspace.py --profile iasx --schema workspace.dev_<usuário>_iasx_clinical

Só exporta casos sintéticos registrados em data/synthetic/cases.json (casos de teste avulsos ficam de fora) e só
tabelas silver/gold, onde os identificadores já estão mascarados. A bronze (PDF bruto) nunca é exportada.
"""

import argparse
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "tables"

# Mesmo conjunto de SELECT concedido ao app em resources/iasx_jev_api.app.yml.
TABLES = (
    "gold_review_status",
    "gold_review_queue",
    "gold_findings",
    "silver_document_pages",
    "gold_timeline",
    "gold_temporal_comparison",
    "gold_attestation_payload",
    "gold_mvp_metrics",
    "gold_benchmark",
)


def run(w: WorkspaceClient, warehouse_id: str, statement: str) -> list:
    resp = w.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=statement, wait_timeout="50s")
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{resp.status.state}: {resp.status.error and resp.status.error.message}\n{statement}")
    rows = (resp.result and resp.result.data_array) or []
    return [json.loads(r[0]) for r in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--schema", required=True, help="catálogo.schema da pipeline")
    parser.add_argument("--warehouse-id", help="padrão: primeiro SQL Warehouse do workspace")
    args = parser.parse_args()

    w = WorkspaceClient(profile=args.profile)
    warehouse_id = args.warehouse_id or next(iter(w.warehouses.list())).id
    lines = (ROOT / "data/synthetic/cases.json").read_text(encoding="utf-8").splitlines()
    in_cases = ", ".join(f"'{json.loads(line)['case_id']}'" for line in lines if line.strip())

    # Column masks (src/sql/access_policies.sql): fora do grupo, o texto viria como [restrito] e a base ficaria inútil.
    [allowed] = run(w, warehouse_id, "SELECT to_json(named_struct('ok', is_member('iasx_clinical_text_readers')))")
    if not allowed["ok"]:
        raise SystemExit("o usuário do perfil precisa estar em iasx_clinical_text_readers (tools/setup_access_groups.py)")

    OUT.mkdir(exist_ok=True)
    for table in TABLES:
        rows = run(w, warehouse_id, (
            # ignoreNullFields=false: a base mockada precisa ter as mesmas colunas da tabela, inclusive nulas.
            f"SELECT to_json(struct(*), map('ignoreNullFields', 'false')) FROM {args.schema}.{table} "
            f"WHERE case_id IN ({in_cases})"
        ))
        rows.sort(key=lambda r: json.dumps(r, sort_keys=True))  # diff estável entre exportações
        (OUT / f"{table}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{table}: {len(rows)} linhas")


if __name__ == "__main__":
    main()
