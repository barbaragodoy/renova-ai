# RenovAI — Motor de Recomendação de Painel Médico

> Simulação local do PED 2.0 / RenovAI (Aché Farma).  
> Motor de inteligência artificial para recomendação do painel médico de propagandistas farmacêuticos.

---

## Índice

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Estrutura de Pastas](#estrutura-de-pastas)
- [Stack Tecnológica](#stack-tecnológica)
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

O propagandista recebe no máximo **5 sugestões por tipo** por ciclo, ordenadas por pontuação. Pode aceitar (ação tomada → `APLICADA`), desconsiderar com justificativa (`DESCONSIDERADA`) ou deixar expirar no fim do ciclo (`EXPIRADA`).

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
│  │   ClaudeProvider │ OpenAIProvider │ GeminiProvider        │  │
│  │   (get_llm_provider() — selecionado via LLM_PROVIDER)     │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ SQLAlchemy
┌──────────────────────────────▼──────────────────────────────────┐
│                  PostgreSQL 15 (Docker)                           │
│                                                                   │
│  tb_propagandistas       tb_ranking_medicos                       │
│  tb_painel_medico        tb_prescricoes_geral                     │
│  tb_recomendacoes_painel tb_visitacao_medica                     │
│  tb_hierarquia_gd                                                 │
└─────────────────────────────────────────────────────────────────┘

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
│       │   └── context.py             # resolver_contexto() + GET /auth/contexto
│       ├── genie/
│       │   ├── intent_rules.json      # ⚠️ ÚNICO arquivo a mudar após alinhamento com Pavan
│       │   └── nl_to_sql.py           # Fluxo completo NL→SQL→NL
│       ├── llm/
│       │   ├── adapter.py             # Interface abstrata LLMAdapter + factory
│       │   ├── claude_provider.py     # Anthropic SDK
│       │   ├── openai_provider.py     # OpenAI SDK
│       │   └── gemini_provider.py     # Google Generative AI SDK
│       ├── routers/
│       │   ├── prescricoes.py         # POST /prescricoes/consultar
│       │   ├── recomendacoes.py       # GET /entrada, /revisao | POST /desconsiderar
│       │   └── gerencial.py           # GET /indicadores, /propagandistas, /recomendacoes
│       ├── schemas/
│       │   ├── recomendacoes.py       # Contrato frontend ↔ backend (recomendações)
│       │   └── gerencial.py           # Contrato frontend ↔ backend (visão GD)
│       ├── jobs/
│       │   ├── gerar_recomendacoes.py # Gera sugestões por ciclo
│       │   ├── atualizar_status.py    # Atualiza PENDENTE → APLICADA diariamente
│       │   └── novo_ciclo.py          # Expira ciclo anterior + abre novo ciclo
│       └── tests/
│           ├── test_context.py
│           ├── test_prescricoes.py
│           ├── test_recomendacoes.py
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
│   └── promocao_producao.md           # Checklist local → produção Aché
├── docker-compose.yml                 # PostgreSQL 15 + pgAdmin
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
| LLM | Anthropic Claude / OpenAI GPT-4o / Google Gemini (selecionável via `.env`) |
| Auth | Auth0 free tier (simula Entra ID) |
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

## Regras de Negócio

### Cortes do ranking

| Ambiente | Entrada | Revisão |
|---|---|---|
| Local (simulado) | posicao_ranking ≤ 100 | posicao_ranking > 100 |
| Produção (Aché) | posicao_ranking ≤ 400 | posicao_ranking > 400 |

### Critérios de revisão

- **ABAIXO_CORTE** — médico no painel com ranking acima do corte
- **SEM_VISITA_5_MESES** — médico no painel sem visita efetiva nos últimos 150 dias

### Limites e ordenação

- Máximo de **5 sugestões** por tipo por propagandista por ciclo
- Entrada ordenada por `soma_pontuacao DESC`
- Revisão ordenada por `posicao_ranking DESC` (pior posição primeiro)
- Recomendações recorrentes incrementam `qtd_vezes_recomendado` (sem duplicar)

### Identidade do propagandista

- Backend resolve matrícula/setor a partir do e-mail do token JWT
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
| GET | `/recomendacoes/entrada?email={email}` | Lista ENTRADA_PAINEL PENDENTE (≤ 5) |
| GET | `/recomendacoes/revisao?email={email}` | Lista REVISAO_PAINEL PENDENTE (≤ 5) |
| POST | `/recomendacoes/desconsiderar?email={email}` | Desconsiderar recomendação com motivo |

**Body de desconsiderar:**
```json
{
  "id_recomendacao": "uuid",
  "rep_matricula": "REP001",
  "motivo": "Médico fora da minha área de atuação.",
  "timestamp": "2026-07-10T10:00:00"
}
```

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

### Tabelas principais

| Tabela | Descrição |
|---|---|
| `tb_propagandistas` | Cadastro de reps (nunca exposta via API) |
| `tb_ranking_medicos` | Ranking mensal por setor/linha/ciclo |
| `tb_painel_medico` | Painel atual de médicos por setor/ciclo |
| `tb_prescricoes_geral` | Prescrições capturadas de fontes externas (IQVIA/Close-Up) |
| `tb_recomendacoes_painel` | Sugestões geradas pelo motor, com histórico completo |
| `tb_visitacao_medica` | Registro de visitas efetivas e tentativas |
| `tb_hierarquia_gd` | Relacionamento GD → propagandistas subordinados |

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

### Local (Auth0)

O token JWT do Auth0 contém o campo `email`. O endpoint `GET /auth/contexto?email={email}` resolve a identidade do propagandista consultando `tb_propagandistas`.

### Produção (Entra ID)

O claim de e-mail no JWT do Entra ID pode ser `preferred_username` ou `upn` — a confirmar com Flávio antes do go-live.

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
```

### 4. Criar ambiente Python e instalar dependências

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn sqlalchemy psycopg2-binary pydantic pydantic-settings \
            anthropic openai google-generativeai pytest httpx
```

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
| `test_context.py` | 3 | Unitário (mock) |
| `test_prescricoes.py` | 6 | Integração (mock LLM) |
| `test_recomendacoes.py` | 4 | Integração (mock banco) |
| `test_desconsiderar.py` | 5 | Integração (mock banco) |
| `test_ciclo.py` | 5 | Unitário (mock banco) |
| `test_gerencial.py` | 6 | Integração (mock banco) |
| `test_cenarios_completos.py` | 10 | E2E mockado |
| `test_golden_set.py` | 22 + relatório | Golden set NL |

O `test_golden_set.py` imprime ao final a taxa de acerto por categoria (OPERACIONAL / TOTAL_GERAL / FORA_ESCOPO).

---

## Documentação Adicional

| Documento | Conteúdo |
|---|---|
| `docs/cenarios/matriz_teste.md` | 37 cenários em 6 grupos com critérios de aceite |
| `docs/cenarios/golden_set.json` | 22 perguntas categorizadas para validação do Genie local |
| `docs/promocao_producao.md` | Checklist de promoção local → produção com responsáveis |
| `CLAUDE.md` | Contexto completo do projeto para sessões com Claude Code |

---

## Próximas Etapas

As etapas abaixo são necessárias para o projeto estar **funcional em produção**.

### 1. Implementar `GeniProvider` (Databricks SDK)

O único provider ainda não implementado. Será usado em produção no lugar de Claude/OpenAI/Gemini.

```
backend/app/llm/genie_provider.py
```

- Chamar Databricks Genie via REST API ou SDK (`databricks-sdk`)
- Registrar `genie` como opção válida no factory `get_llm_provider()`
- Testar com o SQL Warehouse 2XS da POC
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

Verificar com **Flávio** qual campo do token Entra ID contém o e-mail corporativo (`preferred_username` vs `upn`) e atualizar `backend/app/auth/context.py` se necessário.

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

### 9. Executar `gerar_recomendacoes` para o ciclo vigente em produção

Após validação de todos os itens acima, rodar o job para o ciclo atual e validar as recomendações com dados reais.

### 10. Piloto com usuários reais

- Validar golden set contra o Genie de produção
- Validar taxa de acerto dos endpoints com propagandistas e GDs piloto
- Coletar feedback e ajustar `intent_rules.json` se necessário

---

## Mapeamento Local → Produção

| Item | Local | Produção |
|---|---|---|
| Banco | PostgreSQL 15 (Docker) | Databricks SQL Warehouse + Unity Catalog |
| LLM | Claude / OpenAI / Gemini | Databricks Genie |
| Auth | Auth0 | Microsoft Entra ID |
| Secrets | `.env` | Azure Key Vault |
| Deploy | `uvicorn` manual | Azure Container Apps |
| Corte de ranking | ≤ 100 | ≤ 400 |

> **O código não muda. Apenas variáveis de ambiente e providers.**

---

## Responsáveis

| Papel | Pessoa | Área |
|---|---|---|
| Dados e Unity Catalog | Caio | Dados |
| Infra Azure, Key Vault, Entra ID | Flávio | Infraestrutura |
| Backend FastAPI, GeniProvider | Colin | Backend IA |
| Critérios de intent e ranking | Pavan | Negócio |

---

## Licença

Projeto interno Aché Farma — uso restrito.
