# Contratos da landing zone

Volume: `/Volumes/<catalog>/<schema>/landing`. Arquivos JSON são *JSON lines* (um objeto por linha).
Cada arquivo novo é ingerido uma única vez pelo Auto Loader — **nunca sobrescreva um arquivo; grave um novo**.
Timestamps em ISO-8601 UTC.

## `pdfs/<case_id>/<document_id>.pdf` — portal

PDF textual sintético. `document_id` deve ser único no workspace (sugestão: prefixo do caso).

## `cases/*.json` — portal

| Campo | Tipo | Observação |
|---|---|---|
| `case_id` | string | ID técnico do caso |
| `review_id` | string | ID técnico da revisão (seed da PDA on-chain) |
| `scenario` | string | rótulo livre (ex.: `C_principal`) |
| `created_at` | timestamp | ordena atualizações do mesmo caso |
| `manual_review_seconds_baseline` | int | tempo medido de revisão manual (métrica) |

## `jev_decisions/*.json` — job `jev_classify`

`finding_id`, `review_id`, `needs_review` (bool), `priority` (`baixa`/`media`/`alta`), `is_clear` (bool),
`jev_model`, `jev_request_hash`, `jev_response_valid` (bool), `decided_at`.

## `review_decisions/*.json` — portal

| Campo | Tipo | Observação |
|---|---|---|
| `review_id` | string | |
| `scope` | string | `FINDING` ou `REVIEW` |
| `finding_id` | string | obrigatório se `scope = FINDING` |
| `action` | string | `CONFIRM` / `CORRECT` / `REJECT` (finding) ou `SIGNOFF` (review) |
| `corrected_value`, `corrected_unit` | double, string | obrigatório ao menos um se `CORRECT` |
| `reviewer_tech_id` | string | identificador técnico **não clínico** do revisor |
| `decided_at` | timestamp | a ação mais recente por (`review_id`, `finding_id`) vale |

Exemplo: `tools/sample_events/review_decisions_case_c.json`.

## `attestations/*.json` — backend, após enviar a transação

`review_id`, `cluster`, `program_id`, `pda_address`, `tx_signature`, `input_hash`, `analysis_hash`,
`reviewed_hash` (copiados de `gold_attestation_payload`), `workflow_version`, `model_version`, `status`,
`reviewer_tech_id`, `submitted_at`. Exemplo: `tools/sample_events/attestation_case_c.json`.

## `attestation_verifications/*.json` — job `verify_onchain`

`review_id`, `pda_address`, `tx_signature`, `account_found`, `tx_confirmed`, `onchain_input_hash`,
`onchain_analysis_hash`, `onchain_reviewed_hash`, `onchain_status`, `slot`, `error`, `verified_at`.

## `gabarito/*.csv` — equipe (benchmark)

`case_id, finding_type, finding_subtype, test_code, exam_date, expected_page, note`.
