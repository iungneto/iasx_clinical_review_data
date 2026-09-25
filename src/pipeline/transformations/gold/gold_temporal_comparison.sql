-- Comparação temporal do mesmo exame entre datas consecutivas.
-- Datas com valores conflitantes ficam fora da série (são tratadas em gold_conflicts, sem escolher versão).
CREATE OR REFRESH MATERIALIZED VIEW gold_temporal_comparison
COMMENT 'Variação entre coletas consecutivas do mesmo exame, com evidência das duas medições.'
CLUSTER BY (case_id)
TBLPROPERTIES ('iasx.layer' = 'gold')
AS WITH per_date AS (
  SELECT
    case_id,
    test_code,
    exam_date,
    any_value(test_name_raw) AS test_name_raw,
    count(DISTINCT concat_ws('|', cast(value AS STRING), lower(coalesce(unit, '')))) AS n_versions,
    min(value) AS value,
    any_value(unit) AS unit,
    collect_list(named_struct(
      'document_id', document_id, 'page_num', page_num, 'line_no', line_no,
      'char_start', char_start, 'char_end', char_end, 'source_text', source_text)) AS evidence
  FROM silver_lab_results
  WHERE value_status = 'OK' AND exam_date IS NOT NULL
  GROUP BY case_id, test_code, exam_date
),
series AS (
  SELECT
    *,
    lag(exam_date) OVER w AS previous_date,
    lag(value) OVER w AS previous_value,
    lag(unit) OVER w AS previous_unit,
    lag(evidence) OVER w AS previous_evidence
  FROM per_date
  WHERE n_versions = 1
  WINDOW w AS (PARTITION BY case_id, test_code ORDER BY exam_date)
),
deltas AS (
  SELECT
    *,
    lower(coalesce(previous_unit, '')) = lower(coalesce(unit, '')) AS same_unit,
    CASE WHEN lower(coalesce(previous_unit, '')) = lower(coalesce(unit, ''))
         THEN round(value - previous_value, 4) END AS delta_abs,
    CASE WHEN lower(coalesce(previous_unit, '')) = lower(coalesce(unit, '')) AND previous_value <> 0
         THEN round(100 * (value - previous_value) / abs(previous_value), 2) END AS delta_pct
  FROM series
  WHERE previous_date IS NOT NULL
)
SELECT
  case_id,
  test_code,
  test_name_raw,
  previous_date,
  exam_date,
  datediff(exam_date, previous_date) AS days_between,
  previous_value,
  value,
  previous_unit,
  unit,
  delta_abs,
  delta_pct,
  CASE
    WHEN NOT same_unit THEN 'UNIT_CHANGED'
    WHEN delta_pct IS NULL THEN 'NOT_COMPARABLE'
    WHEN abs(delta_pct) < 5 THEN 'STABLE'
    WHEN delta_pct > 0 THEN 'UP'
    ELSE 'DOWN'
  END AS direction,
  concat(previous_evidence, evidence) AS evidence
FROM deltas;
