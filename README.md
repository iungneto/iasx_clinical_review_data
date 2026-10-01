# IASX Clinical Review — Stack de dados

Stack de dados do MVP **IASX Clinical Review** (IA + Jev + Blockchain) no **Databricks Free Edition**, com
**Lakeflow Declarative Pipelines** (antigo DLT) como motor de pipelines e **Lakeflow Jobs** para orquestrar.
Tudo é empacotado como **Declarative Automation Bundle** (antigo Asset Bundle) e publicado com a CLI `databricks`.

> **Finalidade e limites.** Demonstração técnica com **dados 100% sintéticos**, sem pacientes reais e sem uso
> assistencial. O IASX apoia a revisão e a estruturação de informação: **não diagnostica, não prescreve, não
> recomenda tratamento e não substitui o profissional**. Não é regularizado na Anvisa. O JEV classifica e
> prioriza a revisão; a Solana Devnet guarda só uma atestação técnica (hashes), nunca dado clínico.
> Detalhes em [docs/regulatory/intended_use.md](docs/regulatory/intended_use.md); riscos, checklist do MVP e
> pendências para um piloto real em [docs/regulatory/risk_and_compliance.md](docs/regulatory/risk_and_compliance.md).

> **Community Edition × Free Edition:** a Community Edition antiga não tem Unity Catalog, volumes, jobs nem
> pipelines declarativas. Este projeto usa a **Free Edition** (a substituta gratuita), que tem compute serverless,
> Unity Catalog (catálogo `workspace`), Lakeflow Pipelines, Jobs e SQL Warehouse, com cotas de uso reduzidas.

## Fluxo coberto (seções 6, 7 e 13 do documento)

```
PDF sintético → bronze (Auto Loader) → páginas + identificadores mascarados → resultados com fonte
  → linha do tempo / comparação temporal / conflitos / lacunas → achados (finding_id determinístico)
  → Jev (Noul/Choice) + regras de segurança → fila de revisão → ações do profissional + signoff
  → payload de atestação (hashes) → tx Solana (backend) → verificação da PDA → ATTESTED
```

Arquitetura, estados e regras: [docs/architecture.md](docs/architecture.md) ·
Contratos da landing: [docs/data_contracts.md](docs/data_contracts.md) ·
Contrato com o programa Solana: [docs/onchain_account_layout.md](docs/onchain_account_layout.md) ·
Finalidade e limites: [docs/regulatory/intended_use.md](docs/regulatory/intended_use.md) ·
Riscos e conformidade: [docs/regulatory/risk_and_compliance.md](docs/regulatory/risk_and_compliance.md)

## Estrutura

```
iasx_clinical_review_data/
├── databricks.yml                       # bundle: variáveis (catálogo, schema, workflow, Solana) e target dev
├── resources/
│   ├── iasx_unity_catalog.yml           # schema iasx_clinical + volume landing
│   ├── iasx_clinical.pipeline.yml       # pipeline serverless (pypdf, configs iasx.*)
│   ├── iasx_jev_api.app.yml             # Databricks App: API consumida pelo frontend JEV
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
│   ├── app/                             # API FastAPI do JEV (app.py, backend.py, models.py, guards.py)
│   ├── jobs/
│   │   ├── 00_bootstrap_landing.py      # cria pastas e carrega os casos sintéticos
│   │   ├── jev_classify.py              # chama o Jev server-side (notebook)
│   │   ├── jev_contract.py              # perguntas, request/response e rastreabilidade do Jev
│   │   ├── verify_onchain.py            # lê a PDA na Solana Devnet (notebook)
│   │   └── onchain_layout.py            # layout da conta de atestação e trava de Devnet
│   └── sql/portal_queries.sql           # consultas do backend do portal
├── tools/
│   ├── generate_synthetic_cases.py      # gera PDFs A–D, cases.json, gabarito.csv
│   ├── mock_db/                         # base mockada: tabelas gold/silver exportadas + backend e API locais
│   └── sample_events/                   # exemplos de eventos do portal/backend
├── data/synthetic/                      # saída do gerador (sincronizada pelo bundle)
├── docs/
│   └── regulatory/                      # finalidade pretendida, riscos, checklist do MVP, roadmap
└── tests/                               # regras, API de ponta a ponta (mock), Jev, on-chain e conformidade
```

## Passo a passo

### 1. Pré-requisitos

- Conta no [Databricks Free Edition](https://www.databricks.com/learn/free-edition).
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) (versão recente) e login:
  `databricks auth login --host https://<seu-workspace>.cloud.databricks.com`
- Em `databricks.yml`, troque `REPLACE_WITH_YOUR_WORKSPACE` pela URL do workspace.

### 2. Testes locais e dados sintéticos

```bash
uv sync                                               # .venv Python 3.12 (Databricks Connect + pytest/pypdf/pydantic)
uv run pytest -q                                      # também gera data/synthetic/
uv run python tools/generate_synthetic_cases.py       # (ou só isto, para gerar os dados)
```

Sem uv: `python -m venv .venv`, `pip install -r requirements-dev.txt` e `pytest -q`.

**Base mockada.** `tools/mock_db/tables/` guarda um retrato das tabelas que a API lê (casos A–D, só silver/gold,
já mascaradas). Com ela, `tests/test_api_endpoints.py` exercita a API inteira sem Databricks, e o frontend JEV
pode ensaiar contra uma API local:

```bash
uv run python tools/mock_db/serve.py                  # http://127.0.0.1:8000/docs, escritas só em memória
uv run python tools/mock_db/export_from_workspace.py --profile <perfil> --schema workspace.<schema>   # reexporta
```

Reexporte depois de mudar regras, perguntas do Jev ou colunas da gold; `tests/test_mock_db.py` falha se as
colunas do `backend.py` deixarem de existir na base.

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
databricks bundle run iasx_bootstrap                  # pastas da landing + casos A–D
databricks bundle run iasx_review_cycle               # pipeline → Jev → verificação → pipeline
```

### 5. Simular o portal (revisão humana e atestação)

1. Consulte `gold_review_queue` (query 2 de `src/sql/portal_queries.sql`) e copie os `finding_id`.
2. Preencha `tools/sample_events/review_decisions_case_c.json` e envie para a landing:
   `databricks fs cp tools/sample_events/review_decisions_case_c.json dbfs:/Volumes/workspace/iasx_clinical/landing/review_decisions/rd_001.json`
   (no target `dev`, o schema é `dev_<usuário>_iasx_clinical`)
3. Rode `iasx_review_cycle` → caso C fica `CONFIRMED`/`CORRECTED` e `ready_for_attestation = true`.
4. O backend lê `gold_attestation_payload` (query 6), envia a tx para a Devnet e grava o recibo
   (`tools/sample_events/attestation_case_c.json`) em `landing/attestations/`.
5. Rode `iasx_review_cycle` de novo → `verify_onchain` lê a PDA, a pipeline compara os hashes e o caso vira
   **ATTESTED** (`gold_review_status.is_finalized = true`).

### 6. API para o frontend JEV

O **JEV** (frontend externo) conversa com o Databricks só pela API `iasx-jev-api`, um Databricks App (FastAPI)
publicado pelo mesmo bundle. Não confundir com o **Jev da typesafe.ai**, o classificador chamado pelo job `jev_classify`.

```bash
databricks bundle deploy -t dev                      # as tabelas gold precisam existir (rode iasx_review_cycle antes)
databricks bundle run iasx_jev_api -t dev            # inicia o app e mostra a URL
```

A documentação interativa (OpenAPI) fica em `<url do app>/docs`.

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/health`, `/api/whoami` | teste de conexão e identidade de quem chamou |
| GET | `/api/cases` | casos com estado da revisão e status on-chain |
| GET | `/api/cases/{case_id}/queue` · `/timeline` · `/comparison` | fila de revisão, linha do tempo, comparação temporal |
| GET | `/api/findings/{finding_id}/evidence` | fonte do achado (documento, página, linha, offsets) |
| GET | `/api/documents/{document_id}/pages/{page_num}` | texto mascarado da página |
| GET | `/api/reviews/{review_id}/attestation-payload` | payload que vai para a Solana |
| GET | `/api/metrics` | métricas do MVP e benchmark |
| POST | `/api/cases` | registra caso → `landing/cases/` |
| POST | `/api/cases/{case_id}/documents/{document_id}` | upload do PDF (multipart `file`) → `landing/pdfs/` |
| POST | `/api/review-decisions` | CONFIRM / CORRECT / REJECT / SIGNOFF → `landing/review_decisions/` |
| POST | `/api/attestations` | recibo da tx Solana → `landing/attestations/` |
| POST · GET | `/api/review-cycle/runs` · `/runs/{run_id}` | dispara `iasx_review_cycle` e acompanha a execução |

A API preenche `created_at`, `decided_at` e `submitted_at` e valida os contratos de
[docs/data_contracts.md](docs/data_contracts.md). As escritas só aparecem nas rotas GET depois de uma
execução de `iasx_review_cycle`.

**Somente dados sintéticos.** `POST /api/cases` exige `"data_classification": "SYNTHETIC"`, e o upload recusa
(422) PDF cujo texto não traga a declaração "Documento sintético". Campos técnicos (`case_id`, `scenario`,
`reviewer_tech_id`, unidades, hashes, endereços Solana) não aceitam texto livre, e a atestação só aceita
`cluster = devnet`. Toda resposta traz o cabeçalho `X-IASX-Intended-Use`, e `GET /api/health` devolve o
texto da finalidade pretendida para o frontend exibir.

**Autenticação.** Todo request precisa de `Authorization: Bearer <token OAuth do Databricks>`. As chamadas
partem do **backend do JEV** (servidor-a-servidor); o token nunca vai para o navegador. Para isso:

```bash
databricks service-principals create --display-name jev-frontend        # anote o applicationId
databricks service-principal-secrets-proxy create <id-numérico-do-SP>   # gera client_secret (guarde no cofre do JEV)
```

Depois, coloque o `applicationId` na variável `jev_client_id` de `databricks.yml`: o bundle concede `CAN_USE`
no app a esse service principal a cada deploy. No workspace dev isso já está feito (`jev-frontend`).

O backend do JEV troca as credenciais por um token (válido por 1 h) e chama a API:

```bash
curl -s -u "<applicationId>:<client_secret>" https://<workspace>/oidc/v1/token   -d grant_type=client_credentials -d scope=all-apis
curl -H "Authorization: Bearer <access_token>" https://<url do app>/api/cases
```

O service principal do próprio app recebe, pelos `resources` do bundle, apenas: `CAN_USE` no SQL Warehouse,
`SELECT` nas tabelas que a API expõe, `WRITE_VOLUME` na landing e `CAN_MANAGE_RUN` no `iasx_review_cycle`.
A `bronze_documents` (PDF bruto) fica de fora.

## Segurança (MVP)

- **Segredos fora do código.** Chave do Jev no secret scope `iasx`; `client_secret` do JEV só no cofre do
  backend do JEV; nenhum token no navegador. `tests/test_repo_compliance.py` varre os arquivos versionados.
- **Acesso mínimo.** A API exige OAuth do Databricks (HTTPS do Databricks Apps) e só o service principal do JEV
  tem `CAN_USE`; o app lê somente as tabelas que expõe (sem a bronze com o PDF bruto) e escreve só na landing.
- **Dados.** Somente sintéticos, com travas na entrada; identificadores mascarados antes da silver.
- **Logs** dos jobs registram só contagens e caminhos, nunca conteúdo de laudo.
- **Blockchain** só na Devnet e só com hashes, versões e status.
- **Ambiente** de desenvolvimento isolado (`mode: development`, schema com prefixo do usuário).

## Limitações

- Não diagnostica, não prescreve, não recomenda tratamento e não substitui o profissional; sem uso assistencial.
- Extração por regras só para laudos no formato dos casos sintéticos; sem OCR (página digitalizada vira lacuna).
- Sem conversão de unidades e sem faixa de referência externa; valor ambíguo ou ausente vira lacuna.
- O limiar de variação temporal é de apresentação, não critério clínico; variação não implica causalidade.
- A atestação prova que um compromisso técnico foi registrado, não que o laudo ou a interpretação estão corretos.
- O hash de um documento pode ser associado a ele por quem o tem (risco R10 em
  [risk_and_compliance.md](docs/regulatory/risk_and_compliance.md)).

## Decisões de projeto

- **Extração determinística por regras** para o P0: reprodutível (hash da análise estável), sem custo de
  modelo e cada valor com offset exato no texto. A troca por `ai_parse_document`/`ai_query` pode ser feita
  depois, dentro de `silver_lab_results`, desde que mantenha o contrato de evidência.
- **Faixa de referência só a do documento.** Sem faixa no PDF, o IASX registra lacuna em vez de usar uma tabela externa.
- **Valor ambíguo não vira número.** `< 0,5` ou `1,0 ou 1,3` viram a lacuna `AMBIGUOUS_VALUE`; unidade diferente
  entre coletas vira `UNIT_CHANGED`, sem conversão.
- **Mascaramento com comprimento preservado.** Nome, CPF, CNS, nascimento, contato e médico/CRM são trocados por `*`
  antes da silver; os offsets das evidências continuam válidos.
- **`model_version` vem dos dados.** A atestação registra o extrator e o modelo do Jev que realmente geraram a
  análise (ex.: `extract-rules-1.1.0+mock-jev`), não um valor configurado.
- **Variação temporal ≥ 20%** (`iasx.temporal_variation_pct`) é um limiar de apresentação, não um critério clínico.
- **Uma pipeline, um schema** (`bronze_*`, `silver_*`, `gold_*`) para caber nas cotas da Free Edition.
- **Portal/backend escrevem só na landing**; lê gold via SQL Warehouse. A pipeline é a única que escreve tabelas.

## Pendências a validar antes da demo

- **Contrato da API do Jev:** `build_request`/`extract_answer` em `src/jobs/jev_contract.py` seguem o que o
  documento descreve (`POST /v1/systemone`, `GET /v1/models`, Bearer, Noul/Choice). Confira os campos exatos em
  https://api.typesafe.ai/docs. Qualquer resposta fora do esperado vira `jev_response_valid = false`, e isso força revisão humana.
- **Layout da conta Solana:** alinhar `docs/onchain_account_layout.md` com o programa Anchor e preencher
  `solana_program_id` em `databricks.yml`.
- **Baseline manual:** preencher `manual_review_seconds_baseline` em `cases.json` com tempos medidos.
- **Cotas da Free Edition:** o compute serverless tem limite diário; na demo, rode o ciclo sob demanda.
