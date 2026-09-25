-- Máquina de estados da revisão. Regra do produto: a revisão só é FINALIZADA (ATTESTED)
-- quando existe atestação on-chain verificada cujos hashes batem com o payload recalculado agora.
-- Se qualquer dado mudar depois da atestação, os hashes divergem e o caso volta a não finalizado.
CREATE OR REFRESH MATERIALIZED VIEW gold_review_status
COMMENT 'Estado atual de cada revisão: CREATED → PROCESSING → AI_REVIEW_READY / HUMAN_REVIEW_REQUIRED → CONFIRMED / CORRECTED → ATTESTED.'
TBLPROPERTIES ('iasx.layer' = 'gold')
AS WITH onchain AS (
  SELECT
    c.case_id,
    c.review_id,
    c.scenario,
    c.created_at,
    p.input_hash,
    p.analysis_hash,
    p.reviewed_hash,
    p.target_status,
    p.signoff_at,
    p.ready_for_attestation,
    coalesce(p.n_documents, 0) AS n_documents,
    coalesce(p.n_findings, 0) AS n_findings,
    coalesce(p.n_jev_pending, 0) AS n_jev_pending,
    coalesce(p.n_pending_human, 0) AS n_pending_human,
    a.tx_signature,
    a.pda_address,
    a.cluster,
    a.submitted_at,
    v.verified_at,
    v.slot,
    v.error AS verification_error,
    CASE
      WHEN a.review_id IS NULL THEN 'NOT_SUBMITTED'
      WHEN v.review_id IS NULL OR v.tx_signature <> a.tx_signature THEN 'SUBMITTED'
      WHEN v.error IS NOT NULL OR NOT coalesce(v.account_found, false) OR NOT coalesce(v.tx_confirmed, false)
        THEN 'VERIFICATION_FAILED'
      WHEN v.onchain_status = 'ATTESTED'
       AND v.onchain_input_hash = p.input_hash
       AND v.onchain_analysis_hash = p.analysis_hash
       AND v.onchain_reviewed_hash = p.reviewed_hash
        THEN 'VERIFIED'
      ELSE 'HASH_MISMATCH'
    END AS onchain_status
  FROM silver_cases c
  LEFT JOIN gold_attestation_payload p ON p.case_id = c.case_id
  LEFT JOIN silver_attestations a ON a.review_id = c.review_id
  LEFT JOIN silver_attestation_verifications v ON v.review_id = c.review_id
)
SELECT
  *,
  CASE
    WHEN onchain_status = 'VERIFIED' THEN 'ATTESTED'
    WHEN n_documents = 0 THEN 'CREATED'
    WHEN n_jev_pending > 0 THEN 'PROCESSING'
    WHEN n_pending_human > 0 THEN 'HUMAN_REVIEW_REQUIRED'
    WHEN signoff_at IS NULL THEN 'AI_REVIEW_READY'
    ELSE target_status
  END AS review_state,
  onchain_status = 'VERIFIED' AS is_finalized
FROM onchain;
