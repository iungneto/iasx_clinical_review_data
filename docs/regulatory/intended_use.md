# Finalidade pretendida e limitações — IASX Clinical Review (MVP)

Versão do workflow: `iasx-wf-1.0.0` · Extrator: `extract-rules-1.1.0` · Atualizado em 01/10/2026.
Base: *Matriz Regulatória, Legal, de Segurança e Normas Técnicas* (referências vigentes em 30/09/2026).

> Este documento registra a finalidade do **protótipo do hackathon**. Não é parecer jurídico nem
> enquadramento regulatório. Antes de qualquer piloto com pacientes ou uso comercial, o enquadramento
> como SaMD (RDC 657/2022), a classe de risco (RDC 751/2022) e o mapeamento LGPD precisam ser feitos com
> especialista.

## Finalidade

Demonstrar tecnicamente, com **dados 100% sintéticos**, um fluxo de **apoio à revisão e à estruturação de
informação** de laudos laboratoriais em PDF:

1. extrair resultados de exame com a fonte exata (documento, página, linha e trecho);
2. organizar linha do tempo e comparação entre coletas;
3. sinalizar, sem decidir, valores fora da faixa **informada no próprio documento**, variações entre
   coletas, conflitos entre documentos e lacunas de informação;
4. priorizar a fila de revisão do profissional (JEV);
5. registrar as ações do profissional e uma **atestação técnica de integridade** na Solana Devnet.

## Usuários e ambiente

- Equipe do hackathon e avaliadores, em workspace Databricks Free Edition de demonstração.
- Sem pacientes reais, sem uso assistencial, sem integração com prontuário.

## O que o IASX não faz

| Não faz | Como o código garante |
|---|---|
| Diagnóstico, prescrição, recomendação de tratamento | Achados são só comparações com o próprio documento; perguntas do Jev são de fluxo de trabalho (`src/jobs/jev_contract.py`, teste `test_questions_are_about_workflow_never_diagnosis`) |
| Substituir o profissional | Nenhuma revisão fecha sem `SIGNOFF` humano; conflito e lacuna exigem ação humana (`gold_review_queue`) |
| Inferir informação ausente | Data, unidade, faixa ou valor ausentes viram lacuna; valor ambíguo (`< 0,5`, `1,0 ou 1,3`) vira `AMBIGUOUS_VALUE` |
| Usar faixa de referência externa | Só a faixa impressa no documento |
| Afirmar causalidade | Variação temporal é descrita como diferença numérica entre datas; o limiar de 20% é de apresentação, não clínico |
| Escolher entre versões conflitantes | `gold_conflicts` lista todas as versões com fonte |
| Processar dado real | API exige `data_classification = SYNTHETIC` e PDF com a declaração "Documento sintético"; a pipeline não propaga o texto de PDF sem a declaração (`NOT_SYNTHETIC_DOCUMENT`) |
| Gravar dado clínico na blockchain | On-chain só vão hashes, versões, status e carteira técnica (`docs/onchain_account_layout.md`) |

## Papel do JEV

O JEV é uma **camada de classificação, regras e apoio à revisão**: responde se um achado precisa de revisão,
qual a prioridade **de fluxo de trabalho** e se a informação está clara. Não é mecanismo de decisão clínica.
As regras de segurança da gold sempre prevalecem sobre o JEV, e cada decisão final tem justificativa
(`review_reasons`, `priority_reason`) e versão rastreável (`jev_model`, `jev_prompt_version`).

## Papel da blockchain

A Solana Devnet prova que **um compromisso técnico foi registrado** (hashes de entrada, análise e revisão).
Ela **não prova** que o conteúdo clínico está correto nem que alguma interpretação é verdadeira.

## Comunicação (pitch, README, telas)

Permitido: "apoio à revisão", "estruturação de informação", "rastreabilidade da fonte", "atestação técnica de
integridade", "demonstração com dados sintéticos".

Proibido enquanto não houver evidência ou regularização correspondente:

- dizer que o IASX é aprovado, registrado ou notificado na Anvisa, ou certificado em qualquer norma ISO/IEC;
- dizer que o IASX diagnostica, recomenda tratamento, evita mortes, reduz erro médico ou garante segurança;
- apresentar o JEV como médico, diagnosticador ou decisor autônomo;
- apresentar a atestação on-chain como prova de que o laudo ou a interpretação estão corretos.

A API anuncia esta finalidade em toda resposta (`X-IASX-Intended-Use`) e em `GET /api/health`.
