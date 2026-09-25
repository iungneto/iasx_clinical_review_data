-- Métricas do MVP (seção 14 do documento) por revisão.
CREATE OR REFRESH MATERIALIZED VIEW gold_mvp_metrics
COMMENT 'Tempo manual vs. IASX, cobertura/precisão de fonte, conflitos, lacunas, taxas de ação, latências e verificação on-chain.'
TBLPROPERTIES ('iasx.layer' = 'gold')
AS WITH extraction AS (
  SELECT case_id,
         count(*) AS n_measurements,
         min(ingested_at) AS first_ingested_at,
         min(processed_at) AS first_extracted_at
  FROM silver_lab_results
  GROUP BY case_id
),
pages AS (
  SELECT case_id, count(*) AS n_pages FROM silver_document_pages GROUP BY case_id
),
queue AS (
  SELECT
    case_id,
    count_if(finding_type = 'OUT_OF_DOCUMENT_RANGE') AS n_out_of_range,
    count_if(finding_type = 'TEMPORAL_VARIATION') AS n_temporal_variation,
    count_if(finding_type = 'CONFLICT') AS n_conflicts,
    count_if(finding_type = 'GAP') AS n_gaps,
    count_if(reviewer_action = 'CONFIRM') AS n_confirmed,
    count_if(reviewer_action = 'CORRECT') AS n_corrected,
    count_if(reviewer_action = 'REJECT') AS n_rejected,
    count_if(reviewer_action IS NOT NULL) AS n_decided,
    max(jev_decided_at) AS last_jev_at
  FROM gold_review_queue
  GROUP BY case_id
),
bench AS (
  SELECT
    case_id,
    count_if(outcome IN ('MATCHED', 'MISSED')) AS n_expected,
    count_if(outcome = 'MATCHED') AS n_matched,
    count_if(outcome = 'EXTRA') AS n_extra,
    count_if(source_page_matches) AS n_source_ok,
    count_if(source_page_matches IS NOT NULL) AS n_source_checked
  FROM gold_benchmark
  GROUP BY case_id
)
SELECT
  s.case_id,
  s.review_id,
  s.scenario,
  s.review_state,
  s.onchain_status,
  c.manual_review_seconds_baseline,
  p.n_pages,
  e.n_measurements,
  q.n_out_of_range,
  q.n_temporal_variation,
  q.n_conflicts,
  q.n_gaps,
  q.n_confirmed,
  q.n_corrected,
  q.n_rejected,
  round(q.n_confirmed / nullif(q.n_decided, 0), 3) AS confirm_rate,
  round(q.n_corrected / nullif(q.n_decided, 0), 3) AS correct_rate,
  round(q.n_rejected / nullif(q.n_decided, 0), 3) AS reject_rate,
  round(b.n_matched / nullif(b.n_expected, 0), 3) AS finding_coverage,
  b.n_extra AS findings_not_in_gabarito,
  round(b.n_source_ok / nullif(b.n_source_checked, 0), 3) AS source_precision,
  timestampdiff(SECOND, e.first_ingested_at, e.first_extracted_at) AS first_response_latency_s,
  timestampdiff(SECOND, e.first_ingested_at, s.signoff_at) AS iasx_review_seconds,
  timestampdiff(SECOND, s.signoff_at, s.submitted_at) AS review_to_attestation_s,
  timestampdiff(SECOND, e.first_ingested_at, s.verified_at) AS total_flow_s,
  s.onchain_status = 'VERIFIED' AS attestation_verified
FROM gold_review_status s
LEFT JOIN silver_cases c ON c.case_id = s.case_id
LEFT JOIN pages p ON p.case_id = s.case_id
LEFT JOIN extraction e ON e.case_id = s.case_id
LEFT JOIN queue q ON q.case_id = s.case_id
LEFT JOIN bench b ON b.case_id = s.case_id;
