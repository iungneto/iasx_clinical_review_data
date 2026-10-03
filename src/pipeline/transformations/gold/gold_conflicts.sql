-- Conflitos: mesmo caso, mesmo exame, mesma data, valores/unidades diferentes em documentos/páginas distintos.
-- O IASX NÃO decide qual versão é a correta: todas as versões e fontes são apresentadas ao profissional.
CREATE OR REFRESH MATERIALIZED VIEW gold_conflicts (
  case_id STRING,
  test_code STRING,
  exam_date DATE,
  test_name_raw STRING,
  n_versions BIGINT,
  versions ARRAY<STRUCT<value_raw: STRING, unit: STRING, document_id: STRING, page_num: INT>>,
  evidence ARRAY<STRUCT<document_id: STRING, page_num: INT, line_no: INT, char_start: INT, char_end: INT, source_text: STRING>> MASK ${iasx.policy_schema}.iasx_mask_evidence
)
COMMENT 'Informações potencialmente conflitantes, com todas as versões e suas fontes.'
CLUSTER BY (case_id)
TBLPROPERTIES ('iasx.layer' = 'gold')
AS SELECT
  case_id,
  test_code,
  exam_date,
  any_value(test_name_raw) AS test_name_raw,
  count(DISTINCT concat_ws('|', cast(value AS STRING), lower(coalesce(unit, '')))) AS n_versions,
  collect_set(named_struct('value_raw', value_raw, 'unit', unit, 'document_id', document_id, 'page_num', page_num)) AS versions,
  collect_list(named_struct(
    'document_id', document_id, 'page_num', page_num, 'line_no', line_no,
    'char_start', char_start, 'char_end', char_end, 'source_text', source_text)) AS evidence
FROM silver_lab_results
WHERE value_status = 'OK' AND exam_date IS NOT NULL
GROUP BY case_id, test_code, exam_date
HAVING count(DISTINCT concat_ws('|', cast(value AS STRING), lower(coalesce(unit, '')))) > 1;
