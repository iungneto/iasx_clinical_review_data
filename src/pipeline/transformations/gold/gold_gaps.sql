-- Lacunas: ausência ou ilegibilidade. Nada é preenchido; cada lacuna aponta para onde foi detectada.
CREATE OR REFRESH MATERIALIZED VIEW gold_gaps (
  case_id STRING,
  gap_type STRING,
  test_code STRING,
  exam_date DATE,
  document_id STRING,
  page_num INT,
  description STRING,
  evidence ARRAY<STRUCT<document_id: STRING, page_num: INT, line_no: INT, char_start: INT, char_end: INT, source_text: STRING>> MASK ${iasx.policy_schema}.iasx_mask_evidence
)
COMMENT 'Lacunas de informação (data, valor ilegível/ausente/ambíguo, unidade, faixa de referência, página sem texto, documento ilegível ou não sintético).'
CLUSTER BY (case_id)
TBLPROPERTIES ('iasx.layer' = 'gold')
AS WITH measurement_gaps AS (
  SELECT
    case_id, document_id, page_num, test_code, exam_date, test_name_raw,
    named_struct(
      'document_id', document_id, 'page_num', page_num, 'line_no', line_no,
      'char_start', char_start, 'char_end', char_end, 'source_text', source_text) AS ev,
    filter(array(
      CASE WHEN exam_date IS NULL THEN 'MISSING_DATE' END,
      CASE WHEN value_status = 'ILLEGIBLE' THEN 'ILLEGIBLE_VALUE' END,
      CASE WHEN value_status = 'MISSING' THEN 'MISSING_VALUE' END,
      CASE WHEN value_status = 'AMBIGUOUS' THEN 'AMBIGUOUS_VALUE' END,
      CASE WHEN value_status = 'OK' AND unit IS NULL THEN 'MISSING_UNIT' END,
      CASE WHEN value_status = 'OK' AND ref_kind IS NULL AND (ref_low IS NULL OR ref_high IS NULL) THEN 'MISSING_REFERENCE_RANGE' END,
      CASE WHEN NOT test_known THEN 'UNMAPPED_TEST' END
    ), x -> x IS NOT NULL) AS gap_types
  FROM silver_lab_results
)
SELECT
  case_id, gap_type, test_code, exam_date, document_id, page_num,
  CASE gap_type
    WHEN 'MISSING_DATE' THEN concat('Resultado de ', test_name_raw, ' sem data de coleta identificável.')
    WHEN 'ILLEGIBLE_VALUE' THEN concat('Valor de ', test_name_raw, ' marcado como ilegível no documento.')
    WHEN 'MISSING_VALUE' THEN concat('Valor de ', test_name_raw, ' ausente/não informado no documento.')
    WHEN 'AMBIGUOUS_VALUE' THEN concat('Valor de ', test_name_raw, ' não é um número simples no documento; o IASX não escolhe um valor.')
    WHEN 'MISSING_UNIT' THEN concat('Valor de ', test_name_raw, ' sem unidade no documento.')
    WHEN 'MISSING_REFERENCE_RANGE' THEN concat('Documento não informa faixa de referência para ', test_name_raw, '.')
    WHEN 'UNMAPPED_TEST' THEN concat('Exame "', test_name_raw, '" não reconhecido pelo dicionário do IASX.')
  END AS description,
  array(ev) AS evidence
FROM measurement_gaps
LATERAL VIEW explode(gap_types) t AS gap_type

UNION ALL

SELECT
  case_id,
  gap_type,
  CAST(NULL AS STRING) AS test_code,
  CAST(NULL AS DATE) AS exam_date,
  document_id,
  page_num,
  CASE gap_type
    WHEN 'DOCUMENT_UNREADABLE' THEN 'Documento não pôde ser lido como PDF textual (OCR fora do escopo do MVP).'
    WHEN 'NOT_SYNTHETIC_DOCUMENT' THEN 'Documento sem declaração de dado sintético: conteúdo não processado (o MVP aceita somente dados sintéticos).'
    ELSE 'Página sem texto extraível (possível imagem/digitalização; OCR fora do escopo do MVP).'
  END AS description,
  array(named_struct(
    'document_id', document_id, 'page_num', page_num, 'line_no', CAST(NULL AS INT),
    'char_start', CAST(NULL AS INT), 'char_end', CAST(NULL AS INT), 'source_text', '')) AS evidence
FROM (
  SELECT *,
         CASE
           WHEN parse_error IS NOT NULL THEN 'DOCUMENT_UNREADABLE'
           WHEN NOT synthetic_declared THEN 'NOT_SYNTHETIC_DOCUMENT'
           WHEN NOT is_textual THEN 'NON_TEXTUAL_PAGE'
         END AS gap_type
  FROM silver_document_pages
)
-- Lacunas de documento inteiro aparecem uma vez (página 1); página sem texto, uma por página.
WHERE gap_type = 'NON_TEXTUAL_PAGE' OR (gap_type IS NOT NULL AND coalesce(page_num, 1) = 1);
