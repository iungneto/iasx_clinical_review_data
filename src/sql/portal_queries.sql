-- Consultas que o backend do portal executa no SQL Warehouse (Statement Execution API, parâmetros nomeados).
-- A chave/token do Databricks fica só no backend. O frontend nunca fala direto com o Databricks.

-- 1) Lista de casos com estado da revisão e status on-chain
SELECT case_id, review_id, scenario, review_state, onchain_status, is_finalized,
       n_documents, n_findings, n_pending_human, tx_signature, submitted_at, verified_at
FROM workspace.iasx_clinical.gold_review_status
ORDER BY created_at DESC;

-- 2) Fila de revisão de um caso (prioridade de workflow, estado de cada achado, flags de segurança)
SELECT finding_id, finding_type, finding_subtype, test_code, exam_date, summary,
       jev_status, jev_needs_review, jev_priority, jev_is_clear,
       needs_review_final, priority_final, safety_flags, finding_state,
       reviewer_action, corrected_value, corrected_unit
FROM workspace.iasx_clinical.gold_review_queue
WHERE case_id = :case_id
ORDER BY priority_rank, finding_type, exam_date;

-- 3) Evidência de origem de um achado ("abrir fonte": documento, página, linha, offsets, trecho)
SELECT e.document_id, e.page_num, e.line_no, e.char_start, e.char_end, e.source_text
FROM workspace.iasx_clinical.gold_findings
LATERAL VIEW explode(evidence) t AS e
WHERE finding_id = :finding_id;

-- 3b) Página completa (texto mascarado) para destacar o trecho no visualizador
SELECT page_text
FROM workspace.iasx_clinical.silver_document_pages
WHERE document_id = :document_id AND page_num = :page_num;

-- 4) Linha do tempo do caso
SELECT exam_date, timeline_position, test_code, test_name_raw, value_raw, unit, value_status,
       document_id, page_num, source_text
FROM workspace.iasx_clinical.gold_timeline
WHERE case_id = :case_id
ORDER BY exam_date NULLS LAST, test_code;

-- 5) Comparação temporal
SELECT test_code, test_name_raw, previous_date, exam_date, previous_value, value, unit,
       delta_abs, delta_pct, direction
FROM workspace.iasx_clinical.gold_temporal_comparison
WHERE case_id = :case_id
ORDER BY test_code, exam_date;

-- 6) Payload da atestação (SOMENTE estes campos vão para o programa Solana)
SELECT review_id, input_hash, analysis_hash, reviewed_hash, workflow_version, model_version,
       target_status, reviewer_tech_id, signoff_at, ready_for_attestation
FROM workspace.iasx_clinical.gold_attestation_payload
WHERE review_id = :review_id;

-- 7) Métricas do MVP e benchmark
SELECT * FROM workspace.iasx_clinical.gold_mvp_metrics ORDER BY case_id;
SELECT outcome, count(*) FROM workspace.iasx_clinical.gold_benchmark GROUP BY outcome;
