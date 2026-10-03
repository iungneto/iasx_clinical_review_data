-- Linha do tempo do caso: cada resultado extraído, ordenável por data, com a fonte original.
CREATE OR REFRESH MATERIALIZED VIEW gold_timeline (
  case_id STRING,
  exam_date DATE,
  timeline_position INT,
  test_code STRING,
  test_name_raw STRING,
  value_raw STRING,
  value DOUBLE,
  unit STRING,
  ref_low DOUBLE,
  ref_high DOUBLE,
  value_status STRING,
  document_id STRING,
  page_num INT,
  line_no INT,
  char_start INT,
  char_end INT,
  source_text STRING MASK ${iasx.policy_schema}.iasx_mask_document_text,
  date_source_text STRING MASK ${iasx.policy_schema}.iasx_mask_document_text,
  measurement_id STRING
)
COMMENT 'Linha do tempo por caso. Resultados sem data aparecem com timeline_position NULL (lacuna, nunca data inferida).'
CLUSTER BY (case_id)
TBLPROPERTIES ('iasx.layer' = 'gold')
AS SELECT
  case_id,
  exam_date,
  CASE WHEN exam_date IS NOT NULL
       THEN dense_rank() OVER (PARTITION BY case_id ORDER BY exam_date) END AS timeline_position,
  test_code,
  test_name_raw,
  value_raw,
  value,
  unit,
  ref_low,
  ref_high,
  value_status,
  document_id,
  page_num,
  line_no,
  char_start,
  char_end,
  source_text,
  date_source_text,
  measurement_id
FROM silver_lab_results;
