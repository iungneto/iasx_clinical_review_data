-- Fila de revisão consumida pelo portal: achado + decisão do Jev + regras de segurança + ação do profissional.
-- Regras de segurança (sobrepõem o Jev, nunca o contrário):
--   * conflito e lacuna SEMPRE exigem revisão humana;
--   * Jev ausente ou com resposta fora do schema → revisão humana com prioridade alta;
--   * informação marcada como pouco clara pelo Jev → revisão humana;
--   * conflito nunca fica com prioridade baixa.
CREATE OR REFRESH MATERIALIZED VIEW gold_review_queue
COMMENT 'Achados priorizados para o portal, com o resultado estruturado do Jev e as sobreposições de segurança.'
CLUSTER BY (case_id)
TBLPROPERTIES ('iasx.layer' = 'gold')
AS WITH joined AS (
  SELECT
    f.*,
    j.finding_id IS NOT NULL AS has_jev,
    coalesce(j.jev_response_valid, false) AS jev_valid,
    j.needs_review AS jev_needs_review,
    j.priority AS jev_priority,
    j.is_clear AS jev_is_clear,
    j.jev_model,
    j.decided_at AS jev_decided_at,
    d.action AS reviewer_action,
    d.corrected_value,
    d.corrected_unit,
    d.reviewer_tech_id,
    d.decided_at AS reviewer_decided_at
  FROM gold_findings f
  LEFT JOIN silver_jev_decisions j ON j.finding_id = f.finding_id
  LEFT JOIN silver_review_decisions d
    ON d.review_id = f.review_id AND d.finding_id = f.finding_id AND d.scope = 'FINDING'
),
safety AS (
  SELECT
    *,
    CASE WHEN NOT has_jev THEN 'PENDING' WHEN NOT jev_valid THEN 'INVALID' ELSE 'OK' END AS jev_status,
    coalesce(
      finding_type IN ('CONFLICT', 'GAP') OR NOT has_jev OR NOT jev_valid OR jev_needs_review OR NOT jev_is_clear,
      true) AS needs_review_final,
    CASE
      WHEN NOT has_jev OR NOT jev_valid THEN 'alta'
      WHEN finding_type = 'CONFLICT' AND jev_priority = 'baixa' THEN 'media'
      ELSE jev_priority
    END AS priority_final,
    filter(array(
      CASE WHEN finding_type = 'CONFLICT' THEN 'FORCED_REVIEW_CONFLICT' END,
      CASE WHEN finding_type = 'GAP' THEN 'FORCED_REVIEW_GAP' END,
      CASE WHEN NOT has_jev THEN 'JEV_PENDING' END,
      CASE WHEN has_jev AND NOT jev_valid THEN 'JEV_INVALID_SCHEMA' END,
      CASE WHEN jev_valid AND NOT jev_is_clear THEN 'LOW_CLARITY' END,
      CASE WHEN jev_valid AND NOT jev_needs_review AND finding_type IN ('CONFLICT', 'GAP') THEN 'JEV_OVERRIDDEN' END
    ), x -> x IS NOT NULL) AS safety_flags
  FROM joined
)
SELECT
  *,
  CASE
    WHEN reviewer_action = 'CONFIRM' THEN 'CONFIRMED'
    WHEN reviewer_action = 'CORRECT' THEN 'CORRECTED'
    WHEN reviewer_action = 'REJECT' THEN 'REJECTED'
    WHEN jev_status = 'PENDING' THEN 'AWAITING_JEV'
    WHEN needs_review_final THEN 'HUMAN_REVIEW_REQUIRED'
    ELSE 'AI_REVIEW_READY'
  END AS finding_state,
  CASE priority_final WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END AS priority_rank
FROM safety;
