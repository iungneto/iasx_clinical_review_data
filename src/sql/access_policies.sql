-- Políticas de mascaramento do Unity Catalog (column masks). Aplicadas pelo job iasx_bootstrap
-- (src/jobs/apply_access_policies.py) antes da pipeline, que referencia as funções nas definições das tabelas.
-- {fq_schema} é substituído pelo catálogo.schema do target.
--
-- Camadas de proteção (docs/regulatory/risk_and_compliance.md, R1/R2):
--   1. mascaramento de identificadores na transformação (clinical_rules.mask_identifiers), antes da silver;
--   2. estas máscaras: mesmo com SELECT na tabela, só os grupos abaixo veem o conteúdo do documento;
--   3. grants mínimos (o app não tem SELECT na bronze).
-- Grupos (tools/setup_access_groups.py):
--   iasx_raw_document_readers  → PDF bruto da bronze (só a identidade que roda a pipeline);
--   iasx_clinical_text_readers → texto do documento em silver/gold (pipeline e service principal do app).
-- Os grupos deste workspace são locais, por isso is_member() e não is_account_group_member().
-- A máscara vale para todos, inclusive admins e o dono da tabela.

CREATE OR REPLACE FUNCTION {fq_schema}.iasx_mask_raw_document(content BINARY)
RETURNS BINARY
COMMENT 'Column mask: PDF bruto só para iasx_raw_document_readers (demais veem NULL).'
RETURN CASE WHEN is_member('iasx_raw_document_readers') THEN content END;

CREATE OR REPLACE FUNCTION {fq_schema}.iasx_mask_document_text(text STRING)
RETURNS STRING
COMMENT 'Column mask: texto do documento só para iasx_clinical_text_readers (demais veem [restrito]).'
RETURN CASE WHEN text IS NULL OR text = '' OR is_member('iasx_clinical_text_readers') THEN text ELSE '[restrito]' END;

-- Evidência: documento, página, linha e offsets continuam visíveis (rastreabilidade); só o trecho é ocultado.
CREATE OR REPLACE FUNCTION {fq_schema}.iasx_mask_evidence(
  evidence ARRAY<STRUCT<document_id: STRING, page_num: INT, line_no: INT, char_start: INT, char_end: INT, source_text: STRING>>
)
RETURNS ARRAY<STRUCT<document_id: STRING, page_num: INT, line_no: INT, char_start: INT, char_end: INT, source_text: STRING>>
COMMENT 'Column mask: trecho de origem só para iasx_clinical_text_readers (ponteiros da fonte ficam visíveis).'
RETURN CASE
  WHEN is_member('iasx_clinical_text_readers') THEN evidence
  ELSE transform(evidence, e -> named_struct(
    'document_id', e.document_id, 'page_num', e.page_num, 'line_no', e.line_no,
    'char_start', e.char_start, 'char_end', e.char_end,
    'source_text', CASE WHEN e.source_text IS NULL OR e.source_text = '' THEN e.source_text ELSE '[restrito]' END))
END;
