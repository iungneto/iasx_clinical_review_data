-- Linha do tempo do caso: cada resultado extraído, ordenável por data, com a fonte original.
CREATE OR REFRESH MATERIALIZED VIEW gold_timeline
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
