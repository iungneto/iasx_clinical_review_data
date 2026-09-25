-- Achados consolidados que vão para o Jev e para a revisão humana.
-- finding_id é determinístico (tipo + chave + fontes): o mesmo PDF gera sempre os mesmos IDs,
-- o que torna o hash da análise reprodutível para a atestação on-chain.
CREATE OR REFRESH MATERIALIZED VIEW gold_findings (
  CONSTRAINT every_finding_has_source EXPECT (size(evidence) > 0 AND evidence[0].document_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT known_finding_type EXPECT (finding_type IN ('OUT_OF_DOCUMENT_RANGE', 'TEMPORAL_VARIATION', 'CONFLICT', 'GAP')) ON VIOLATION FAIL UPDATE,
  CONSTRAINT registered_case EXPECT (review_id IS NOT NULL)
)
COMMENT 'Achados (alteração vs. faixa do documento, variação temporal, conflito, lacuna) com fonte obrigatória. Não contém diagnóstico.'
CLUSTER BY (case_id)
TBLPROPERTIES ('iasx.layer' = 'gold')
AS WITH out_of_range AS (
  SELECT
    'OUT_OF_DOCUMENT_RANGE' AS finding_type,
    CASE WHEN value < ref_low THEN 'BELOW_DOCUMENT_RANGE' ELSE 'ABOVE_DOCUMENT_RANGE' END AS finding_subtype,
    case_id, test_code, exam_date,
    format_string('%s = %s %s fora da faixa de referência informada no documento (%s–%s).',
                  test_name_raw, value_raw, coalesce(unit, ''), ref_low, ref_high) AS summary,
    array(named_struct(
      'document_id', document_id, 'page_num', page_num, 'line_no', line_no,
      'char_start', char_start, 'char_end', char_end, 'source_text', source_text)) AS evidence
  FROM silver_lab_results
  WHERE value_status = 'OK' AND ref_low IS NOT NULL AND ref_high IS NOT NULL
    AND (value < ref_low OR value > ref_high)
),
variation AS (
  SELECT
    'TEMPORAL_VARIATION' AS finding_type,
    direction AS finding_subtype,
    case_id, test_code, exam_date,
    CASE WHEN direction = 'UNIT_CHANGED'
         THEN format_string('%s mudou de unidade entre %s (%s) e %s (%s); comparação direta não realizada.',
                            test_name_raw, previous_date, previous_unit, exam_date, unit)
         ELSE format_string('%s variou %s%% entre %s (%s %s) e %s (%s %s).',
                            test_name_raw, delta_pct, previous_date, previous_value, coalesce(previous_unit, ''),
                            exam_date, value, coalesce(unit, ''))
    END AS summary,
    evidence
  FROM gold_temporal_comparison
  WHERE direction = 'UNIT_CHANGED'
     OR abs(delta_pct) >= CAST('${iasx.temporal_variation_pct}' AS DOUBLE)
),
conflicts AS (
  SELECT
    'CONFLICT' AS finding_type,
    'DIVERGENT_VALUES' AS finding_subtype,
    case_id, test_code, exam_date,
    format_string('%s em %s aparece com %d versões diferentes: %s. O IASX não escolhe a versão correta.',
                  test_name_raw, exam_date, n_versions,
                  array_join(transform(versions, v -> concat(v.value_raw, ' ', coalesce(v.unit, ''),
                                                             ' (', v.document_id, ' p.', v.page_num, ')')), '; ')) AS summary,
    evidence
  FROM gold_conflicts
),
gaps AS (
  SELECT 'GAP' AS finding_type, gap_type AS finding_subtype, case_id, test_code, exam_date,
         description AS summary, evidence
  FROM gold_gaps
),
all_findings AS (
  SELECT * FROM out_of_range
  UNION ALL SELECT * FROM variation
  UNION ALL SELECT * FROM conflicts
  UNION ALL SELECT * FROM gaps
)
SELECT
  sha2(concat_ws('|',
    f.finding_type, f.finding_subtype, f.case_id, coalesce(f.test_code, ''), coalesce(cast(f.exam_date AS STRING), ''),
    array_join(array_sort(transform(f.evidence, e -> concat_ws(':', e.document_id, e.page_num, e.char_start))), ',')
  ), 256) AS finding_id,
  c.review_id,
  f.*
FROM all_findings f
LEFT JOIN silver_cases c USING (case_id);
