# RenovAI — Contexto do Projeto Local

## O que é esse projeto
Simulação local do PED 2.0 / RenovAI (Aché Farma). Motor de recomendação 
do painel médico para propagandistas. Eu executo todos os papéis: dados (Hugo), 
orquestração (George) e backend de IA (Bárbara).

## Stack local
- Banco: PostgreSQL via Docker
- Backend: Python / FastAPI
- LLM: provider configurável via LLM_PROVIDER no .env (claude, openai, gemini, groq)
- Substituto do Genie: LangChain + SQLAlchemy + LLM adapter
- Autenticação: Auth0 free tier (simula Entra ID)
- Frontend: React localhost (referência)

## Stack de produção (Aché)
- Banco: Azure Databricks / Unity Catalog / Delta
- Backend: Python / FastAPI em container no Azure
- LLM: Databricks Genie via Service Principal
- Autenticação: Microsoft Entra ID / SSO

## Regras de negócio confirmadas
- Corte de entrada: posição no ranking <= 400 (local: <= 100)
- Corte de revisão: posição no ranking > 400 (local: > 100)
- Limite de sugestões: 5 por retorno, separados por tipo
- Priorização: pontuação do ranking
- Médico sem visita há mais de 5 meses: critério adicional de revisão
- Propagandista não informa matrícula manualmente
- Backend nunca expõe tb_propagandistas para o usuário
- Motivos de revisão: ABAIXO_CORTE ou SEM_VISITA_5_MESES

## Status de resolução de contexto
- SETOR_RESOLVIDO: avança
- PROPAGANDISTA_NAO_ENCONTRADO: bloqueia
- IDENTIDADE_AMBIGUA: bloqueia

## Erros padronizados do Genie/LLM
- GENIE_TIMEOUT
- GENIE_ERROR
- EMPTY_RESPONSE
- CONTEXT_ERROR

## Permissões confirmadas
- SP sp-renovai-genie-api-poc tem SELECT sobre todas as tabelas
  atualmente consultadas pelo Genie Space, incluindo tb_propagandistas
  — confirmado por George em 2026-07-15.
- Atenção: toda nova tabela adicionada ao escopo do Genie precisa de
  confirmação de grant separada — não assumir herança automática.

### Conexão com Databricks real — CONFIRMADO
- SP sp-renovai-genie-api-poc autenticado com sucesso via OAuth M2M
  (client_credentials), testado em 2026-07-16.
- Warehouse correto e testado: `783ae0217086255c` (`sql-warehouse-renovai-dev`
  antigo, `e0bbf85808a7e35b`, **NÃO deve ser usado** — SP não tem CAN USE nele).
  Isso corrige a entrada anterior deste documento que apontava o nome antigo
  como confirmado — ver nota em "Pontos simulados" sobre `DATABRICKS_WAREHOUSE_ID`.
- SELECT confirmado sobre `acheinfo_dev.renovai.tb_propagandistas` via teste
  direto com token do SP (retornou 2156 registros).
- `current_user()` do SP retorna o ClientID (`1831a9d4-97cd-4b56-8243-83a777dde138`),
  confirmando que a identidade usada é do SP, não de sessão de usuário humano.

### Domínio de e-mail — CONFIRMADO
- ache.com.br e biosintetica.com.br são domínios válidos, confirmado por
  George (mesmo grupo econômico). Validação de domínio deve ser configurável,
  não hardcoded (ver `DOMINIOS_EMAIL_ACEITOS` em `config.py`, detalhado em
  "Pontos simulados" abaixo).

## Bug real encontrado e corrigido — 2026-07-16
- 14 dos 2156 registros reais em `acheinfo_dev.renovai.tb_propagandistas` têm
  `REP_EMAIL` gravado com letras maiúsculas (ex.: `SUELEN.BRITO@ACHE.COM.BR`).
  `resolver_contexto()` fazia match exato (`=`), então um e-mail vindo em
  minúsculas do Auth0/Entra ID (o normal) retornava incorretamente
  `PROPAGANDISTA_NAO_ENCONTRADO` para esses 14 propagandistas.
- **Corrigido** em `auth/context.py`: comparação agora via
  `WHERE LOWER(rep_email) = LOWER(:email)`. Confirmado que isso não introduz
  falsos `IDENTIDADE_AMBIGUA`: 0 colisões via `GROUP BY LOWER(rep_email)` nos
  2156 registros reais. Coberto por teste de regressão em
  `test_context_integration.py::test_setor_resolvido_com_email_gravado_em_maiusculo`
  (busca dinamicamente um registro com maiúscula, não fixa a matrícula).
- Não é um caso de IDENTIDADE_AMBIGUA: essa regra é para múltiplas linhas
  distintas colidindo no mesmo e-mail (duplicidade de cadastro); aqui é uma
  única linha com inconsistência de caixa na origem — comparação
  case-insensitive é o padrão para e-mails, não uma ambiguidade de identidade.

## Pontos simulados (não confirmados em produção)
- Critério de desempate de sugestões: a definir com Caio
- Perfis autorizados além do GD: a definir
- Regra de exibição de justificativa de recusa para GD: a definir (implementado: GD vê motivo_desconsideracao)
- Fonte oficial da hierarquia GD: a confirmar com Hugo (HUGO-08). Atualização: o schema real de
  `acheinfo_dev.renovai.tb_propagandistas` (verificado 2026-07 no workspace de DEV) já traz
  GD_MATRICULA/GD_NOME/GD_EMAIL/GD_LOGIN (e GR_*/GN_*) embutidos por linha de SETOR/REP — a
  hierarquia pode não precisar de uma tabela separada equivalente a `tb_hierarquia_gd` em produção.
  Ainda não resolvido: como isso afeta `routers/gerencial.py`, que hoje faz JOIN com
  `tb_hierarquia_gd` local (fora do escopo desta validação de contexto).
- Claim JWT do Entra ID com e-mail: preferred_username ou upn — confirmar com Flávio
- GeniProvider (Databricks SDK): não implementado ainda — ver docs/promocao_producao.md
- Domínio de e-mail biosintetica.com.br: **CONFIRMADO** por George (PM Simbiox) — mesmo grupo
  econômico do ache.com.br, dentro do escopo do projeto. Implementado como lista configurável
  (`DOMINIOS_EMAIL_ACEITOS` em `config.py`), não hardcoded.
- Coluna de status ativo/inativo em tb_propagandistas: **CONFIRMADO que NÃO EXISTE** no schema real
  (verificação técnica direta no Databricks DEV, 2026-07). Registros "VAGO" já são removidos na
  origem pelo pipeline de ingestão. Decisão adotada: ausência de linha para o e-mail já é o proxy
  de "propagandista não encontrado/inativo" — `resolver_contexto()` não filtra mais por `ativo`.
- IDENTIDADE_AMBIGUA: lógica defensiva mantida no código, mas **não validável com dado real hoje**
  (2156/2156 e-mails únicos confirmado em `acheinfo_dev.renovai.tb_propagandistas`). Coberta apenas
  por teste unitário com mock/massa sintética (`test_context.py::test_identidade_ambigua`).
- Coluna `cod_linha` (linha de produto) em tb_propagandistas: **CONFIRMADO que NÃO EXISTE** no schema
  real. Removida de `resolver_contexto()`/`ContextoResponse`. Ainda não resolvido: `jobs/gerar_recomendacoes.py`,
  `routers/gerencial.py` e `schemas/gerencial.py` continuam assumindo essa coluna em tb_propagandistas —
  precisa de alinhamento com Hugo sobre a fonte real dessa dimensão antes da promoção a produção.
- SQL Warehouse de referência: **CORRIGIDO em 2026-07-16** — o ID correto e testado (SP tem CAN USE)
  é `783ae0217086255c`. O nome `sql-warehouse-renovai-dev` (ID `e0bbf85808a7e35b`), registrado
  anteriormente neste documento como confirmado, está **incorreto** — o SP não tem CAN USE nele.
  Ver detalhes em "Permissões confirmadas" → "Conexão com Databricks real". Nenhuma configuração
  no código atual tinha um nome hardcoded — `DATABRICKS_WAREHOUSE_ID` está vazio, preencher com
  `783ae0217086255c` na promoção.

## O que foi implementado nesta sessão

### Infraestrutura base
- `backend/app/config.py` — pydantic-settings, único ponto de leitura de env vars
- `backend/app/main.py` — FastAPI com middleware de logging (timestamp, rota, matrícula, status) + CORS
- Todos os `__init__.py` criados para todos os pacotes Python

### Camada LLM (pasta `backend/app/llm/`)
- `adapter.py` — interface abstrata `LLMAdapter.complete()`, exceções padronizadas, factory `get_llm_provider()`
- `claude_provider.py` — Anthropic SDK com asyncio.to_thread + timeout
- `openai_provider.py` — OpenAI SDK com asyncio.to_thread + timeout
- `gemini_provider.py` — google-generativeai com asyncio.to_thread + timeout
- `groq_provider.py` — SDK OpenAI apontado para `https://api.groq.com/openai/v1` (API compatível), modelo `llama-3.3-70b-versatile`
- Nenhum código fora de `llm/` importa um provider diretamente

### Genie local (pasta `backend/app/genie/`)
- `intent_rules.json` — palavras-chave OPERACIONAL/TOTAL_GERAL e regex de período. **ÚNICO arquivo a mudar após alinhamento com Pavan**
- `nl_to_sql.py` — fluxo completo: classifica intent → monta system prompt com schema + regras → gera SQL via LLM → executa via SQLAlchemy → sintetiza resposta em NL → mapeia todos os erros padronizados

### Conexão de dados (pasta `backend/app/db/`) — NOVO
- `databricks_connection.py` — `get_engine()` retorna a engine SQLAlchemy da fonte ativa via
  `DATA_SOURCE` (`local` → Postgres, `databricks` → Databricks real). Databricks autentica via
  OAuth M2M (client_credentials) do SP `sp-renovai-genie-api-poc`, usando `databricks-sdk`
  (`Config` + `oauth_service_principal`) e o dialect `databricks-sqlalchemy` — nunca PAT.
  Smoke test rodado em 2026-07-16: `SELECT COUNT(*) FROM tb_propagandistas` → 2156 (bate com o
  valor confirmado). Testado também com e-mail real de ache.com.br e de biosintetica.com.br
  (ambos SETOR_RESOLVIDO) — ver `test_context_integration.py`.
- Dependências novas em `requirements.txt`: `databricks-sql-connector`, `databricks-sqlalchemy`, `databricks-sdk`.

### Autenticação
- `backend/app/auth/context.py` — `resolver_contexto(email)` consulta tb_propagandistas, retorna
  ContextoResponse com os 3 status. Endpoint `GET /auth/contexto`. Agnóstico à fonte de dados —
  usa `db/databricks_connection.py:get_engine()`, não sabe se fala com Postgres local ou Databricks.

### Routers (`backend/app/routers/`)
- `prescricoes.py` — `POST /prescricoes/consultar`: valida contexto, chama nl_to_sql, devolve sql_gerado apenas para perfil_tecnico=True
- `recomendacoes.py` — `GET /recomendacoes/entrada`, `GET /recomendacoes/revisao`, `POST /recomendacoes/desconsiderar`. Validações: recomendação pertence ao rep, status PENDENTE, sem exclusão física.
- `gerencial.py` — `GET /gerencial/indicadores`, `GET /gerencial/propagandistas`, `GET /gerencial/recomendacoes`. GD acessa apenas seu escopo via tb_hierarquia_gd. Nenhum endpoint aceita escrita.

### Schemas Pydantic (`backend/app/schemas/`)
- `recomendacoes.py` — RecomendacaoItem, ListaRecomendacoesResponse, DesconsiderarRequest/Response
- `gerencial.py` — IndicadoresGD, PropagandistaSummary, RecomendacaoGerencial

### Jobs (`backend/app/jobs/`)
- `gerar_recomendacoes.py` — gera ENTRADA_PAINEL (pos ≤ corte, fora do painel) e REVISAO_PAINEL (ABAIXO_CORTE ou SEM_VISITA_5_MESES). Upsert: insere ou incrementa qtd_vezes_recomendado. Justificativa consultiva automática. CLI: `--ciclo`, `--dry-run`.
- `atualizar_status.py` — roda diariamente. ENTRADA→APLICADA se médico entrou no painel; REVISAO→APLICADA se médico saiu. Atualiza data_ultima_verificacao.
- `novo_ciclo.py` — expira PENDENTE do ciclo atual → chama gerar_recomendacoes para o novo ciclo. Calcula próximo ciclo automaticamente se não informado.

### SQL — Views gerenciais
- `data/scripts/08_create_views_gerencial.sql` — vw_hierarquia_gd, vw_recomendacoes_gerencial, vw_metricas_gerencial (taxa de aceite por GD/ciclo/tipo), vw_motivos_desconsideracao

### Testes (`backend/app/tests/`)
- `test_context.py` — 4 cenários: setor resolvido (domínio ache.com.br, real), setor resolvido
  (domínio biosintetica.com.br, mock), não encontrado (real), ambíguo (mock, ver nota em
  "Pontos simulados" sobre por que não é validável com dado real). Força `DATA_SOURCE=local` via
  fixture autouse, independente do que estiver no `.env` real — sempre testa contra o Postgres local.
- `test_context_integration.py` — **NOVO**, só roda com `DATA_SOURCE=databricks` no `.env`
  (skipif caso contrário). 3 cenários contra o Databricks real: ache.com.br, biosintetica.com.br
  (busca um e-mail real de cada domínio via query, não fixa valores) e não encontrado. Não testa
  IDENTIDADE_AMBIGUA (não reproduzível com dado real).
- `test_prescricoes.py` — golden set de 5 perguntas + propagandista não encontrado
- `test_recomendacoes.py` — lista com pendências, vazia, não encontrado, limite 5
- `test_desconsiderar.py` — 5 cenários: sucesso, não encontrada, outro rep, já desconsiderada, já aplicada
- `test_ciclo.py` — recomendação nova, recorrente, expirada, aplicada no dia seguinte, desconsiderada volta no ciclo novo
- `test_gerencial.py` — 6 cenários incluindo escopo, fora do escopo, filtros
- `test_cenarios_completos.py` — 10 testes E2E da matriz (mockados)
- `test_golden_set.py` — 22 perguntas parametrizadas, taxa de acerto por categoria, relatório no terminal

### Documentação (`docs/`)
- `docs/cenarios/matriz_teste.md` — 37 cenários em 6 grupos (GEORGE-06 + GEORGE-13)
- `docs/cenarios/golden_set.json` — 22 perguntas com categoria, sql_esperado_estrutura e resposta_esperada
- `docs/promocao_producao.md` — checklist de promoção local→produção com responsáveis (Flávio, Colin, Caio), riscos e sequência de 12 passos

## Ambiente de desenvolvimento
- **WSL Ubuntu 22.04:** `/home/admin/projetos/renovai-local/`
- **Windows:** `D:\Downloads\projeto-simbiox\projeto-ache\renovai-local\`
- **Sincronização:** `rsync -av --checksum --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.env' /mnt/d/Downloads/projeto-simbiox/projeto-ache/renovai-local/ /home/admin/projetos/renovai-local/`
- **Docker Compose** rodando no WSL com PostgreSQL 15 e pgAdmin
- **Python venv:** `.venv` em `/home/admin/projetos/renovai-local/`
- **Rodar testes:** `cd /home/admin/projetos/renovai-local && source .venv/bin/activate && pytest backend/app/tests/ -v`
- **Rodar API:** `uvicorn backend.app.main:app --reload`

## Tasks mapeadas

### Dados (Hugo)
- HUGO-01/02: ✅ tabelas criadas e validadas (validate_tables.py — todos os 4 cenários passam)
- HUGO-03: ✅ tb_recomendacoes_painel populada via gerar_recomendacoes
- HUGO-04/05: ✅ regras implementadas em jobs/gerar_recomendacoes.py
- HUGO-06: ✅ jobs/atualizar_status.py
- HUGO-07: ✅ jobs/novo_ciclo.py
- HUGO-08/09/10: ⚠️ tb_hierarquia_gd existe localmente; equivalente em produção a confirmar com Caio

### Orquestração (George)
- GEORGE-01: ✅ este CLAUDE.md (atualizado)
- GEORGE-02/03/04: ✅ schemas/recomendacoes.py e schemas/gerencial.py
- GEORGE-05: ✅ test_golden_set.py + test_cenarios_completos.py
- GEORGE-06/13: ✅ docs/cenarios/matriz_teste.md (37 cenários) + testes pytest
- GEORGE-07: ✅ seção de pontos simulados acima
- GEORGE-10/11/12: ✅ routers/gerencial.py + schemas/gerencial.py

### Backend IA (Bárbara)
- BARBARA-01: ✅ fluxo documentado em nl_to_sql.py
- BARBARA-02: ✅ auth/context.py — resolver_contexto()
- BARBARA-03: ✅ genie/nl_to_sql.py + llm/adapter.py + 3 providers
- BARBARA-04/05: ✅ routers/recomendacoes.py — /entrada e /revisao
- BARBARA-06: ✅ routers/recomendacoes.py — /desconsiderar
- BARBARA-07: ✅ justificativa consultiva gerada em gerar_recomendacoes.py
- BARBARA-08/09/10: ✅ routers/gerencial.py — /indicadores, /propagandistas, /recomendacoes

## Próximos passos (não iniciados)
- Implementar `llm/genie_provider.py` com Databricks SDK (para promoção a produção)
- Criar frontend React que consome os endpoints
- Alinhar intent_rules.json com Pavan após revisão de critérios
- Confirmar equivalente de tb_hierarquia_gd em produção (HUGO-08, com Caio)
- Confirmar claim JWT do Entra ID com Flávio (preferred_username vs upn)
