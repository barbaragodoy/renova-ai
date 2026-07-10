# RenovAI — Contexto do Projeto Local

## O que é esse projeto
Simulação local do PED 2.0 / RenovAI (Aché Farma). Motor de recomendação 
do painel médico para propagandistas. Eu executo todos os papéis: dados (Hugo), 
orquestração (George) e backend de IA (Bárbara).

## Stack local
- Banco: PostgreSQL via Docker
- Backend: Python / FastAPI
- LLM: provider configurável via LLM_PROVIDER no .env (claude, openai, gemini)
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

## Pontos simulados (não confirmados em produção)
- Critério de desempate de sugestões: a definir com Caio
- Perfis autorizados além do GD: a definir
- Regra de exibição de justificativa de recusa para GD: a definir (implementado: GD vê motivo_desconsideracao)
- Fonte oficial da hierarquia GD: a confirmar com Hugo (HUGO-08)
- Claim JWT do Entra ID com e-mail: preferred_username ou upn — confirmar com Flávio
- GeniProvider (Databricks SDK): não implementado ainda — ver docs/promocao_producao.md

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
- Nenhum código fora de `llm/` importa um provider diretamente

### Genie local (pasta `backend/app/genie/`)
- `intent_rules.json` — palavras-chave OPERACIONAL/TOTAL_GERAL e regex de período. **ÚNICO arquivo a mudar após alinhamento com Pavan**
- `nl_to_sql.py` — fluxo completo: classifica intent → monta system prompt com schema + regras → gera SQL via LLM → executa via SQLAlchemy → sintetiza resposta em NL → mapeia todos os erros padronizados

### Autenticação
- `backend/app/auth/context.py` — `resolver_contexto(email)` consulta tb_propagandistas, retorna ContextoResponse com os 3 status. Endpoint `GET /auth/contexto`.

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
- `test_context.py` — 3 cenários: setor resolvido, não encontrado, ambíguo (mock)
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
