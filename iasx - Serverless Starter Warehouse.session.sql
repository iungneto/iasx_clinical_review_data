-- Teste de conexão: confirma catálogo, schema e usuário da sessão
SELECT current_catalog(), current_schema(), current_user();

-- Status de cada caso de revisão (gold)
SELECT
  case_id,
  scenario,
  review_state,
  onchain_status,
  n_documents,
  n_findings,
  n_pending_human,
  ready_for_attestation
FROM workspace.dev_iungneto_iasx_clinical.gold_review_status
ORDER BY created_at DESC
LIMIT 10;
