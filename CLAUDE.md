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

## Status ativo — Task 170097: login por Entra ID / Easy Auth

Arquitetura confirmada em 2026-09-15: o App Service Easy Auth autentica o
usuário antes de a requisição chegar ao FastAPI e injeta a identidade nos
headers `X-MS-CLIENT-PRINCIPAL-NAME` e `X-MS-CLIENT-PRINCIPAL`.
`AUTH_MODE=entra_id` não usa o caminho legado `AUTH_REQUIRE_JWT`/JWKS.

A parte anterior ao primeiro `@` do identificador, sem domínio hardcoded, é
comparada com `REP_LOGIN` usando `LOWER()` dos dois lados. `AUTH_MODE=senha`
permanece como default e continua comparando o e-mail da sessão com
`REP_EMAIL`.

**Claim real (24/09, via `/.auth/me` com a conta da Bárbara):** o claim
`upn` **não existe** no token da Aché. O login está em `preferred_username`
(`3gobarbara@ache.com.br`). Existe também `emailaddress`
(`barbara.godoy_terceiro@ache.com.br`), valor diferente que **não** pode ser
usado para comparar com `REP_LOGIN`. **Log Stream de hmg (24/09, 05:25 UTC):**
`X-MS-CLIENT-PRINCIPAL-NAME` chega com o `emailaddress`, não com o login.
Por isso `jwt_auth.py` ignora esse header e lê `preferred_username` (com
`upn` como reserva) de `X-MS-CLIENT-PRINCIPAL`. Corrigido localmente em
24/09, ainda sem commit. Ver `known-issues.md`.

Redirect URI de `pedai.ache.com.br` e do domínio de hmg: **resolvido em
23/09** (ambos cadastrados no App Registration).

**STATUS_ACESSO/PERFIL_ACESSO implementados e publicados em hmg (24/09).**
Checagem única em `auth/status_acesso.py`, aplicada sobre a identidade real
(nunca a personificada) em `POST /auth/login` e em
`jwt_auth.py::resolver_email_autenticado()`. `ADMIN_EMAILS` foi removido:
administrador vem de `tb_perfil_portal.PERFIL_ACESSO`. Frontend `entra_id`
implementado (`src/auth/entraId.ts`, `pages/AcessoBloqueado.tsx`), mas só
ativo em build com `VITE_AUTH_MODE=entra_id` — ver pendências abaixo.

Etapas da virada (roteiro da Bárbara em 24/09):

| Fase | Situação |
|---|---|
| 1. Commit + sync com dev + suíte | Concluída em 24/09 |
| 2. Confirmar header real no Log Stream | Concluída: logins das 05:25–05:38 UTC de 24/09, anteriores ao bloqueio |
| 3. Corrigir extração de identidade conforme a evidência | Feita localmente em 24/09 (`preferred_username` do payload; log `EASY_AUTH_DEBUG` removido), sem commit |
| 4. `AUTH_MODE=entra_id` + Easy Auth `RedirectToLoginPage`, juntos | Exige confirmação explícita da Bárbara |
| 5. Prova com as 4 contas reais do George | Exige confirmação explícita; lista das contas ainda não recebida |

Pendências que bloqueiam a Fase 4:
- Commitar a Fase 3, sincronizar com `dev` e gerar nova imagem.
- **Dockerfile:** `ARG VITE_AUTH_MODE=senha` foi adicionado em
  `AcheInfo_Apps/APP_RENOVAI/Dockerfile` em 24/09, sem commit. O bundle muda
  conforme o valor (conferido com `vite build`). A imagem da virada precisa
  de `--build-arg VITE_AUTH_MODE=entra_id`. Sem isso, a tela pede senha e
  `POST /auth/login` responde 404.
- 3 linhas de administrador em `tb_perfil_portal` (Cezar ×2, Eduardo) estão
  gravadas com o e-mail, não com o UPN. Com `entra_id`, elas não batem e esses
  dois ficam bloqueados. Corrigir no dado. Ver `known-issues.md` (24/09).
- `AUTH_REQUIRE_JWT` e `AUTH_EMAIL_CLAIM` **não** influenciam o modo
  `entra_id` (o branch `entra_id` é resolvido antes, e `AUTH_EMAIL_CLAIM` só
  vale no caminho JWKS legado). Não precisam mudar na virada.
- Easy Auth hoje: `requireAuthentication=true` e
  `unauthenticatedClientAction=AllowAnonymous`. Com `AllowAnonymous`,
  qualquer requisição direta pode forjar `X-MS-CLIENT-PRINCIPAL-NAME`. Por
  isso `AUTH_MODE=entra_id` só pode ser ativado **junto com**
  `RedirectToLoginPage`.

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

**Pendência das 5 colunas na tabela real RESOLVIDA em 2026-08-20** —
`DESCRIBE TABLE` confirmou as 5 presentes (`MOTIVO_DESCONSIDERACAO`,
`DESCONSIDERADO_POR`, `DATA_DESCONSIDERACAO`, `QTD_VEZES_DESCONSIDERADO`,
`BLOQUEAR_NOVAS_RECOMENDACOES`), e um teste real de UPDATE + reversão nessa
mesma data confirmou que o Service Principal `sp-renovai-genie-api-poc` tem
permissão de escrita (`MODIFY`) na tabela — não só `SELECT` como antes.
Detalhes completos em `docs/context/decisions-log.md` (entrada 2026-08-20).
Mapeamento em `_COLUNAS_POR_FONTE["databricks"]`, `routers/recomendacoes.py`
já está pronto e não é mais dormente — dado e permissão deixaram de ser
bloqueio para ativar este endpoint contra Databricks. Um erro 500 relatado
em produção nesse endpoint **não é explicado** por nenhuma dessas duas
causas no estado atual da tabela; se ainda ocorrer, a causa raiz está em
outro lugar (ver candidatos na entrada 2026-08-20 do decisions-log). Fora
de escopo por enquanto: lógica de bloqueio no próximo ciclo (responsabilidade
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

## Status ativo — Chat/Ranking/Agente + Perfil unificado — CONCLUÍDA E PUBLICADA

Concluída e publicada em 2026-08-26/27: trouxe para `renovai-local` o
trabalho do George na branch `merge/portal-agente-e-recomendacoes`
(`AcheInfo_Apps/APP_RENOVAI`) — agente de chat (`backend/app/agente/`,
`routers/agente.py`), aba Chat (`chat/perfil_medico.py`,
`routers/chat.py`), aba Ranking (`routers/ranking.py`), e unificou
`tb_perfil_portal` com a edição de nome/foto/limite de painel do George
(`auth/perfil.py`, `auth/foto.py`). Diagnóstico prévio confirmou os 4
arquivos centrais da Sprint 6 idênticos entre `dev` e a branch do George
— sem conflito real, só merge de superset.

**6 correções aplicadas durante o port**, achadas via teste de fumaça
real (API rodando de ponta a ponta, não só suíte mockada) — código do
George assumia só Databricks e quebrava contra Postgres local:
qualificação de catálogo (`acheinfo_dev.renovai.`), maiúsculas
inconsistentes entre objetos reais, sintaxe de `MERGE` (`UPDATE SET
destino.col=` não existe no Postgres 15), `current_timestamp()` com
parênteses, `uuid()` (só Databricks), `CAST(:x AS STRING)` (tipo não
existe no Postgres). Detalhe completo, achado por achado, em
`docs/context/known-issues.md` (entrada "dialeto SQL Databricks vs
Postgres", 26/08/2026).

Também migrado: o literal `318` (default de `LIMITE_PAINEL`, Sprint 6)
passou a vir de `tb_renovai_parametros` (tabela criada pelo George no
Databricks real em 26/08/2026, mesmo valor confirmado via `DESCRIBE`) em
vez de hardcoded — aplicado em `routers/recomendacoes.py`,
`jobs/gerar_recomendacoes.py`, `genie/nl_to_sql.py` e `auth/perfil.py`.

Schema local novo: `tb_conduta_medico`, `tb_perfil_medico_setor`,
`tb_ranking_medicos_validacao`, `tb_renovai_parametros`,
`tb_segmentacao_medico`, `tb_dim_medicos`, `tb_agente_persona`,
`tb_agente_log`, `vw_gold_auditpharma`/`vw_agente_produtos`
(simplificados, fonte real é externa) e 3 views reais
(`vw_segmentacao_efetiva`, `vw_agente_medico`, `vw_agente_participacao`)
— `data/scripts/14` a `16`.

**Publicado nos dois repositórios**: 6 commits em `renovai-local`
(`364e3c0`..`b0ee9b5`), 5 commits equivalentes em
`AcheInfo_Apps/dev` (`0630b17`..`67dd775`, push confirmado,
`origin/dev` atualizado). Limitação conhecida remanescente: `GET/PUT
/auth/perfil` não roda contra Postgres local — `tb_propagandistas`
local não tem as ~11 colunas que `auth/perfil.py` já exigia
(pré-existente, fora do escopo desta sincronização).

## Status ativo — Integração WhatsApp via Twilio (Sprint 7) — IMPLEMENTADA, AINDA NÃO COMMITADA

Implementada em 2026-08-28, ambiente sandbox: `backend/app/integrations/
whatsapp/` (`config.py`, `client.py`, `templates.py`, `service.py`),
`backend/app/services/registro_notificacao_whatsapp.py` (SQL cru via
`get_engine()`/`text()`, mesmo padrão de `registro_envio.py` — sem ORM,
não existe `Base`/`Column`/`Session` em nenhum lugar deste projeto) e
`backend/app/routers/webhooks_twilio.py` (callback de status,
`POST /webhooks/twilio/status`, registrado em `main.py`).

`tb_notificacoes_whatsapp` no Postgres local (`data/scripts/17`) —
decisão explícita de não tocar Databricks real nesta fase.
`send_whatsapp_notification()` está pronta mas **sem gatilho** — mesma
situação de `registrar_envio_recomendacoes()` na Sprint 5, nada chama
automaticamente ainda.

**PRECISA DE REVISÃO HUMANA**: conteúdo dos 2 templates
(`entrada_painel`/`revisao_painel` em `templates.py`) é placeholder
estrutural, não aprovado; nenhum dos dois foi submetido para aprovação
de Template na Meta (obrigatório fora da janela de 24h). `TWILIO_ENV=
production` bloqueado de propósito (`TwilioConfigError` clara) — sem
credencial de produção configurada ainda, ver
`docs/context/known-issues.md`.

19 testes novos, suíte completa em 360 passed / 1 failed (pré-existente,
sem relação) / 3 skipped. **Nada commitado ainda** — próxima sessão
precisa decidir a divisão de commits (git status mostra os arquivos
novos/modificados) antes de seguir.

## 2026-09-17 — PRs 23635 e 23670 sincronizados localmente

Os dois PRs de frontend foram aprovados e mesclados com squash em
`AcheInfo_Apps/dev`: `f82996d` (login) e `54e3c0e` (Home, Chat e
Recomendações). O diff combinado altera sete arquivos, todos em
`APP_RENOVAI/`; a cópia Aché está limpa em `dev`. Os mesmos hunks foram
aplicados em `renovai-local`, preservando duas diferenças locais de linhas
em branco em `frontend/src/pages/Recomendacoes.tsx`. Nada foi commitado
em `renovai-local`.

O formulário de e-mail e senha continua disponível. O botão Microsoft do
PR 23635 permanece visível e clicável, mas não cria a sessão do portal
quando `AUTH_MODE=senha`; pode iniciar o Easy Auth e encontrar a pendência
do redirect URI. A decisão é manter `AUTH_MODE=senha` e o Easy Auth em
`AllowAnonymous` por enquanto. Em 17/09, a imagem de homologação ainda era
`ed64685-entra-id-20260915`: não houve build nem deploy destes PRs.

Validação local: `npm run lint` passou. A coleta da suíte backend completa
para no problema preexistente de `test_golden_set.py`; ignorando apenas esse
arquivo, foram 476 passed, 5 failed e 3 skipped. As cinco falhas são as
já documentadas em `known-issues.md` (recorrência e massa de registro de
envios). Nenhuma falha nova foi observada.

## 2026-09-17 — Botão Microsoft desabilitado para o próximo deploy

Após o merge dos PRs 23635/23670, um ajuste local em `frontend/src/pages/Login.tsx`
trocou o link do Easy Auth por um botão desabilitado, ainda visível. O formulário
de e-mail e senha permanece. `npm run lint` passou nos dois ambientes locais.
O ajuste ainda não foi commitado, publicado nem implantado. A imagem de
homologação segue a anterior, com `AUTH_MODE=senha` e Easy Auth em
`AllowAnonymous`.

O `acessos.csv` existente na cópia Aché será preservado: gerar outro arquivo
rotacionaria as senhas dos 25 registros. Ele é ignorado pelo Git; o arquivo
de distribuição `senhas-portal-*.csv` também é ignorado pelo Git e excluído
do contexto Docker. O `acessos.csv` só entrará no contexto do build aprovado
separadamente e será incorporado à imagem, como exige o Dockerfile atual.

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

## 2026-09-17 — Build dos PRs 23635/23670 com botão Microsoft desabilitado

O ajuste de `Login.tsx` foi commitado em `2982345` e enviado à `dev`.
O build ACR `cf1u` terminou com sucesso e publicou
`app-renovai:2982345-login-microsoft-inerte-20260917`.
O `acessos.csv` existente foi usado no contexto da imagem sem regenerar senhas;
`acessos.csv` e `senhas-portal-*.csv` seguem fora do Git.
Homologação ainda usa `ed64685-entra-id-20260915`.
`AUTH_MODE=senha` e Easy Auth `AllowAnonymous` foram reconfirmados.
O deploy aguarda autorização separada.

## 2026-09-17 — Deploy em homologação dos PRs 23635/23670

A imagem `app-renovai:2982345-login-microsoft-inerte-20260917` foi configurada
em `asp-renoveai-hmg`, seguida de restart. O Web App está `Running`.
`AUTH_MODE=senha` e Easy Auth `AllowAnonymous` permaneceram iguais.
`/`, `/docs` e `/health` responderam 200; `/auth/contexto` sem sessão, 401.
`POST /auth/login` consta no OpenAPI. O bundle servido contém o formulário
de e-mail e senha e o botão Microsoft desabilitado, sem link para Easy Auth.
O Log Stream registrou erros da própria transmissão; a checagem HTTP passou.
O login real com uma credencial existente ainda requer validação manual.

## 2026-09-17 — Diagnóstico inicial de performance

O usuário confirmou login real bem-sucedido após o deploy. Métricas de
homologação mostram janelas com resposta média de 8,98 a 13,74 s, sem 5xx,
enquanto CPU ficou entre 8,6% e 14,4% e a fila HTTP em zero nessas janelas.
O diagnóstico detalhado e seus limites estão em `docs/context/known-issues.md`.

## 2026-09-17 — Performance medida no Databricks real

Com o `.env` local carregado somente no processo de teste e o código Aché
implantado, a consulta de cadastro levou 1,02 s; perfil 5,38 s; entrada
4,94 s; revisão 4,71 s; ranking 3,84 s. A abertura paralela de entrada,
revisão e perfil levou 5,35 s na primeira rodada e 3,48 s na segunda.
O warehouse observado está em 2X-Small serverless, com auto-stop de
5 minutos. Ver `docs/context/known-issues.md` para limites e detalhes.

## 2026-09-19 — Deploy com rotação dos acessos do piloto

O commit `4be1660` foi enviado à `dev` somente com arquivos de
`APP_RENOVAI/`. O build ACR `cf1v` publicou
`app-renovai:4be1660-dualsource-senhas-20260919` e a imagem foi implantada em
`asp-renoveai-hmg`. Os 25 usuários foram preservados e os 25 hashes foram
substituídos. `acessos.csv` e `senhas-portal-2026-09-18.csv` continuam fora do
Git; somente `acessos.csv` entrou na imagem. Ambos permanecem locais com modo
`0600`.

O container iniciou sem erro e o probe ficou saudável. `/`, `/health`,
`/docs` e `/openapi.json` responderam 200. `AUTH_MODE=senha` e Easy Auth
`AllowAnonymous` foram preservados; o botão Microsoft continua visível e
desabilitado. As senhas antigas deixam de autenticar novos logins, mas tokens
já emitidos podem continuar válidos por até 60 minutos.

## 2026-09-23 — Imagem publicada fora deste registro

Conferido em 24/09 via `az webapp config container show`: antes do deploy
abaixo, hmg rodava `app-renovai:53b8067-ranking-admin-menus-20260923`, não
`4be1660` como a entrada acima deixaria supor. Esse deploy não foi registrado
aqui. **É o alvo de rollback de imagem** do deploy de 24/09.

## 2026-09-24 — Deploy de STATUS_ACESSO em homologação (Fases 1 e 2)

Commits em `renovai-local` (`origin/main`): `61267ea` (schema local),
`1491a2a` (backend STATUS_ACESSO), `876465c` (frontend entra_id), `86d823b`
(branding `Ped.AI` no texto novo).

Sincronizado em `AcheInfo_Apps/dev`: `2b3e0b4` (backend) e `b9342ea`
(frontend). `dev` não tinha commits de terceiros. Houve merge de 3 vias em
5 arquivos que já divergiam em `dev`. O trabalho que só existe em `dev` foi
preservado: busca de médico em `App.tsx`, testes de reversão de aceite em
`test_reverter.py`, `ciclo_referencia` 202608 em `config.py` e branding
`Ped.AI`. `data/` e `docs/` são ignorados pelo Git em `APP_RENOVAI`, então o
script `20_migrar_status_acesso.sql` existe lá só em disco. Todo o trabalho
do Thiago que já estava mesclado em `dev` está na imagem. `virada-entraid-front`
ficou de fora de propósito: o essencial dela foi reimplementado sobre `dev`.

Suítes: `renovai-local` com 536 passed / 7 failed (conhecidas) / 15 skipped;
`dev` com 526 passed / 12 failed / 15 skipped. As 5 falhas a mais em `dev`
são de `test_gerar_recomendacoes.py`, arquivo que só existe lá, e foram
confirmadas idênticas antes e depois da sincronização via `git stash`.
`npm run build` limpo nos dois repositórios.

Build ACR `cf1y` publicou `app-renovai:b9342ea-status-acesso-debug-20260924`.
A imagem foi trocada em `asp-renoveai-hmg` e o app reiniciado; `/`, `/docs`
e `/health` responderam 200. `AUTH_MODE=senha` e Easy Auth `AllowAnonymous`
**inalterados** (conferido depois do deploy).

Consequência aceita pela Bárbara: os 25 usuários de `acessos.csv` estão todos
`BLOQUEADO` em `tb_perfil_portal`, então o login por senha deles em hmg
passou a responder 403 `ACESSO_BLOQUEADO`. Ninguém usa essas credenciais em
homologação.

A imagem inclui o log temporário `EASY_AUTH_DEBUG` para a Fase 2. A Fase 2
está parada porque o login Microsoft da Bárbara foi bloqueado pelo Entra ID
(Smart Lockout ou política de horário, não confirmado). Nada foi alterado em
`AUTH_MODE` nem no Easy Auth.
