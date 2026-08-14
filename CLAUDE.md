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

## Status ativo — Desconsiderar Recomendação (task 161830/163626)

Implementada **localmente** (Postgres) em 2026-08-06, reconciliando o
endpoint antigo congelado (item 1), o notebook de referência da task 163626
(item 2) e a especificação oficial da task 161830 do George (item 3, que
formaliza a decisão de canal REST e resolve o congelamento) — detalhes
completos em `docs/context/decisions-log.md` (entrada 2026-08-06).

O antigo `POST /recomendacoes/desconsiderar` (ID no corpo) foi
**descontinuado** — removido de `routers/recomendacoes.py`,
`schemas/recomendacoes.py` e `test_desconsiderar.py`. Novo contrato:
`POST /recomendacoes/{id_recomendacao}/desconsiderar`, ID no path,
identidade exclusivamente via `resolver_contexto()`, autorização de dono da
recomendação (403), `motivo` restrito a `MOTIVOS_DESCONSIDERACAO` (+
`OUTROS` com `motivo_outros_texto`), `bloquear_novas_recomendacoes`
obrigatório sem default, `data_desconsideracao` gerada pelo backend, UPDATE
atômico (`WHERE status_recomendacao='PENDENTE'`) cobrindo concorrência.

**Aguardando as 5 colunas na tabela real** (`tb_recomendacoes_painel_historico`)
antes de migrar para Databricks — pendência já formalizada com o Hugo, mesmo
processo de BARBARA-04/05: `MOTIVO_DESCONSIDERACAO`, `DESCONSIDERADO_POR`,
`DATA_DESCONSIDERACAO`, `QTD_VEZES_DESCONSIDERADO`,
`BLOQUEAR_NOVAS_RECOMENDACOES`. Mapeamento já pronto (dormente) em
`_COLUNAS_POR_FONTE["databricks"]`, `routers/recomendacoes.py`. Fora de
escopo por enquanto: lógica de bloqueio no próximo ciclo (responsabilidade
do notebook do Hugo) — a aba "Arquivadas" (consulta + reversão) já foi
implementada, ver seção abaixo.

## Status ativo — Aba Arquivadas (consulta + reversão de desconsideradas)

Implementada **localmente** (Postgres) em 2026-08-13, sobre a mesma base do
Desconsiderar Recomendação acima — as 5 colunas de desconsideração já
existiam no schema local desde aquela task, então este desenvolvimento não
teve nenhuma pendência de dado nova. Reaproveita toda a infraestrutura
existente (`get_engine()`, `_schema()`, `resolver_contexto()`,
`_ciclo_mais_recente()`, `_aplicar_fallback_nome_medico()`,
`_COLUNAS_POR_FONTE`).

`GET /recomendacoes/desconsideradas` — lista o histórico completo (sem
`LIMIT`, diferente de `/entrada`/`/revisao` que limitam a sugestões
priorizadas) das recomendações `DESCONSIDERADA` do propagandista
autenticado, ordenado por `data_desconsideracao DESC`.

`POST /recomendacoes/{id_recomendacao}/reverter` — sem payload no corpo.
Mesmas checagens de identidade/dono de `/desconsiderar` (404/403), 400 se a
recomendação não estiver em `DESCONSIDERADA`. Novo status é `PENDENTE` se o
ciclo da recomendação ainda é o mais recente (`_ciclo_mais_recente()`) ou
`EXPIRADA` caso contrário. Limpa `motivo_desconsideracao`,
`desconsiderado_por`, `bloquear_novas_recomendacoes` e
`data_desconsideracao` (voltam a `NULL`) — `qtd_vezes_desconsiderado`
propositalmente **não** é zerado, mantém o histórico acumulado de quantas
vezes aquela recomendação já foi desconsiderada. UPDATE atômico
(`WHERE status_recomendacao='DESCONSIDERADA'`) cobrindo concorrência, mesmo
padrão de `/desconsiderar`. Confirmado por teste de integração que uma
recomendação revertida para `PENDENTE` reaparece naturalmente em
`GET /recomendacoes/entrada`/`/revisao`, sem qualquer alteração nesses dois
endpoints.

Mapeamento para Databricks continua **dormente**, aguardando as mesmas 5
colunas do Hugo já documentadas na seção acima.

## Status ativo — Registro de Envio do Piloto (Sprint 5)

Implementado **localmente** em 2026-08-10 — tabela nova, sem dependência de
correção externa (diferente de `tb_recomendacoes_painel*`): propriedade e
criação da própria Bárbara, não do Hugo.

`tb_envios_recomendacoes_piloto` (`data/scripts/11_create_tb_envios_recomendacoes_piloto.sql`)
registra o histórico de envio de recomendações aos propagandistas durante o
piloto, comparando os grupos **WhatsApp**, **E-mail** e **Controle**. Grão:
uma linha por combinação (envio, recomendação) — várias recomendações
mandadas juntas no mesmo disparo compartilham `ID_ENVIO`. Decisão de design:
o grupo **CONTROLE também gera registro**, com `CANAL_ENVIO = 'NENHUM'`
("recomendação estava disponível, sem push ativo") — garante que a tabela
sozinha permita comparar timing entre os três grupos sem depender de outra
fonte.

Implementado como **função de serviço**, não endpoint REST:
`registrar_envio_recomendacoes()` em `backend/app/services/registro_envio.py`
— ainda não há job/integração de disparo real (Twilio/WhatsApp, templates
Meta, e-mail) que a chame. `ID_ENVIO` (UUID) e `DATA_HORA_ENVIO` são sempre
gerados pelo backend, nunca aceitos como parâmetro externo — nem existem no
schema `RegistrarEnvioRequest` (`schemas/envio_recomendacoes.py`). Validação
cruzada `grupo_piloto`/`canal_envio` via `model_validator` (CONTROLE exige
NENHUM; WHATSAPP/EMAIL exigem o canal igual ao grupo).

Não depende de: integração Twilio, aprovação de templates Meta, ou
disponibilização de números de telefone dos propagandistas — desenvolvido de
forma totalmente independente disso.

**Ainda não existe no Databricks real** — será criada lá em sessão separada
(ver `docs/context/databricks-schema-real.md`).

## Índice — ler sob demanda conforme a tarefa

- `docs/context/decisions-log.md` — decisões de negócio/arquitetura datadas
  (permissões do SP, warehouse correto, domínios de e-mail, TRUNCATE em
  produção, Genie Room histórico, reconciliação/descongelamento do
  desconsiderar (2026-08-06), regras de negócio baseline, pendências abertas
  com George/Hugo/Caio/Flávio).
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
