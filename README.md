# RenovAI — Motor de Recomendação de Painel Médico

> Simulação local do PED 2.0 / RenovAI (Aché Farma).  
> Motor de inteligência artificial para recomendação do painel médico de propagandistas farmacêuticos.

---

## Índice

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Estrutura de Pastas](#estrutura-de-pastas)
- [Stack Tecnológica](#stack-tecnológica)
- [Fonte de Dados (`DATA_SOURCE`)](#fonte-de-dados-data_source)
- [Regras de Negócio](#regras-de-negócio)
- [Endpoints da API](#endpoints-da-api)
- [Banco de Dados](#banco-de-dados)
- [Camada LLM / Genie Local](#camada-llm--genie-local)
- [Jobs de Ciclo](#jobs-de-ciclo)
- [Autenticação](#autenticação)
- [Como Rodar Localmente](#como-rodar-localmente)
- [Testes](#testes)
- [Documentação Adicional](#documentação-adicional)
- [Próximas Etapas](#próximas-etapas)
- [Mapeamento Local → Produção](#mapeamento-local--produção)

---

## Visão Geral

O **RenovAI** é um motor de recomendação que apoia propagandistas farmacêuticos da Aché na gestão do painel médico. A cada ciclo mensal, o sistema analisa o ranking de médicos (baseado em volume de prescrições e outros critérios) e gera duas categorias de sugestões:

| Tipo | Critério | Ação sugerida |
|---|---|---|
| **ENTRADA_PAINEL** | Médico no ranking ≤ 400, fora do painel atual | Incluir no painel |
| **REVISAO_PAINEL** | Médico no painel com ranking > 400 **ou** sem visita há > 5 meses | Revisar permanência |

> A ampliação do critério de revisão para incluir médicos com ranking bom
> (≤ 400) sem visita há 5+ meses é o comportamento real da fonte hoje, mas
> ainda **não foi formalmente confirmada como regra intencional** com
> George/Bruno — ver `docs/context/known-issues.md`.

O propagandista recebe no máximo **5 sugestões por tipo** por ciclo, ordenadas por pontuação. Pode aceitar (ação tomada → `APLICADA`), desconsiderar com justificativa (`DESCONSIDERADA`) ou deixar expirar no fim do ciclo (`EXPIRADA`). **O fluxo de desconsiderar está congelado** (ver seção de Endpoints) — não recebe manutenção nova no momento.

Além das listas, o sistema oferece um **chat analítico em linguagem natural** que traduz perguntas do propagandista em SQL, executa no banco de dados e retorna a resposta sintetizada — simulando localmente o comportamento do Databricks Genie.

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                          │
│                     localhost:3000 (referência)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / REST
┌────────────────────────────▼────────────────────────────────────┐
│                    FastAPI — backend/app/                         │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ /auth        │  │/recomendacoes│  │ /gerencial           │  │
│  │ /contexto    │  │ /entrada     │  │ /indicadores         │  │
│  │              │  │ /revisao     │  │ /propagandistas      │  │
│  │              │  │ /desconsid.  │  │ /recomendacoes       │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                       │              │
│  ┌──────▼───────────────────────────────────────▼───────────┐  │
│  │              /prescricoes/consultar                        │  │
│  │          (NL → SQL → Execute → Síntese NL)                │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                              │                                    │
│  ┌───────────────────────────▼──────────────────────────────┐  │
│  │                   LLM Adapter Layer                        │  │
│  │  ClaudeProvider │ OpenAIProvider │ GeminiProvider │ GroqProvider │  │
│  │   (get_llm_provider() — selecionado via LLM_PROVIDER)     │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────┘
                                │ SQLAlchemy
                                │ db/databricks_connection.py:get_engine()
                                │ troca de fonte via DATA_SOURCE (.env)
              ┌─────────────────┴──────────────────┐
              ▼ DATA_SOURCE=local                   ▼ DATA_SOURCE=databricks
┌───────────────────────────┐          ┌────────────────────────────────────┐
│  PostgreSQL 15 (Docker)    │          │  Databricks SQL Warehouse (real)    │
│                            │          │  acheinfo_dev.renovai — OAuth M2M   │
│  tb_propagandistas         │          │  do SP sp-renovai-genie-api-poc     │
│  tb_ranking_medicos        │          │                                      │
│  tb_painel_medico          │          │  tb_propagandistas                  │
│  tb_prescricoes_geral      │          │  tb_recomendacoes_painel_historico  │
│  tb_recomendacoes_painel   │          │  vw_ranking_setor                   │
│  tb_visitacao_medica       │          │  vw_ranking_corte_hist              │
│  tb_hierarquia_gd          │          │  vw_ultima_visita                   │
└───────────────────────────┘          └────────────────────────────────────┘

Jobs (CLI / cron):
  gerar_recomendacoes.py  →  roda no início de cada ciclo
  atualizar_status.py     →  roda diariamente
  novo_ciclo.py           →  roda no último dia útil do mês
```

### Fluxo NL → SQL (Genie local)

```
Pergunta do usuário
      │
      ▼
1. Classificar intent (intent_rules.json)
   OPERACIONAL  →  aplica WHERE setor = '{setor_do_rep}'
   TOTAL_GERAL  →  sem filtro de setor
      │
      ▼
2. Detectar período (regex em intent_rules.json)
   período informado  →  aplica filtro de data
   sem período        →  aplica YTD (data >= {ano}-01-01)
      │
      ▼
3. Montar system prompt  (schema das tabelas + regras de negócio)
      │
      ▼
4. LLM gera SQL
      │
      ▼
5. Executar SQL via SQLAlchemy
      │
      ▼
6. LLM sintetiza resposta em linguagem natural
      │
      ▼
Resposta em texto + sql_gerado (apenas para perfil técnico)
```

---

## Estrutura de Pastas

```
renovai-local/
├── backend/
│   └── app/
│       ├── config.py                  # Leitura centralizada de env vars (pydantic-settings)
│       ├── main.py                    # FastAPI: routers + middleware de logging + CORS
│       ├── auth/
│       │   ├── context.py             # resolver_contexto() + GET /auth/contexto
│       │   └── jwt_auth.py            # resolver_email_autenticado() — flag AUTH_REQUIRE_JWT
│       ├── db/
│       │   └── databricks_connection.py  # get_engine() — alterna Postgres/Databricks via DATA_SOURCE
│       ├── genie/
│       │   ├── intent_rules.json      # ⚠️ ÚNICO arquivo a mudar após alinhamento com Pavan
│       │   └── nl_to_sql.py           # Fluxo completo NL→SQL→NL
│       ├── llm/
│       │   ├── adapter.py             # Interface abstrata LLMAdapter + factory
│       │   ├── claude_provider.py     # Anthropic SDK
│       │   ├── openai_provider.py     # OpenAI SDK
│       │   ├── gemini_provider.py     # Google Generative AI SDK
│       │   └── groq_provider.py       # SDK OpenAI apontado para api.groq.com (compatível)
│       ├── routers/
│       │   ├── prescricoes.py         # POST /prescricoes/consultar
│       │   ├── recomendacoes.py       # GET /entrada, /revisao | POST /desconsiderar (CONGELADO)
│       │   └── gerencial.py           # GET /indicadores, /propagandistas, /recomendacoes
│       ├── schemas/
│       │   ├── recomendacoes.py       # Contrato frontend ↔ backend (recomendações)
│       │   └── gerencial.py           # Contrato frontend ↔ backend (visão GD)
│       ├── jobs/
│       │   ├── gerar_recomendacoes.py # Gera sugestões por ciclo
│       │   ├── atualizar_status.py    # Atualiza PENDENTE → APLICADA diariamente
│       │   └── novo_ciclo.py          # Expira ciclo anterior + abre novo ciclo
│       └── tests/
│           ├── conftest.py
│           ├── test_context.py
│           ├── test_context_integration.py    # só roda com DATA_SOURCE=databricks
│           ├── test_jwt_auth.py
│           ├── test_prescricoes.py
│           ├── test_recomendacoes.py
│           ├── test_recomendacoes_integration.py  # só roda com DATA_SOURCE=databricks
│           ├── test_desconsiderar.py
│           ├── test_ciclo.py
│           ├── test_gerencial.py
│           ├── test_cenarios_completos.py  # 10 cenários E2E
│           └── test_golden_set.py          # 22 perguntas NL com taxa de acerto
├── data/
│   └── scripts/
│       ├── 01_create_tables.sql
│       ├── 02_populate_propagandistas.sql
│       ├── 03_populate_ranking.sql
│       ├── 04_populate_painel.sql
│       ├── 05_populate_prescricoes.sql
│       ├── 06_populate_hierarquia_gd.sql
│       ├── 07_simulate_recomendacoes.sql
│       ├── 08_create_views_gerencial.sql
│       └── validate_tables.py
├── docs/
│   ├── cenarios/
│   │   ├── matriz_teste.md            # 37 cenários em 6 grupos
│   │   └── golden_set.json            # 22 perguntas categorizadas
│   ├── context/                       # ler sob demanda — ver índice no CLAUDE.md
│   │   ├── decisions-log.md           # decisões de negócio/arquitetura datadas
│   │   ├── databricks-schema-real.md  # de-para completo schema local ↔ Databricks real
│   │   ├── known-issues.md            # bugs técnicos na fonte real, RESOLVIDO/ABERTO
│   │   └── arquitetura.md             # inventário completo do implementado + tasks
│   └── promocao_producao.md           # Checklist local → produção Aché
├── docker-compose.yml                 # PostgreSQL 15 + pgAdmin
├── requirements.txt
├── .env.example
├── CLAUDE.md                          # Contexto do projeto para Claude Code
└── README.md
```

---

## Stack Tecnológica

### Local (desenvolvimento)

| Componente | Tecnologia |
|---|---|
| Banco | PostgreSQL 15 via Docker |
| ORM | SQLAlchemy 2.x |
| Backend | Python 3.10+ / FastAPI |
| Validação | Pydantic v2 + pydantic-settings |
| LLM | Anthropic Claude / OpenAI GPT-4o / Google Gemini / Groq (selecionável via `LLM_PROVIDER` no `.env`) |
| Auth | Auth0 free tier (simula Entra ID) — JWT opcional via `AUTH_REQUIRE_JWT` |
| Fonte de dados | Postgres local **ou** Databricks real (`DATA_SOURCE`, ver seção abaixo) |
| Testes | pytest + unittest.mock |

### Produção (Aché)

| Componente | Tecnologia |
|---|---|
| Banco | Azure Databricks SQL Warehouse + Unity Catalog + Delta Lake |
| Backend | FastAPI em container Azure Container Apps |
| LLM | Databricks Genie via Service Principal |
| Auth | Microsoft Entra ID / SSO |
| Secrets | Azure Key Vault + Managed Identity |
| Observabilidade | Azure Monitor / Application Insights |

---

## Fonte de Dados (`DATA_SOURCE`)

A alternância local ↔ real é feita por `DATA_SOURCE` no `.env` (`local` | `databricks`), resolvida centralmente em `db/databricks_connection.py:get_engine()`. Nenhum outro módulo (`auth/**`, `routers/recomendacoes.py`) sabe ou deve saber qual fonte está por trás da engine.

| `DATA_SOURCE` | Engine | Autenticação |
|---|---|---|
| `local` (padrão) | PostgreSQL 15 via Docker | nenhuma (`docker-compose.yml`) |
| `databricks` | Databricks SQL Warehouse real (`acheinfo_dev.renovai`) | OAuth M2M (`client_credentials`) do Service Principal `sp-renovai-genie-api-poc` — **nunca PAT** |

Isso permite rodar a API localmente (`uvicorn` na sua máquina) apontando para o dado real de produção do Databricks, sem precisar do deploy em Azure. `GET /recomendacoes/entrada` e `GET /recomendacoes/revisao` já usam esse mecanismo e alternam nome de tabela/coluna por fonte (`tb_recomendacoes_painel` local vs. `tb_recomendacoes_painel_historico` real — ver `docs/context/databricks-schema-real.md`). `POST /recomendacoes/desconsiderar` ainda opera só contra o schema local (congelado, ver Endpoints).

---

## Regras de Negócio

### Cortes do ranking

| Ambiente | Entrada | Revisão |
|---|---|---|
| Local (simulado, Postgres) | posicao_ranking ≤ 100 | posicao_ranking > 100 |
| Produção / Databricks real | posicao_ranking (por setor) ≤ 400 | posicao_ranking (por setor) > 400 |

### Critérios de revisão

- **ABAIXO_CORTE** (modelo local) / `REVISAO_RANKING_SETOR_ACIMA_400` (fonte real) — médico no painel com ranking acima do corte
- **SEM_VISITA_5_MESES** (modelo local) / `REVISAO_SEM_VISITA_5_MESES` (fonte real) — médico no painel sem visita efetiva nos últimos 5 meses, **independente do ranking** (ver nota de pendência de negócio na Visão Geral)
- `REVISAO_RANKING_SETOR_ACIMA_400_E_SEM_VISITA_5_MESES` — combinação dos dois critérios (só existe na fonte real, `MOTIVO_RECOMENDACAO`)
- Trava adicional só na fonte real: propagandista precisa ter **mais de 400 médicos no painel** (`QTD_MEDICOS_PAINEL_CICLO > 400`) para a revisão ser sugerida — mantida no backend como defesa em profundidade mesmo já validada na origem

### Limites e ordenação

- Máximo de **5 sugestões** por tipo por propagandista por ciclo
- Entrada ordenada por `soma_pontuacao DESC`
- Revisão ordenada por `posicao_ranking DESC` (pior posição primeiro)
- Recomendações recorrentes incrementam `qtd_vezes_recomendado` (sem duplicar)

### Identidade do propagandista

- Backend resolve matrícula/setor a partir do e-mail (`resolver_email_autenticado()`, ver seção Autenticação — origem do e-mail depende de `AUTH_REQUIRE_JWT`)
- Propagandista **nunca informa matrícula manualmente**
- `tb_propagandistas` **nunca é exposta** nas respostas da API

### Status de contexto

| Status | Significado | Impacto |
|---|---|---|
| `SETOR_RESOLVIDO` | 1 cadastro ativo encontrado | Prossegue |
| `PROPAGANDISTA_NAO_ENCONTRADO` | 0 cadastros ativos | Bloqueia com 403 |
| `IDENTIDADE_AMBIGUA` | 2+ cadastros ativos | Bloqueia com 403 |

### Status de recomendação

| Status | Quando ocorre |
|---|---|
| `PENDENTE` | Gerada, aguardando ação |
| `APLICADA` | Médico entrou/saiu do painel (detectado por `atualizar_status.py`) |
| `DESCONSIDERADA` | Rep ou GD optou por ignorar (com motivo registrado) |
| `EXPIRADA` | Ciclo encerrado sem ação |

---

## Endpoints da API

> `email` via query string só é aceito com `AUTH_REQUIRE_JWT=false` (padrão
> local). Com `AUTH_REQUIRE_JWT=true`, todos os endpoints abaixo exigem
> header `Authorization: Bearer <token>` e ignoram `email` — ver seção
> Autenticação.

### Autenticação

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/auth/contexto?email={email}` | Resolve identidade do propagandista |

### Consultas analíticas (NL-to-SQL)

| Método | Endpoint | Descrição |
|---|---|---|
| POST | `/prescricoes/consultar` | Pergunta em linguagem natural → resposta sintetizada |

**Body:**
```json
{
  "pergunta": "Quais médicos prescreveram mais Venlaxin no meu setor?",
  "email": "ana.silva@ache.com.br",
  "periodo": null,
  "perfil_tecnico": false
}
```

### Recomendações

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/recomendacoes/entrada?email={email}&ciclo={ciclo}` | Lista ENTRADA_PAINEL PENDENTE (≤ 5) |
| GET | `/recomendacoes/revisao?email={email}&ciclo={ciclo}` | Lista REVISAO_PAINEL PENDENTE (≤ 5) |
| POST | `/recomendacoes/{id_recomendacao}/desconsiderar?email={email}` | Desconsiderar recomendação com motivo (task 161830/163626) |

> `ciclo` é opcional e cai no default `CICLO_REFERENCIA` (`config.py`/`.env`),
> hoje **desatualizado** (`202507`) em relação ao ciclo real mais recente na
> fonte Databricks (`202607`). Sem `?ciclo=` explícito, chamadas contra
> `DATA_SOURCE=databricks` retornam lista vazia mesmo havendo dado
> disponível — passe o ciclo explicitamente até o default ser corrigido.
>
> O antigo `POST /recomendacoes/desconsiderar` (ID no corpo) esteve
> **congelado por decisão do George** desde 2026-07-23, pendente de decisão
> de canal (REST vs. conversacional). A especificação 161830 (George)
> resolveu essa pendência optando pelo endpoint REST controlado da task
> 163626 — o endpoint antigo foi **descontinuado** e substituído por
> `POST /recomendacoes/{id_recomendacao}/desconsiderar` (ID no path), que
> roda hoje contra o schema local (`tb_recomendacoes_painel`); migração para
> `tb_recomendacoes_painel_historico` real depende de 5 colunas novas ainda
> não criadas pelo Hugo. Ver
> `docs/context/decisions-log.md`.

**Body de `POST /recomendacoes/{id_recomendacao}/desconsiderar`** (ID vem do
path, não do corpo; matrícula sempre via `resolver_contexto()`, nunca aceita
do cliente; `data_desconsideracao` sempre gerada pelo backend):
```json
{
  "motivo": "MEDICO_APOSENTADO",
  "motivo_outros_texto": null,
  "bloquear_novas_recomendacoes": true
}
```
`motivo` é uma das constantes em `MOTIVOS_DESCONSIDERACAO`
(`schemas/recomendacoes.py`): `MEDICO_NAO_ATUA_MAIS`, `MEDICO_APOSENTADO`,
`MEDICO_FALECIDO`, `SEM_INTERESSE_COMERCIAL`, `OUTROS` (exige
`motivo_outros_texto`, persistido como `"OUTROS: <texto>"`).

### Gerencial (exclusivo GD)

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/gerencial/indicadores?gd_email={email}&ciclo={ciclo}` | Métricas consolidadas do escopo |
| GET | `/gerencial/propagandistas?gd_email={email}&ciclo={ciclo}` | Lista reps com contagens |
| GET | `/gerencial/recomendacoes?gd_email={email}&matricula={mat}&ciclo={ciclo}` | Recomendações de um rep com filtros |

> Todos os endpoints gerenciais são somente leitura (GET). Acesso fora do escopo retorna 403.

### Erros padronizados

| Código | Status HTTP | Significado |
|---|---|---|
| `GENIE_TIMEOUT` | 504 | LLM não respondeu no tempo limite |
| `GENIE_ERROR` | 502 | Erro na API do LLM ou execução do SQL |
| `EMPTY_RESPONSE` | 502 | LLM retornou resposta vazia |
| `CONTEXT_ERROR` | 422 | Erro de contexto (intent_rules.json inválido etc.) |

---

## Banco de Dados

### Tabelas principais (schema local — `DATA_SOURCE=local`)

| Tabela | Descrição |
|---|---|
| `tb_propagandistas` | Cadastro de reps (nunca exposta via API) |
| `tb_ranking_medicos` | Ranking mensal por setor/linha/ciclo |
| `tb_painel_medico` | Painel atual de médicos por setor/ciclo |
| `tb_prescricoes_geral` | Prescrições capturadas de fontes externas (IQVIA/Close-Up) |
| `tb_recomendacoes_painel` | Sugestões geradas pelo motor — **estado mais recente sobrescrito** (não histórico) |
| `tb_visitacao_medica` | Registro de visitas efetivas e tentativas |
| `tb_hierarquia_gd` | Relacionamento GD → propagandistas subordinados |

> No schema Databricks real (`DATA_SOURCE=databricks`), `tb_recomendacoes_painel`
> é substituída por `tb_recomendacoes_painel_historico` — histórico por
> ciclo (não sobrescrito), 15 colunas, nomes de coluna diferentes (ex.:
> `RANKING_POSICAO_CICLO`, `MOTIVO_RECOMENDACAO`, `QTD_MEDICOS_PAINEL_CICLO`).
> `tb_propagandistas` também difere (sem `cod_linha`/`ativo`, com campos
> `GD_*` embutidos). Mapeamento completo coluna a coluna em
> `docs/context/databricks-schema-real.md`. Hoje `/recomendacoes/entrada`,
> `/recomendacoes/revisao` e `/recomendacoes/{id}/desconsiderar` já
> alternam por fonte via `_COLUNAS_POR_FONTE` — o mapeamento Databricks do
> desconsiderar fica dormente até o Hugo criar as 5 colunas novas na tabela
> real. `gerencial.py` ainda assume só o schema local.

### Views gerenciais

| View | Descrição |
|---|---|
| `vw_hierarquia_gd` | GD com todos os propagandistas e setores vinculados |
| `vw_recomendacoes_gerencial` | Join completo recomendações + propagandista + GD |
| `vw_metricas_gerencial` | Taxa de aceite por GD/ciclo/tipo |
| `vw_motivos_desconsideracao` | Principais motivos agrupados por GD e ciclo |

### Dados de simulação (local)

- **3 setores:** SP_INTERIOR, RJ_CAPITAL, MG_SUL
- **2 linhas:** CARDIO, SNC
- **10 propagandistas** (1 inativo para teste)
- **3 GDs:** GD001→SP_INTERIOR, GD002→RJ_CAPITAL, GD003→MG_SUL
- **150 médicos por setor/linha** no ranking (900 total)
- **80 médicos por setor/linha** no painel (480 total)
- **4 cenários obrigatórios** garantidos nos dados: C1 (fora do painel), C2 (no painel), C3 (abaixo do corte no painel), C4 (sem visita > 5 meses)

---

## Camada LLM / Genie Local

O módulo `genie/nl_to_sql.py` simula o comportamento do Databricks Genie localmente.

### Classificação de intent

Configurada em `genie/intent_rules.json` — **único arquivo a alterar** após alinhamento de critérios com Pavan:

- **OPERACIONAL** — pergunta sobre o setor do propagandista → aplica `WHERE setor = '{setor}'`
- **TOTAL_GERAL** — pergunta consolidada nacional → sem filtro de setor

### Período

- Período explícito na pergunta → detectado por regex e aplicado ao SQL
- Sem período → YTD implícito (`data >= {ano}-01-01`)

### Providers disponíveis (via `LLM_PROVIDER` no `.env`)

| Provider | Modelo padrão | Variável de chave |
|---|---|---|
| `claude` | claude-sonnet-4-6 | `ANTHROPIC_API_KEY` |
| `openai` | gpt-4o | `OPENAI_API_KEY` |
| `gemini` | gemini-1.5-pro | `GOOGLE_API_KEY` |
| `groq` | llama-3.3-70b-versatile | `GROQ_API_KEY` |

---

## Jobs de Ciclo

### `gerar_recomendacoes.py`

Gera sugestões para todos os propagandistas ativos. Upsert: insere novo ou incrementa `qtd_vezes_recomendado`.

```bash
python -m backend.app.jobs.gerar_recomendacoes --ciclo 202507 --dry-run
```

### `atualizar_status.py`

Roda diariamente. Detecta médicos que entraram/saíram do painel e atualiza status para `APLICADA`.

```bash
python -m backend.app.jobs.atualizar_status --ciclo 202507
```

### `novo_ciclo.py`

Roda no último dia útil do mês. Expira `PENDENTE` do ciclo atual e gera recomendações para o próximo.

```bash
python -m backend.app.jobs.novo_ciclo --ciclo-atual 202507 --ciclo-novo 202508
```

---

## Autenticação

`backend/app/auth/jwt_auth.py:resolver_email_autenticado()` é o ponto único de resolução de identidade — usado por `auth/context.py`, `routers/prescricoes.py` e `routers/recomendacoes.py`. O comportamento é controlado pela flag `AUTH_REQUIRE_JWT` (`.env`):

### `AUTH_REQUIRE_JWT=false` (padrão local, dev)

Aceita o e-mail cru vindo de query string ou body — nenhum token é validado. É o modo usado nos exemplos deste README e nos testes mockados.

### `AUTH_REQUIRE_JWT=true` (produção / homologação)

Exige header `Authorization: Bearer <token>`. O token é validado (assinatura, audience, issuer) via JWKS do Auth0/Entra ID (`PyJWKClient`, com cache por domínio), e o e-mail é extraído da claim configurada em `AUTH_EMAIL_CLAIM` (padrão `preferred_username`). Nesse modo, `email` via query/body é **ignorado** — só o token é fonte de verdade. Em qualquer modo, uma vez resolvido, o e-mail é usado para consultar `tb_propagandistas` (local ou Databricks, conforme `DATA_SOURCE`) e obter matrícula/setor.

### Claim de e-mail no Entra ID — pendente

O claim correto (`preferred_username` vs. `upn`) ainda **não foi confirmado com Flávio**. `AUTH_EMAIL_CLAIM` é configurável via `.env` justamente para não exigir mudança de código quando a resposta chegar.

---

## Como Rodar Localmente

### Pré-requisitos

- Docker + Docker Compose
- Python 3.10+
- WSL Ubuntu 22.04 (recomendado) ou Linux/macOS

### 1. Clonar e configurar

```bash
git clone https://github.com/barbaragodoy/renova-ai.git
cd renova-ai
cp .env.example .env
# Editar .env com as chaves de API e configurações
```

### 2. Subir o banco

```bash
docker compose up -d
```

### 3. Criar e popular o banco

```bash
# Dentro do container PostgreSQL:
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/01_create_tables.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/02_populate_propagandistas.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/03_populate_ranking.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/04_populate_painel.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/05_populate_prescricoes.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/06_populate_hierarquia_gd.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/07_simulate_recomendacoes.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/08_create_views_gerencial.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/09_migrar_colunas_desconsideracao.sql
docker exec -i renovai-postgres psql -U renovai -d renovai < data/scripts/10_popular_cenarios_desconsiderar.sql
```

### 4. Criar ambiente Python e instalar dependências

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Inclui os SDKs de todos os providers LLM (Claude/OpenAI/Gemini/Groq), o
> stack de conexão Databricks (`databricks-sql-connector`,
> `databricks-sqlalchemy`, `databricks-sdk`, usados só quando
> `DATA_SOURCE=databricks`) e `PyJWT` (validação de token quando
> `AUTH_REQUIRE_JWT=true`).

### 5. Validar dados

```bash
python data/scripts/validate_tables.py
# Todos os 4 cenários obrigatórios devem passar
```

### 6. Gerar recomendações do ciclo

```bash
python -m backend.app.jobs.gerar_recomendacoes --ciclo 202507
```

### 7. Rodar a API

```bash
uvicorn backend.app.main:app --reload
# API disponível em http://localhost:8000
# Docs em http://localhost:8000/docs
```

---

## Testes

```bash
source .venv/bin/activate
pytest backend/app/tests/ -v
```

### Suítes disponíveis

| Arquivo | Cenários | Tipo |
|---|---|---|
| `test_context.py` | 4 | Unitário (mock; força `DATA_SOURCE=local`) |
| `test_context_integration.py` | 6 | Integração contra Databricks real — `skipif DATA_SOURCE != databricks` |
| `test_jwt_auth.py` | 7 | Unitário (mock) — `AUTH_REQUIRE_JWT` true/false |
| `test_prescricoes.py` | 6 | Integração (mock LLM) |
| `test_recomendacoes.py` | 4 | Integração (mock banco) |
| `test_recomendacoes_integration.py` | — | Integração contra Databricks real — `skipif DATA_SOURCE != databricks` |
| `test_desconsiderar.py` | 5 | Integração (mock banco) |
| `test_ciclo.py` | 5 | Unitário (mock banco) |
| `test_gerencial.py` | 6 | Integração (mock banco) |
| `test_cenarios_completos.py` | 10 | E2E mockado |
| `test_golden_set.py` | 22 + relatório | Golden set NL |

O `test_golden_set.py` imprime ao final a taxa de acerto por categoria (OPERACIONAL / TOTAL_GERAL / FORA_ESCOPO). Os testes `*_integration.py` só executam de fato com `DATA_SOURCE=databricks` configurado no `.env` — caso contrário aparecem como `SKIPPED`.

---

## Documentação Adicional

| Documento | Conteúdo |
|---|---|
| `docs/cenarios/matriz_teste.md` | 37 cenários em 6 grupos com critérios de aceite |
| `docs/cenarios/golden_set.json` | 22 perguntas categorizadas para validação do Genie local |
| `docs/promocao_producao.md` | Checklist de promoção local → produção com responsáveis |
| `docs/context/decisions-log.md` | Decisões de negócio/arquitetura datadas (permissões do SP, warehouse, domínios de e-mail, congelamento do desconsiderar, pendências abertas) |
| `docs/context/databricks-schema-real.md` | Mapeamento completo de colunas entre o schema local (Postgres) e o schema real do Databricks |
| `docs/context/known-issues.md` | Bugs técnicos na fonte real, com status RESOLVIDO/ABERTO |
| `docs/context/arquitetura.md` | Inventário completo do implementado, tasks por pessoa e ambiente de desenvolvimento |
| `CLAUDE.md` | Contexto completo do projeto para sessões com Claude Code (índice de leitura sob demanda) |

---

## Próximas Etapas

As etapas abaixo são necessárias para o projeto estar **funcional em produção**.

### 1. Implementar `GenieProvider` (Databricks Genie, para o chat NL→SQL)

O único provider de LLM ainda não implementado — usado hoje: Claude, OpenAI, Gemini e Groq. **Não confundir com `DATA_SOURCE=databricks`**, que já funciona: essa flag só troca a fonte de dados (SQL direto via SP OAuth M2M) usada por `/recomendacoes/*` e `/auth/contexto`; o motor de chat de `/prescricoes/consultar` (`genie/nl_to_sql.py`) continua chamando um dos 4 providers de LLM acima, nunca o Databricks Genie de fato.

```
backend/app/llm/genie_provider.py
```

- Chamar Databricks Genie via REST API ou SDK (`databricks-sdk`)
- Registrar `genie` como opção válida no factory `get_llm_provider()`
- Testar com o SQL Warehouse da POC (`783ae0217086255c`)
- **Responsável:** Colin

### 2. Frontend React

Interface que os propagandistas e GDs usarão.

Telas necessárias:
- Login via Auth0 / Entra ID
- Lista de recomendações de entrada (com ação de desconsiderar)
- Lista de recomendações de revisão (com ação de desconsiderar)
- Chat analítico (pergunta → resposta NL)
- Painel gerencial para GDs (indicadores + drill-down por propagandista)

Contratos já definidos nos schemas Pydantic em `backend/app/schemas/`.

### 3. Confirmar `tb_hierarquia_gd` em produção (HUGO-08)

A tabela existe localmente. Confirmar com **Caio** se o equivalente existe no Unity Catalog de produção ou se precisa ser criado/mapeado.

### 4. Alinhar `intent_rules.json` com Pavan

Após revisão dos critérios de classificação de perguntas com **Pavan**, atualizar:

```
backend/app/genie/intent_rules.json
```

Este é o **único arquivo** a mudar para ajustar o comportamento do classificador de intent.

### 5. Confirmar claim JWT do Entra ID

Verificar com **Flávio** qual campo do token Entra ID contém o e-mail corporativo (`preferred_username` vs `upn`) e atualizar `AUTH_EMAIL_CLAIM` em `backend/app/auth/jwt_auth.py`/`.env` se necessário — hoje configurável, sem mudança de código prevista.

### 6. Configurar Azure Key Vault

Migrar todas as variáveis do `.env` para Key Vault com Managed Identity — sem nenhuma secret em código ou em variável de ambiente plain text no container.

- **Responsável:** Flávio

### 7. Configurar pipeline CI/CD

- Pipeline Azure DevOps ou GitHub Actions
- Executar `pytest` antes de qualquer deploy
- Build e push da imagem Docker para Azure Container Registry
- Deploy automático para Azure Container Apps

### 8. Aplicar views gerenciais no Unity Catalog

Executar `data/scripts/08_create_views_gerencial.sql` adaptado para o schema de produção.

- **Responsável:** Caio

### 9. Pendências abertas de curto prazo (não bloqueiam código, bloqueiam homologação)

Levantadas durante a migração de `/recomendacoes/*` para o Databricks real (ver `docs/context/known-issues.md`):

- Atualizar o default `CICLO_REFERENCIA` (`config.py`/`.env`), hoje `202507`, desatualizado em relação ao ciclo real mais recente na fonte (`202607`) — sem `?ciclo=` explícito, os endpoints retornam lista vazia mesmo com dado disponível.
- Confirmar com **George/Bruno** se a ampliação do critério de `REVISAO_PAINEL` (incluir médicos com ranking ≤ 400 sem visita há 5+ meses) é regra de negócio intencional.
- Solicitar ao **Hugo** as 5 colunas novas em `tb_recomendacoes_painel_historico` (`MOTIVO_DESCONSIDERACAO`, `DESCONSIDERADO_POR`, `DATA_DESCONSIDERACAO`, `QTD_VEZES_DESCONSIDERADO`, `BLOQUEAR_NOVAS_RECOMENDACOES`) para migrar `/recomendacoes/{id}/desconsiderar` para o Databricks real — mesmo processo já usado em BARBARA-04/05.
- Confirmar se `MOTIVO_RECOMENDACAO` deve bloquear a mesma recomendação de ser re-sugerida no ciclo seguinte, ou se é sempre re-sugerida — aberto com George, impacta `gerar_recomendacoes.py`.

### 10. Executar `gerar_recomendacoes` para o ciclo vigente em produção

Após validação de todos os itens acima, rodar o job para o ciclo atual e validar as recomendações com dados reais. (A leitura via `DATA_SOURCE=databricks` já foi validada ponta a ponta — falta o deploy em Azure Container Apps em si, itens 6–8.)

### 11. Piloto com usuários reais

- Validar golden set contra o Genie de produção
- Validar taxa de acerto dos endpoints com propagandistas e GDs piloto
- Coletar feedback e ajustar `intent_rules.json` se necessário

---

## Mapeamento Local → Produção

| Item | Local (`DATA_SOURCE=local`) | Local apontando pro real (`DATA_SOURCE=databricks`) | Produção (deploy Azure) |
|---|---|---|---|
| Banco | PostgreSQL 15 (Docker) | Databricks SQL Warehouse real (`acheinfo_dev.renovai`), via OAuth M2M | Databricks SQL Warehouse + Unity Catalog |
| LLM (chat NL→SQL) | Claude / OpenAI / Gemini / Groq | mesmo (LLM não muda com `DATA_SOURCE`) | Databricks Genie (`GenieProvider`, ainda não implementado) |
| Auth | Auth0 / e-mail cru (`AUTH_REQUIRE_JWT=false`) | idem | Microsoft Entra ID / SSO |
| Secrets | `.env` | `.env` | Azure Key Vault |
| Deploy | `uvicorn` manual | `uvicorn` manual | Azure Container Apps |
| Corte de ranking | ≤ 100 | ≤ 400 (por setor) | ≤ 400 (por setor) |

> **O código de negócio não muda entre as três colunas.** A troca é só
> `DATA_SOURCE` (fonte de dados) e `LLM_PROVIDER`/`AUTH_REQUIRE_JWT`/secrets —
> `DATA_SOURCE=databricks` já é hoje uma forma de rodar contra o dado real de
> produção sem depender do deploy em Azure.

---

## Responsáveis

| Papel | Pessoa | Área |
|---|---|---|
| Dados na origem (correções em `tb_recomendacoes_painel_historico`, pipeline) | Hugo | Dados |
| Decisões de negócio/arquitetura, orquestração do projeto | George | Orquestração / PM |
| Dados e Unity Catalog | Caio | Dados |
| Infra Azure, Key Vault, Entra ID | Flávio | Infraestrutura |
| Backend FastAPI, GenieProvider | Colin | Backend IA |
| Critérios de intent e ranking | Pavan | Negócio |

> Nesta simulação local, Bárbara cobre todos os papéis de implementação
> (dados/Hugo, orquestração/George, backend de IA/Bárbara) — as pessoas
> acima são os stakeholders reais do projeto Aché, referenciados nas
> decisões registradas em `docs/context/decisions-log.md`.

---

## Licença

Projeto interno Aché Farma — uso restrito.
