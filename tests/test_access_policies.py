"""Column masks do Unity Catalog (src/sql/access_policies.sql) declarados nas tabelas que guardam conteúdo do documento.

A verificação em execução (máscara anexada e valor oculto para quem não é do grupo) está em
docs/regulatory/risk_and_compliance.md (R2); aqui garantimos que nenhuma tabela nova esqueça a máscara.
"""

import re

import pytest

from conftest import ROOT

TRANSFORMATIONS = ROOT / "src/pipeline/transformations"
POLICIES = (ROOT / "src/sql/access_policies.sql").read_text(encoding="utf-8")

# Colunas com conteúdo do documento → função de máscara que precisa protegê-las.
SENSITIVE = {
    "content": "iasx_mask_raw_document",
    "page_text": "iasx_mask_document_text",
    "source_text": "iasx_mask_document_text",
    "date_source_text": "iasx_mask_document_text",
    "evidence": "iasx_mask_evidence",
}
EXPECTED = {
    "bronze/bronze_documents.py": ["content"],
    "silver/silver_document_pages.py": ["page_text"],
    "silver/silver_lab_results.py": ["source_text", "date_source_text"],
    "gold/gold_timeline.sql": ["source_text", "date_source_text"],
    "gold/gold_temporal_comparison.sql": ["evidence"],
    "gold/gold_conflicts.sql": ["evidence"],
    "gold/gold_gaps.sql": ["evidence"],
    "gold/gold_findings.sql": ["evidence"],
    "gold/gold_review_queue.sql": ["evidence"],
}
# Declaração de coluna num schema explícito: "<nome> <TIPO>" no início da linha (SQL) ou dentro da string (Python).
DECLARATION = re.compile(r"(?:^\s*|[\"(,]\s*)(\w+) (BINARY|STRING|ARRAY<STRUCT<[^>]*>>)([^,\"\n]*)", re.M)


def _declared(path):
    return {name: (typ, rest) for name, typ, rest in DECLARATION.findall(path.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("relative, columns", EXPECTED.items())
def test_document_content_columns_are_masked(relative, columns):
    declared = _declared(TRANSFORMATIONS / relative)
    for column in columns:
        assert column in declared, f"{relative}: {column} sem schema explícito (a máscara exige)"
        assert re.search(rf"MASK (?:\$\{{iasx\.policy_schema\}}|\{{POLICY\}})\.{SENSITIVE[column]}\b", declared[column][1]), (
            f"{relative}: {column} sem MASK {SENSITIVE[column]}"
        )


def test_no_table_declares_document_content_without_mask():
    """Qualquer tabela nova que declare uma coluna sensível precisa da máscara."""
    for path in TRANSFORMATIONS.rglob("*"):
        if path.suffix not in (".py", ".sql"):
            continue
        for name, (_, rest) in _declared(path).items():
            if name in SENSITIVE:
                assert "MASK" in rest, f"{path.relative_to(ROOT)}: {name}"


def test_every_referenced_mask_function_is_defined():
    for function in set(SENSITIVE.values()):
        assert f"CREATE OR REPLACE FUNCTION {{fq_schema}}.{function}(" in POLICIES, function


def test_masks_check_the_least_privilege_groups():
    raw = POLICIES.split("iasx_mask_document_text(")[0]
    assert "is_member('iasx_raw_document_readers')" in raw
    assert POLICIES.count("is_member('iasx_clinical_text_readers')") == 2


def test_evidence_mask_keeps_source_pointers():
    """§14: mesmo mascarada, a evidência continua apontando documento, página e offsets."""
    body = POLICIES.split("iasx_mask_evidence(")[1]
    for field in ("document_id", "page_num", "line_no", "char_start", "char_end"):
        assert f"'{field}', e.{field}" in body


def test_policies_run_before_the_pipeline():
    jobs = (ROOT / "resources/iasx_orchestration.job.yml").read_text(encoding="utf-8")
    pipeline = (ROOT / "resources/iasx_clinical.pipeline.yml").read_text(encoding="utf-8")
    assert "apply_access_policies.py" in jobs.split("iasx_review_cycle:")[0]  # no iasx_bootstrap
    assert "iasx.policy_schema:" in pipeline
