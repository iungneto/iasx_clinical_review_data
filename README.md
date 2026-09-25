# IASX Clinical Review — Stack de dados

Stack de dados do MVP **IASX Clinical Review** (IA + Jev + Blockchain) no **Databricks Free Edition**, com
**Lakeflow Declarative Pipelines** (antigo DLT) como motor de pipelines e **Lakeflow Jobs** para orquestrar.
Tudo é empacotado como **Declarative Automation Bundle** (antigo Asset Bundle) e publicado com a CLI `databricks`.

> **Community Edition × Free Edition:** a Community Edition antiga não tem Unity Catalog, volumes, jobs nem
> pipelines declarativas. Este projeto usa a **Free Edition** (a substituta gratuita), que tem compute serverless,
> Unity Catalog (catálogo `workspace`), Lakeflow Pipelines, Jobs e SQL Warehouse, com cotas de uso reduzidas.

## Fluxo coberto (seções 6, 7 e 13 do documento)

```
PDF sintético → bronze (Auto Loader) → páginas + CPF mascarado → resultados com fonte
  → linha do tempo / comparação temporal / conflitos / lacunas → achados (finding_id determinístico)
  → Jev (Noul/Choice) + regras de segurança → fila de revisão → ações do profissional + signoff
  → payload de atestação (hashes) → tx Solana (backend) → verificação da PDA → ATTESTED
```

Arquitetura, estados e regras: [docs/architecture.md](docs/architecture.md) ·
Contratos da landing: [docs/data_contracts.md](docs/data_contracts.md) ·
Contrato com o programa Solana: [docs/onchain_account_layout.md](docs/onchain_account_layout.md)

## Estrutura

```
iasx_clinical_review_data/
├── databricks.yml                       # bundle: variáveis (catálogo, schema, versões, Solana) e target dev
├── resources/
│   ├── iasx_unity_catalog.yml           # schema iasx_clinical + volume landing
│   ├── iasx_clinical.pipeline.yml       # pipeline serverless (pypdf, configs iasx.*)
│   └── iasx_orchestration.job.yml       # jobs iasx_bootstrap e iasx_review_cycle
├── src/
│   ├── pipeline/
│   │   ├── utilities/                   # extração determinística (Python puro, testável)
│   │   │   ├── clinical_rules.py
│   │   │   └── pdf_parsing.py
│   │   └── transformations/
│   │       ├── bronze/                  # Auto Loader: PDFs, feeds JSON, gabarito
│   │       ├── silver/                  # páginas, resultados, Auto CDC dos feeds
│   │       └── gold/                    # MVs SQL: timeline, comparação, conflitos, lacunas,
│   │                                    #   achados, fila, payload, estado, benchmark, métricas
│   ├── jobs/
│   │   ├── 00_bootstrap_landing.py      # cria pastas e carrega os casos sintéticos
│   │   ├── jev_classify.py              # chama o Jev server-side
│   │   └── verify_onchain.py            # lê a PDA na Solana Devnet
│   └── sql/portal_queries.sql           # consultas do backend do portal
├── tools/
│   ├── generate_synthetic_cases.py      # gera PDFs A/B/C, cases.json, gabarito.csv
│   └── sample_events/                   # exemplos de eventos do portal/backend
├── data/synthetic/                      # saída do gerador (sincronizada pelo bundle)
├── docs/
└── tests/test_clinical_rules.py
```

## Passo a passo

### 1. Pré-requisitos

- Conta no [Databricks Free Edition](https://www.databricks.com/learn/free-edition).
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) (versão recente) e login:
  `databricks auth login --host https://<seu-workspace>.cloud.databricks.com`
- Em `databricks.yml`, troque `REPLACE_WITH_YOUR_WORKSPACE` pela URL do workspace.

### 2. Testes locais e dados sintéticos

```bash
python -m venv .venv && .venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                             # também gera data/synthetic/
python tools/generate_synthetic_cases.py              # (ou só isto, para gerar os dados)
```

### 3. Segredo do Jev (nunca no repositório)

```bash
databricks secrets create-scope iasx
databricks secrets put-secret iasx jev_api_key       # cola a chave quando pedir
```

Sem chave ainda? Rode o job com `jev_mode=mock` para ensaiar a demo (resultado marcado como `mock-jev`).

### 4. Deploy e execução

```bash
databricks bundle validate
databricks bundle deploy                              # cria schema, volume, pipeline e jobs
databricks bundle run iasx_bootstrap                  # pastas da landing + casos A/B/C
databricks bundle run iasx_review_cycle               # pipeline → Jev → verificação → pipeline
```

### 5. Simular o portal (revisão humana e atestação)

1. Consulte `gold_review_queue` (query 2 de `src/sql/portal_queries.sql`) e copie os `finding_id`.
2. Preencha `tools/sample_events/review_decisions_case_c.json` e envie para a landing:
   `databricks fs cp tools/sample_events/review_decisions_case_c.json dbfs:/Volumes/workspace/iasx_clinical/landing/review_decisions/rd_001.json`
3. Rode `iasx_review_cycle` → caso C fica `CONFIRMED`/`CORRECTED` e `ready_for_attestation = true`.
4. O backend lê `gold_attestation_payload` (query 6), envia a tx para a Devnet e grava o recibo
   (`tools/sample_events/attestation_case_c.json`) em `landing/attestations/`.
5. Rode `iasx_review_cycle` de novo → `verify_onchain` lê a PDA, a pipeline compara os hashes e o caso vira
   **ATTESTED** (`gold_review_status.is_finalized = true`).

## Decisões de projeto

- **Extração determinística por regras** para o P0: reprodutível (hash da análise estável), sem custo de
  modelo e cada valor com offset exato no texto. A troca por `ai_parse_document`/`ai_query` pode ser feita
  depois, dentro de `silver_lab_results`, desde que mantenha o contrato de evidência.
- **Faixa de referência só a do documento.** Sem faixa no PDF, o IASX registra lacuna em vez de usar uma tabela externa.
- **Variação temporal ≥ 20%** (`iasx.temporal_variation_pct`) é um limiar de apresentação, não um critério clínico.
- **Uma pipeline, um schema** (`bronze_*`, `silver_*`, `gold_*`) para caber nas cotas da Free Edition.
- **Portal/backend escrevem só na landing**; lê gold via SQL Warehouse. A pipeline é a única que escreve tabelas.

## Pendências a validar antes da demo

- **Contrato da API do Jev:** `build_request`/`extract_answer` em `src/jobs/jev_classify.py` seguem o que o
  documento descreve (`POST /v1/systemone`, `GET /v1/models`, Bearer, Noul/Choice). Confira os campos exatos em
  https://api.typesafe.ai/docs. Qualquer resposta fora do esperado vira `jev_response_valid = false`, e isso força revisão humana.
- **Layout da conta Solana:** alinhar `docs/onchain_account_layout.md` com o programa Anchor e preencher
  `solana_program_id` em `databricks.yml`.
- **Baseline manual:** preencher `manual_review_seconds_baseline` em `cases.json` com tempos medidos.
- **Cotas da Free Edition:** o compute serverless tem limite diário; na demo, rode o ciclo sob demanda.
