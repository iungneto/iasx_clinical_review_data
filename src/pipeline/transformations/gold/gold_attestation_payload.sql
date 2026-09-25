-- Prova de integridade da revisão: é EXATAMENTE isto que o backend envia ao programa Solana.
-- Só hashes e metadados técnicos. Nenhum dado clínico sai desta tabela para a cadeia.
--   input_hash    = sha256 dos hashes (ordenados) dos PDFs do caso
--   analysis_hash = sha256 dos achados + decisões do Jev + sobreposições de segurança (canonical JSON, ordenado)
--   reviewed_hash = sha256 de analysis_hash + ações do profissional + signoff
CREATE OR REFRESH MATERIALIZED VIEW gold_attestation_payload (
  CONSTRAINT sha256_hashes EXPECT (
    input_hash RLIKE '^[0-9a-f]{64}$' AND analysis_hash RLIKE '^[0-9a-f]{64}$' AND reviewed_hash RLIKE '^[0-9a-f]{64}$'
  ) ON VIOLATION FAIL UPDATE
)
COMMENT 'Payload técnico da atestação on-chain por revisão (hashes, versões, status alvo, revisor técnico).'
TBLPROPERTIES ('iasx.layer' = 'gold', 'iasx.onchain_safe' = 'true')
AS WITH docs AS (
  SELECT case_id,
         sha2(array_join(array_sort(collect_set(input_hash)), ','), 256) AS input_hash,
         count(*) AS n_documents
  FROM bronze_documents
  GROUP BY case_id
),
analysis AS (
  SELECT
    case_id,
    sha2(array_join(array_sort(collect_list(to_json(named_struct(
      'finding_id', finding_id, 'type', finding_type, 'subtype', finding_subtype,
      'jev_needs_review', jev_needs_review, 'jev_priority', jev_priority, 'jev_is_clear', jev_is_clear,
      'needs_review_final', needs_review_final, 'priority_final', priority_final)))), '\n'), 256) AS analysis_hash,
    array_join(array_sort(collect_list(CASE WHEN reviewer_action IS NOT NULL THEN to_json(named_struct(
      'finding_id', finding_id, 'action', reviewer_action, 'corrected_value', corrected_value,
      'corrected_unit', corrected_unit, 'reviewer', reviewer_tech_id)) END)), '\n') AS decisions_canonical,
    count(*) AS n_findings,
    count_if(jev_status = 'PENDING') AS n_jev_pending,
    count_if(needs_review_final AND reviewer_action IS NULL) AS n_pending_human,
    count_if(reviewer_action = 'CORRECT') AS n_corrected
  FROM gold_review_queue
  GROUP BY case_id
),
signoff AS (
  SELECT review_id, reviewer_tech_id, decided_at
  FROM silver_review_decisions
  WHERE scope = 'REVIEW' AND action = 'SIGNOFF'
),
assembled AS (
  SELECT
    c.review_id,
    c.case_id,
    d.input_hash,
    coalesce(a.analysis_hash, sha2('', 256)) AS analysis_hash,
    coalesce(a.decisions_canonical, '') AS decisions_canonical,
    coalesce(d.n_documents, 0) AS n_documents,
    coalesce(a.n_findings, 0) AS n_findings,
    coalesce(a.n_jev_pending, 0) AS n_jev_pending,
    coalesce(a.n_pending_human, 0) AS n_pending_human,
    coalesce(a.n_corrected, 0) AS n_corrected,
    s.reviewer_tech_id,
    s.decided_at AS signoff_at
  FROM silver_cases c
  JOIN docs d ON d.case_id = c.case_id
  LEFT JOIN analysis a ON a.case_id = c.case_id
  LEFT JOIN signoff s ON s.review_id = c.review_id
)
SELECT
  review_id,
  case_id,
  input_hash,
  analysis_hash,
  sha2(concat_ws('|', analysis_hash, decisions_canonical,
                 coalesce(reviewer_tech_id, ''),
                 -- epoch em microssegundos: independe do fuso horário da sessão
                 coalesce(cast(unix_micros(signoff_at) AS STRING), '')), 256) AS reviewed_hash,
  '${iasx.workflow_version}' AS workflow_version,
  '${iasx.model_version}' AS model_version,
  CASE WHEN n_corrected > 0 THEN 'CORRECTED' ELSE 'CONFIRMED' END AS target_status,
  reviewer_tech_id,
  signoff_at,
  n_documents,
  n_findings,
  n_jev_pending,
  n_pending_human,
  (n_jev_pending = 0 AND n_pending_human = 0 AND signoff_at IS NOT NULL) AS ready_for_attestation
FROM assembled;
