# Arquitetura implementada — RenovAI Local

Inventário do que foi construído nesta simulação local, mais o
acompanhamento de tasks por pessoa e o ambiente de desenvolvimento completo.
Ler sob demanda ao explorar/estender um módulo específico — não é
necessário para o dia a dia de uma sessão pontual (ver comandos rápidos no
`CLAUDE.md` raiz).

## Infraestrutura base
- `backend/app/config.py` — pydantic-settings, único ponto de leitura de env vars.
- `backend/app/main.py` — FastAPI com middleware de logging (timestamp, rota, matrícula, status) + CORS.
- Todos os `__init__.py` criados para todos os pacotes Python.

## Camada LLM (`backend/app/llm/`)
- `adapter.py` — interface abstrata `LLMAdapter.complete()`, exceções padronizadas, factory `get_llm_provider()`.
- `claude_provider.py` — Anthropic SDK com asyncio.to_thread + timeout.
- `openai_provider.py` — OpenAI SDK com asyncio.to_thread + timeout.
- `gemini_provider.py` — google-generativeai com asyncio.to_thread + timeout.
- `groq_provider.py` — SDK OpenAI apontado para `https://api.groq.com/openai/v1` (API compatível), modelo `llama-3.3-70b-versatile`.
- Nenhum código fora de `llm/` importa um provider diretamente.

## Genie local (`backend/app/genie/`)
- `intent_rules.json` — palavras-chave OPERACIONAL/TOTAL_GERAL e regex de período. Único arquivo a mudar após alinhamento com Pavan.
- `nl_to_sql.py` — fluxo completo: classifica intent → monta system prompt com schema + regras → gera SQL via LLM → executa via SQLAlchemy → sintetiza resposta em NL → mapeia todos os erros padronizados (ver `docs/context/decisions-log.md` → baseline).

## Conexão de dados (`backend/app/db/`)
- `databricks_connection.py` — `get_engine()` retorna a engine SQLAlchemy da fonte ativa via `DATA_SOURCE` (`local` → Postgres, `databricks` → Databricks real). Databricks autentica via OAuth M2M (client_credentials) do SP `sp-renovai-genie-api-poc`, usando `databricks-sdk` (`Config` + `oauth_service_principal`) e o dialect `databricks-sqlalchemy` — nunca PAT.
- Dependências: `databricks-sql-connector`, `databricks-sqlalchemy`, `databricks-sdk` (em `requirements.txt`).
- Detalhes de teste/validação: ver `docs/context/decisions-log.md` (2026-07-16).

## Autenticação
- `backend/app/auth/context.py` — `resolver_contexto(email, tabela="tb_propagandistas")` consulta tb_propagandistas (ou `tb_propagandista_teste`), retorna `ContextoResponse` com os 3 status (baseline em decisions-log.md). Endpoint `GET /auth/contexto`. Agnóstico à fonte de dados. Parâmetro `tabela` validado contra whitelist (`_TABELAS_PERMITIDAS`).
- `backend/app/auth/jwt_auth.py` — `resolver_email_autenticado(authorization, email_param)`. Ponto único de resolução de identidade, usado por `auth/context.py`, `routers/prescricoes.py` e `routers/recomendacoes.py`. Controlado por `AUTH_REQUIRE_JWT`:
  - `false` (padrão local) — aceita o e-mail cru vindo de query/body, sem validar token.
  - `true` (produção) — exige `Authorization: Bearer <token>`, valida assinatura/audience/issuer via JWKS (Auth0/Entra ID, com cache de `PyJWKClient` por domínio) e extrai o e-mail da claim configurada em `AUTH_EMAIL_CLAIM` (`preferred_username` por padrão — a confirmar com Flávio).
  - Coberto por `test_jwt_auth.py` (7 cenários, tudo mockado).

## Routers (`backend/app/routers/`)
- `prescricoes.py` — `POST /prescricoes/consultar`: valida contexto, chama nl_to_sql, devolve `sql_gerado` apenas para `perfil_tecnico=True`.
- `recomendacoes.py` — `GET /recomendacoes/entrada`, `GET /recomendacoes/revisao`, `POST /recomendacoes/desconsiderar` (CONGELADO, ver decisions-log.md). Validações: recomendação pertence ao rep, status PENDENTE, sem exclusão física. Status de migração ativo desses endpoints: ver `CLAUDE.md` raiz.
- `gerencial.py` — `GET /gerencial/indicadores`, `GET /gerencial/propagandistas`, `GET /gerencial/recomendacoes`. GD acessa apenas seu escopo via `tb_hierarquia_gd`. Nenhum endpoint aceita escrita.

## Schemas Pydantic (`backend/app/schemas/`)
- `recomendacoes.py` — RecomendacaoItem, ListaRecomendacoesResponse, DesconsiderarRequest/Response.
- `gerencial.py` — IndicadoresGD, PropagandistaSummary, RecomendacaoGerencial.

## Jobs (`backend/app/jobs/`)
- `gerar_recomendacoes.py` — gera ENTRADA_PAINEL (pos ≤ corte, fora do painel) e REVISAO_PAINEL (ABAIXO_CORTE ou SEM_VISITA_5_MESES). Upsert: insere ou incrementa `qtd_vezes_recomendado`. Justificativa consultiva automática. CLI: `--ciclo`, `--dry-run`.
- `atualizar_status.py` — roda diariamente. ENTRADA→APLICADA se médico entrou no painel; REVISAO→APLICADA se médico saiu. Atualiza `data_ultima_verificacao`.
- `novo_ciclo.py` — expira PENDENTE do ciclo atual → chama `gerar_recomendacoes` para o novo ciclo. Calcula próximo ciclo automaticamente se não informado.

## SQL — Views gerenciais
- `data/scripts/08_create_views_gerencial.sql` — `vw_hierarquia_gd`, `vw_recomendacoes_gerencial`, `vw_metricas_gerencial` (taxa de aceite por GD/ciclo/tipo), `vw_motivos_desconsideracao`.

## Testes (`backend/app/tests/`)
- `test_context.py` — 4 cenários: setor resolvido (ache.com.br, real), setor resolvido (biosintetica.com.br, mock), não encontrado (real), ambíguo (mock). Força `DATA_SOURCE=local` via fixture autouse.
- `test_context_integration.py` — só roda com `DATA_SOURCE=databricks` no `.env` (skipif caso contrário). 6 cenários contra o Databricks real: `test_setor_resolvido_dominio_ache_real`, `_biosintetica_real`, `test_propagandista_nao_encontrado_real`, `test_setor_resolvido_com_email_gravado_em_maiusculo`, `test_setor_resolvido_tabela_teste`, `test_identidade_ambigua_tabela_teste`.
- `test_prescricoes.py` — golden set de 5 perguntas + propagandista não encontrado.
- `test_recomendacoes.py` — lista com pendências, vazia, não encontrado, limite 5.
- `test_desconsiderar.py` — 5 cenários: sucesso, não encontrada, outro rep, já desconsiderada, já aplicada.
- `test_ciclo.py` — recomendação nova, recorrente, expirada, aplicada no dia seguinte, desconsiderada volta no ciclo novo.
- `test_gerencial.py` — 6 cenários incluindo escopo, fora do escopo, filtros.
- `test_cenarios_completos.py` — 10 testes E2E da matriz (mockados).
- `test_golden_set.py` — 22 perguntas parametrizadas, taxa de acerto por categoria, relatório no terminal.

## Documentação (`docs/`)
- `docs/cenarios/matriz_teste.md` — 37 cenários em 6 grupos (GEORGE-06 + GEORGE-13).
- `docs/cenarios/golden_set.json` — 22 perguntas com categoria, sql_esperado_estrutura e resposta_esperada.
- `docs/promocao_producao.md` — checklist de promoção local→produção com responsáveis (Flávio, Colin, Caio), riscos e sequência de 12 passos.
- `docs/context/` (este diretório) — decisions-log.md, databricks-schema-real.md, known-issues.md, arquitetura.md (este arquivo).

## Ambiente de desenvolvimento
- **WSL Ubuntu 22.04:** `/home/admin/projetos/renovai-local/`
- **Windows:** `D:\Downloads\projeto-simbiox\projeto-ache\renovai-local\`
- **Sincronização:** `rsync -av --checksum --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='.env' /mnt/d/Downloads/projeto-simbiox/projeto-ache/renovai-local/ /home/admin/projetos/renovai-local/`
- **Docker Compose** rodando no WSL com PostgreSQL 15 e pgAdmin.
- **Python venv:** `.venv` em `/home/admin/projetos/renovai-local/`.

## Tasks mapeadas (histórico de acompanhamento por pessoa)

### Dados (Hugo)
- HUGO-01/02: ✅ tabelas criadas e validadas (`validate_tables.py` — todos os 4 cenários passam).
- HUGO-03: ✅ `tb_recomendacoes_painel` populada via `gerar_recomendacoes`.
- HUGO-04/05: ✅ regras implementadas em `jobs/gerar_recomendacoes.py`.
- HUGO-06: ✅ `jobs/atualizar_status.py`.
- HUGO-07: ✅ `jobs/novo_ciclo.py`.
- HUGO-08/09/10: ⚠️ `tb_hierarquia_gd` existe localmente; equivalente em produção a confirmar com Caio.

### Orquestração (George)
- GEORGE-01: ✅ CLAUDE.md (atualizado nesta reestruturação).
- GEORGE-02/03/04: ✅ `schemas/recomendacoes.py` e `schemas/gerencial.py`.
- GEORGE-05: ✅ `test_golden_set.py` + `test_cenarios_completos.py`.
- GEORGE-06/13: ✅ `docs/cenarios/matriz_teste.md` (37 cenários) + testes pytest.
- GEORGE-07: ✅ pontos simulados (ver `docs/context/decisions-log.md`).
- GEORGE-10/11/12: ✅ `routers/gerencial.py` + `schemas/gerencial.py`.

### Backend IA (Bárbara)
- BARBARA-01: ✅ fluxo documentado em `nl_to_sql.py`.
- BARBARA-02: ✅ `auth/context.py` — `resolver_contexto()`.
- BARBARA-03: ✅ `genie/nl_to_sql.py` + `llm/adapter.py` + 3 providers.
- BARBARA-04/05: 🔄 `routers/recomendacoes.py` — `/entrada` e `/revisao`, migração em andamento (ver status ativo no `CLAUDE.md` raiz).
- BARBARA-06: ✅ implementado, mas **CONGELADO** desde 2026-07-23 (ver decisions-log.md). Não investir manutenção nova.
- BARBARA-07: ✅ justificativa consultiva gerada em `gerar_recomendacoes.py`.
- BARBARA-08/09/10: ✅ `routers/gerencial.py` — `/indicadores`, `/propagandistas`, `/recomendacoes`.
