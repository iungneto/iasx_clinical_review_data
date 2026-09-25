# Contrato com o programa Solana (atestação)

A stack de dados não implementa o programa; este é o contrato que `verify_onchain.py` espera ler.
Se o time do programa mudar o layout, atualize `decode_account` no notebook.

## PDA

`seeds = [b"review", sha256(review_id)]` — `sha256(review_id)` são 32 bytes, então o `review_id` em texto
não vai para a cadeia.

## Conta `ReviewAttestation` (Anchor, little-endian)

| Offset | Tamanho | Campo | Origem |
|---|---|---|---|
| 0 | 8 | discriminator Anchor | |
| 8 | 32 | `review_id_hash` | sha256(`review_id`) |
| 40 | 32 | `input_hash` | `gold_attestation_payload.input_hash` |
| 72 | 32 | `analysis_hash` | `gold_attestation_payload.analysis_hash` |
| 104 | 32 | `reviewed_hash` | `gold_attestation_payload.reviewed_hash` |
| 136 | 32 | `workflow_version` | UTF-8, preenchido com `\0` |
| 168 | 32 | `model_version` | UTF-8, preenchido com `\0` |
| 200 | 1 | `status` (u8) | 0 CREATED, 1 PROCESSING, 2 AI_REVIEW_READY, 3 HUMAN_REVIEW_REQUIRED, 4 CONFIRMED, 5 CORRECTED, 6 ATTESTED |
| 201 | 32 | `reviewer` (Pubkey) | carteira técnica do revisor |
| 233 | 8 | `attested_at` (i64) | `Clock::get()?.unix_timestamp` |
| 241 | 1 | `bump` | |

Total: 242 bytes, incluindo o discriminator.

## O que nunca vai on-chain

Nome, CPF, exames, laudos, medicamentos, alergias, diagnósticos, texto clínico, `case_id`, trechos de evidência.
