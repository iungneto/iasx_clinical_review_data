-- Benchmark contra o gabarito dos casos sintéticos: cobertura de achados e precisão da fonte.
CREATE OR REFRESH MATERIALIZED VIEW gold_benchmark
COMMENT 'Comparação achado a achado com o gabarito: MATCHED / MISSED / EXTRA e se a página de origem confere.'
TBLPROPERTIES ('iasx.layer' = 'gold')
AS WITH found AS (
  -- Agrupa por chave do gabarito para que achados repetidos em documentos diferentes contem uma vez.
  SELECT case_id, finding_type, finding_subtype, test_code, exam_date,
         collect_list(finding_id) AS finding_ids,
         flatten(collect_list(transform(evidence, e -> e.page_num))) AS pages
  FROM gold_findings
  GROUP BY case_id, finding_type, finding_subtype, test_code, exam_date
)
SELECT
  coalesce(g.case_id, f.case_id) AS case_id,
  coalesce(g.finding_type, f.finding_type) AS finding_type,
  coalesce(g.finding_subtype, f.finding_subtype) AS finding_subtype,
  coalesce(g.test_code, f.test_code) AS test_code,
  coalesce(g.exam_date, f.exam_date) AS exam_date,
  f.finding_ids,
  g.expected_page,
  CASE
    WHEN g.case_id IS NOT NULL AND f.finding_ids IS NOT NULL THEN 'MATCHED'
    WHEN g.case_id IS NOT NULL THEN 'MISSED'
    ELSE 'EXTRA'
  END AS outcome,
  CASE WHEN g.expected_page IS NOT NULL AND f.finding_ids IS NOT NULL
       THEN array_contains(f.pages, g.expected_page) END AS source_page_matches
FROM bronze_gabarito g
FULL OUTER JOIN found f
  ON  g.case_id = f.case_id
  AND g.finding_type = f.finding_type
  AND g.finding_subtype = f.finding_subtype
  AND g.test_code <=> f.test_code
  AND g.exam_date <=> f.exam_date
-- Casos sem gabarito não entram no benchmark.
WHERE coalesce(g.case_id, f.case_id) IN (SELECT DISTINCT case_id FROM bronze_gabarito);
