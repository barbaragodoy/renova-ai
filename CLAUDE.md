# RenovAI — Contexto do Projeto Local

Simulação local do PED 2.0 / RenovAI (Aché Farma): motor de recomendação do
painel médico para propagandistas, com Bárbara cobrindo todos os papéis
(dados/Hugo, orquestração/George, backend de IA/Bárbara).

## Stack

| Camada         | Local (dev)                          | Produção (Aché)                    |
|----------------|---------------------------------------|-------------------------------------|
| Banco          | PostgreSQL via Docker                 | Azure Databricks / Unity Catalog / Delta |
| Backend        | Python / FastAPI                      | Python / FastAPI em container no Azure |
| LLM            | configurável via `LLM_PROVIDER` (claude/openai/gemini/groq) | Databricks Genie via Service Principal |
| Genie          | LangChain + SQLAlchemy + LLM adapter  | Databricks Genie                    |
| Autenticação   | Auth0 free tier (simula Entra ID)     | Microsoft Entra ID / SSO             |
| Frontend       | React localhost (referência)          | —                                    |

Alternância de fonte de dados local↔real é via `DATA_SOURCE` em `.env`
(`local` | `databricks`) — ver `backend/app/db/databricks_connection.py`.

## Comandos

```bash
cd /home/admin/projetos/renovai-local && source .venv/bin/activate
pytest backend/app/tests/ -v          # rodar testes
uvicorn backend.app.main:app --reload # rodar API
```

## Status ativo — migração dos endpoints de recomendações (BARBARA-04/05) — CONCLUÍDA

Concluída e validada de ponta a ponta em 2026-08-06 (origem, notebook
oficial do Hugo, backend, API e regra de negócio confirmada pelo George).
`GET /recomendacoes/entrada` e `GET /recomendacoes/revisao` usam
`db/databricks_connection.py:get_engine()` (respeita `DATA_SOURCE`) e
alternam tabela/colunas por fonte via mapeamento em `routers/recomendacoes.py`.

**`GET /recomendacoes/revisao` — concluído:** validado via curl real contra
dado gerado pelo notebook oficial (`notebookId 1296520715972786`) —
payload coerente, `ORDER BY posicao_ranking DESC`, ≤5 itens, trava
`QTD_MEDICOS_PAINEL_CICLO > 400` sem violações. A ampliação de escopo para
`REVISAO_SEM_VISITA_5_MESES` (médico com ranking bom, ≤400, mas sem visita
há 5+ meses e com 5 ciclos consecutivos no painel) foi **confirmada pelo
George como regra de negócio real e intencional** — sem pendência de
alinhamento remanescente. Detalhes completos em
`docs/context/known-issues.md`.

**`GET /recomendacoes/entrada` — concluído (2026-07-31):** o bloqueio de
`NOME_MEDICO` nulo foi **resolvido na origem pelo Hugo** via `COALESCE` com
a tabela dimensional `ranking_medicos_renovache_dim_medicos` — revalidado
com 0 nulos, nomes reais conferidos via API (`curl` real, sem fallback).
Sem nenhuma limitação de dado conhecida remanescente. O fallback `"Médico
ainda não identificado (UFCRM {ufcrm})"` continua no código
(`schemas`/`routers/recomendacoes.py`) como defesa em profundidade
permanente, não como workaround a remover.

Achado à parte (config, não bug): o default `ciclo_referencia` em
`config.py` foi atualizado em 2026-08-06 de `202507` para `202608`
(ciclo real na fonte no momento da atualização). Como esse default fica
desatualizado a cada rollover mensal de ciclo, chamadas sem `?ciclo=`
explícito continuam sujeitas a retornar lista vazia assim que o ciclo
rolar de novo — vale revisar esse default periodicamente ou considerar
resolvê-lo dinamicamente (`MAX(CICLO_RECOMENDACAO)`, como já fazem os
testes de integração) em vez de manter um valor estático.

`POST /recomendacoes/desconsiderar` está **CONGELADO** por decisão do
George desde 2026-07-23 — não investir manutenção nova nele (ver
`docs/context/decisions-log.md`).

## Índice — ler sob demanda conforme a tarefa

- `docs/context/decisions-log.md` — decisões de negócio/arquitetura datadas
  (permissões do SP, warehouse correto, domínios de e-mail, TRUNCATE em
  produção, Genie Room histórico, congelamento do desconsiderar, regras de
  negócio baseline, pendências abertas com George/Hugo/Caio/Flávio).
- `docs/context/databricks-schema-real.md` — mapeamento completo de colunas
  entre o schema local (Postgres) e o schema real confirmado no Databricks,
  para `tb_propagandistas` e `tb_recomendacoes_painel_historico`.
- `docs/context/known-issues.md` — bugs técnicos na fonte real com status
  RESOLVIDO/ABERTO (inclui o histórico de tentativas de correção do
  `MOTIVO_RECOMENDACAO`, para não perder o rastro numa próxima tentativa).
- `docs/context/arquitetura.md` — inventário completo do que foi implementado
  (LLM adapters, Genie local, auth, routers, jobs, testes), tasks por pessoa
  (Hugo/George/Bárbara) e ambiente de desenvolvimento (WSL/Windows/rsync).
- `.claude/skills/verificar-databricks/SKILL.md` — checklist reutilizável
  (comandos SQL/curl prontos) para validar tabela/view/permissão no
  Databricks real, sem depender de `SHOW GRANTS` (tem limitação de
  visibilidade — usar token OAuth M2M direto).
- `.claude/rules/databricks.md` — carrega automaticamente ao editar
  `backend/app/db/**`, `routers/recomendacoes.py` ou `auth/**`: schema
  resumido + regra de mitigação do `MOTIVO_RECOMENDACAO`.

Não usamos AGENTS.md neste projeto — apenas Claude Code.
