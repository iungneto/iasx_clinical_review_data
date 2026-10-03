# Riscos, conformidade do MVP e evolução regulatória — IASX Clinical Review

Atualizado em 01/10/2026, a partir da *Matriz Regulatória, Legal, de Segurança e Normas Técnicas*
(referências vigentes em 30/09/2026). Finalidade e limites: [intended_use.md](intended_use.md).

Este é um registro de engenharia, não parecer jurídico ou regulatório. ISO/IEC são referências de boas
práticas; o MVP não busca certificação.

## 1. Registro de riscos (ISO 14971:2019, forma simplificada)

Severidade e probabilidade são qualitativas e consideram o uso pretendido do MVP (demonstração, dados sintéticos).

| # | Perigo | Situação perigosa | Controles implementados | Evidência (código / teste) | Risco residual no MVP |
|---|---|---|---|---|---|
| R1 | Dado pessoal real entra no sistema | PDF ou caso real enviado à API ou à landing | `data_classification = SYNTHETIC` obrigatório; upload exige a declaração "Documento sintético"; a pipeline não propaga texto de PDF sem a declaração e gera a lacuna `NOT_SYNTHETIC_DOCUMENT`; column mask no PDF bruto (`bronze_documents.content`) só para `iasx_raw_document_readers` | `src/app/models.py`, `src/app/guards.py`, `silver_document_pages`, `gold_gaps`, `src/sql/access_policies.sql`; testes `test_case_requires_synthetic_declaration`, `test_upload_guard_accepts_synthetic_and_refuses_the_rest`, `test_document_content_columns_are_masked`, Caso D (`D_sem_marcacao`) | Baixo. A declaração é uma trava contra envio acidental, não prova de que o conteúdo é sintético; o PDF bruto de quem burlar a trava escrevendo direto no volume fica na bronze, legível só pela identidade da pipeline |
| R2 | Exposição de identificadores diretos | Nome, CPF, nascimento, contato ou médico aparecem na API ou nas tabelas silver/gold | Mascaramento antes da silver (nome, CPF, CNS, RG, nascimento, telefone, e-mail, endereço, médico/CRM), com comprimento preservado; column masks do Unity Catalog no texto do documento (`page_text`, `source_text`, `date_source_text`, trecho de `evidence`) só para `iasx_clinical_text_readers` | `clinical_rules.mask_identifiers`, `src/sql/access_policies.sql`; testes `test_direct_identifiers_are_masked`, `test_masking_preserves_offsets_and_results`, `tests/test_access_policies.py`; verificado no dev como não membro (texto `[restrito]`, ponteiros da fonte visíveis) | Baixo. Identificador em texto livre fora dos padrões não é removido pela transformação, mas só os membros do grupo leem o texto. O resumo do achado (exame e valor) fica sob grants, sem máscara |
| R3 | Informação ausente preenchida por inferência | Profissional vê data, unidade, faixa ou valor que não estão no documento | Ausência vira `None` e lacuna; faixa só a do documento; valor ambíguo vira `AMBIGUOUS_VALUE` | `parse_page`, `gold_gaps`; testes `test_missing_information_is_never_filled`, `test_missing_unit_is_not_inferred`, `test_ambiguous_value_is_flagged_never_picked` | Baixo |
| R4 | Achado sem fonte | Profissional não consegue conferir a origem | Evidência obrigatória com documento, página, linha e offsets; a gold falha a atualização sem fonte | `gold_findings` (`ON VIOLATION FAIL UPDATE`); `test_source_offsets_point_to_the_line` | Baixo |
| R5 | IASX escolhe uma versão em conflito | Valor divergente apresentado como verdadeiro | Conflito lista todas as versões; revisão humana obrigatória; prioridade mínima média | `gold_conflicts`, `gold_review_queue` | Baixo |
| R6 | Comparação entre unidades diferentes | Variação calculada sobre unidades incompatíveis | Unidade diferente (ou ausente de um lado) vira `UNIT_CHANGED`, sem delta | `gold_temporal_comparison`; Caso D | Baixo. Não há conversão de unidades, por decisão |
| R7 | JEV usado como decisão clínica | Classificação interpretada como diagnóstico | Perguntas só de fluxo de trabalho; gold sobrepõe o JEV; `SIGNOFF` humano obrigatório | `jev_contract.QUESTIONS`; `test_questions_are_about_workflow_never_diagnosis` | Baixo |
| R8 | Falha ou resposta fora do schema do JEV | Achado sem triagem passa despercebido | Resposta inválida vira `jev_response_valid = false` → revisão humana, prioridade alta | `classify`, `gold_review_queue`; `test_failure_or_out_of_schema_is_invalid_not_dropped` | Baixo |
| R9 | Saída sem rastreabilidade de versão | Impossível reconstruir qual versão gerou o resultado | `extractor_version` por medição; `jev_model`, `jev_prompt_version`, hash do envio e resposta bruta por decisão; `review_reasons`/`priority_reason`; `model_version` on-chain derivado do que realmente rodou (ex.: `mock-jev`); mudança nas perguntas do Jev reclassifica os achados de revisões não finalizadas | `silver_lab_results`, `silver_jev_decisions`, `gold_review_queue`, `gold_attestation_payload`, `jev_classify`; `test_every_decision_has_an_objective_traceable_reason` | Baixo |
| R10 | Dado clínico na blockchain | Conteúdo clínico imutável e público | Payload só com hashes, versões, status e IDs técnicos; `review_id` vai como sha256 | `gold_attestation_payload`, `onchain_layout`; `test_only_technical_fields_are_onchain`, `test_attestation_payload_has_no_clinical_columns` | Médio. Hash de documento pode ser associado a uma pessoa por quem tem o documento (§12 da matriz) |
| R11 | Atestação fora da Devnet | Custo e exposição em rede de produção | API aceita só `cluster = devnet`; a silver descarta outro cluster; `verify_onchain` recusa RPC fora da Devnet | `AttestationIn`, `silver_attestations`, `assert_devnet`; `test_other_clusters_are_refused` | Baixo |
| R12 | Segredo no repositório | Chave do JEV, token ou chave privada vazados | Chave do JEV em secret scope; token OAuth só no backend do JEV; varredura de segredos nos arquivos versionados | `test_no_secrets_in_tracked_files` | Baixo |
| R13 | Conteúdo enviado ao JEV externo | Dado sai do lakehouse para um terceiro | Contexto mínimo (tipo, subtipo, resumo), sem `case_id`/`review_id`; só dados sintéticos | `finding_context`; `test_context_is_minimal` | Baixo no MVP. Em produção é suboperador e possivelmente transferência internacional |
| R14 | Alegação indevida no pitch | Claim de aprovação, diagnóstico ou redução de mortes | Lista de claims proibidos; varredura de todo texto versionado | [intended_use.md](intended_use.md); `test_no_forbidden_claims` | Depende da equipe (slides e falas ficam fora do repositório) |
| R15 | Texto do achado ilegível ou enganoso | Revisor lê data como número ou variação como causa | Datas `dd/MM/yyyy` nos resumos; texto só descritivo (sem "piora", "causa") | `gold_findings`; `test_temporal_summaries_are_descriptive_dates_not_epoch_days` | Baixo |

## 2. Checklist regulatório do MVP (§14 da matriz)

| Item | Status | Onde |
|---|---|---|
| Dados 100% sintéticos | ✅ | Casos A–D gerados por `tools/generate_synthetic_cases.py`; travas R1 |
| Sem pacientes reais e sem finalidade assistencial | ✅ | [intended_use.md](intended_use.md); cabeçalho `X-IASX-Intended-Use` |
| Finalidade do protótipo documentada | ✅ | [intended_use.md](intended_use.md) |
| Limitações documentadas (sem diagnóstico, prescrição ou tratamento) | ✅ | [intended_use.md](intended_use.md) |
| JEV descrito como classificação/apoio à revisão | ✅ | [intended_use.md](intended_use.md), `jev_contract.py` |
| Casos de teste e respostas esperadas documentados | ✅ | `data/synthetic/gabarito.csv` (seção 4), `gold_benchmark`, `tests/` |
| Evidência/fonte preservada para cada achado | ✅ | R4 |
| Regras para conflitos, lacunas e ausência de informação | ✅ | R3, R5, R6 |
| Segredos e chaves fora do código | ✅ | R12 |
| Sem dados clínicos na blockchain | ✅ | R10 |
| Solana apenas para atestação técnica na Devnet | ✅ | R11 |
| Versionamento de workflow, regras/modelo e hashes | ✅ | R9 |
| README com arquitetura, limitações e segurança | ✅ | `README.md` (seções Segurança e Limitações), `docs/architecture.md` |
| Não alegar aprovação/registro Anvisa | ✅ | [intended_use.md](intended_use.md); `test_no_forbidden_claims` |
| Não alegar que o sistema evita mortes, erros médicos ou garante segurança | ✅ | [intended_use.md](intended_use.md); `test_no_forbidden_claims` |
| Documento de riscos e plano de evolução regulatória | ✅ | este documento |

### Verificação automatizada

`uv run pytest -q` cobre os itens acima sem Databricks. `tests/test_api_endpoints.py` exercita a API publicada
para o JEV sobre a base mockada (`tools/mock_db/`, retrato das tabelas silver/gold dos casos A–D): finalidade em
toda resposta, fonte de cada achado conferida contra o texto da página, mascaramento, recusa de PDF sem
declaração de dado sintético, regras de conflito e lacuna, payload on-chain só técnico e restrição à Devnet.
A integração real (pipeline, Jev e Solana) é verificada com `databricks bundle run iasx_review_cycle`.

## 3. Riscos residuais e pendências para um piloto real (§15 da matriz)

Nenhum item abaixo está feito; todos são pré-requisitos antes de tratar dado real.

- **Enquadramento:** parecer de SaMD (RDC 657/2022), classe de risco e regime (RDC 751/2022); claims congelados.
  Evoluir para diagnóstico, recomendação terapêutica ou monitoramento muda o enquadramento.
- **LGPD/ANPD:** controlador, operadores, suboperadores (Databricks, typesafe.ai, provedor RPC) e encarregado
  (Res. 18/2024); base legal por finalidade; RIPD; transferência internacional (Res. 19/2024); comunicação de
  incidentes em 3 dias úteis (Res. 15/2024); retenção e descarte (PDF bruto, texto extraído, logs, decisões do JEV).
- **Blockchain:** substituir `sha256` puro de documentos por compromisso com chave (HMAC) ou salt guardado
  off-chain, para que o hash não seja associável por terceiros; avaliar imutabilidade frente a correção e
  eliminação; documentar chaves, rotação e recuperação.
- **Bronze:** o PDF bruto (`bronze_documents`) contém identificadores e já tem column mask; em produção, somar
  criptografia, retenção curta e trilha de acesso (`system.access.audit`).
- **Grupos de acesso:** no MVP são grupos locais do workspace com membros definidos por script; em produção, grupos
  de conta (`is_account_group_member`) geridos pelo IdP, com revisão periódica de membros.
- **Segurança:** MFA, menor privilégio, segregação de ambientes, gestão de vulnerabilidades,
  SAST/DAST/dependências, pentest, backup e continuidade (ISO/IEC 27001/27002, ISO 27799).
- **IA/JEV:** validação de desempenho com dados representativos, métricas e critérios de aceitação, vieses,
  monitoramento de drift e controle de mudanças de modelo e perguntas (ISO/IEC 42001).
- **Software:** ciclo de vida IEC 62304 e IEC 82304-1; QMS ISO 13485 e BPF (RDC 665/2022) conforme a classe;
  requisitos de segurança e desempenho (RDC 848/2024).
- **Prontuário e interoperabilidade:** fora do escopo; antes de integrar, definir autoria, edição e auditoria
  (Lei 13.787/2018) e padrões RNDS/HL7 FHIR.

## 4. Casos de teste e respostas esperadas

Respostas esperadas achado a achado: `data/synthetic/gabarito.csv`, comparado com a saída real em `gold_benchmark`
(cobertura e precisão da página de origem em `gold_mvp_metrics`).

| Caso | Cobre | Achados esperados |
|---|---|---|
| A — normal | Laudo consistente | Nenhum |
| B — evolução | Mesmo exame em três datas | 2 fora da faixa, 2 variações temporais |
| C — principal | Documentos contraditórios, lacunas, página digitalizada | 2 fora da faixa, 1 conflito, 5 lacunas |
| D — unidades e ambiguidade | Troca de unidade, unidade ausente, valores ambíguos, identificadores para mascarar, PDF sem declaração de dado sintético | 2 fora da faixa, 2 `UNIT_CHANGED`, 4 lacunas (`MISSING_UNIT`, 2 `AMBIGUOUS_VALUE`, `NOT_SYNTHETIC_DOCUMENT`) |

## 5. Roadmap regulatório (§17 da matriz)

| Fase | Objetivo | Estado |
|---|---|---|
| 0 — Hackathon | Provar o conceito com segurança | Este repositório |
| 1 — Enquadramento | Definir o produto real: finalidade, claims, SaMD, classe, mapa LGPD, arquitetura | Pendente |
| 2 — Validação | Gestão de risco formal, requisitos, validação de software/IA, evidência clínica | Pendente |
| 3 — Regularização | Dossiê técnico, QMS/BPF, notificação/registro quando aplicável, rotulagem/IFU | Pendente |
| 4 — Operação | Monitoramento, incidentes, mudanças, auditorias, pós-mercado | Pendente |

Repetir a checagem regulatória antes de qualquer piloto: normas e regulamentos podem mudar (§19 da matriz).
