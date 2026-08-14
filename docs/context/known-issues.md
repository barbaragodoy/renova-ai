# Known Issues — tb_recomendacoes_painel_historico

Estado técnico da tabela `tb_recomendacoes_painel_historico` e views
associadas (`acheinfo_dev.renovai`). Atualizar o status aqui em vez de só no
CLAUDE.md — este arquivo é a fonte de verdade sobre o que ainda bloqueia a
migração do endpoint `/recomendacoes` (ver `docs/context/decisions-log.md`,
2026-07-23).

## RESOLVIDO NA ORIGEM — 2026-07-31 — NOME_MEDICO nulo em ENTRADA_PAINEL
Descoberto em 2026-07-30 durante a revalidação pós-correção do Hugo (ver
RESOLVIDOs abaixo). Na época: **100% das 265.916 linhas** de
`TIPO_RECOMENDACAO = 'ENTRADA_PAINEL'` (ciclo `202607`,
`STATUS_RECOMENDACAO = 'PENDENTE'`) tinham `NOME_MEDICO IS NULL`.
`REVISAO_PAINEL` sempre esteve com 0 linhas nulas nessa coluna — o problema
era específico do lado ENTRADA.

**Causa raiz (confirmada por auditoria em 2026-07-31):** `NOME_MEDICO` vinha
exclusivamente de `vw_painel_expandido` (alimentada por
`vw__salesfarma_painel_medico`), que só tem cadastro de médico já presente
no painel — candidatos a `ENTRADA_PAINEL` (ainda fora do painel) não tinham
nome em nenhuma fonte usada pelo pipeline até então.

**Correção do Hugo na origem, confirmada em 2026-07-31:** aplicado
`COALESCE` entre `vw_painel_expandido` e a tabela dimensional
`dmn_inteligencia_dados_prd.gold.ranking_medicos_renovache_dim_medicos`,
que cobre também médicos fora do painel. Revalidado via query direta:
- `ENTRADA_PAINEL`: **271.660 linhas, 0 nulas** em `NOME_MEDICO` (volume
  subiu de 265.916 para 271.660 no ciclo — normal, reflete o rolar de
  ciclo, não a correção em si).
- `REVISAO_PAINEL`: sem regressão, continua 0 nulas.
- Nomes reais conferem com a tabela dimensional nova.
- Confirmado também via API real: `GET /recomendacoes/entrada?email=valter.junior@ache.com.br&ciclo=202607`
  (rep `177917`) retorna 5 itens com nomes reais (`ALESSANDRO RODRIGUES DE
  CARVALHO`, `PITER LACERDA FIGUEIREDO DE FREITAS`, etc.), sem nenhum
  fallback, ordenado corretamente por `soma_pontuacao` DESC.

**Mitigação de backend aplicada em 2026-07-31 — mantida como defesa em
profundidade PERMANENTE, não é workaround temporário a remover:**
- `schemas/recomendacoes.py`: `RecomendacaoItem.nome_medico` continua
  `Optional[str] = None` — não voltar a `str` obrigatório, pois a fonte já
  demonstrou que pode zerar o preenchimento de novo se a lógica de COALESCE
  mudar ou a tabela dimensional tiver gaps futuros.
- `routers/recomendacoes.py`: `_aplicar_fallback_nome_medico()` continua
  aplicado nos dois endpoints. Hoje não é mais exercido pelos dados reais
  (0 nulos), mas existe justamente para não deixar o endpoint quebrar se
  isso regredir — `test_recomendacoes.py::test_entrada_nome_medico_nulo_aplica_fallback`
  (mockado) continua cobrindo esse caminho de código diretamente, já que
  não há mais dado real nulo para exercitá-lo end-to-end.
- `test_recomendacoes_integration.py::test_entrada_ordenada_por_soma_pontuacao_desc`
  foi ajustado em 2026-07-31: não exige mais a presença do fallback no
  payload (antes exigia, porque 100% das linhas eram nulas) — agora só
  confirma que `nome_medico` nunca vem vazio/None e que a ordenação
  continua correta. Ajuste de teste, não regressão.

## RESOLVIDO POR VIA ALTERNATIVA — USE CATALOG em dmn_inteligencia_dados_prd — achado em 2026-08-12
SP `sp-renovai-genie-api-poc` **não tem `USE CATALOG`** em
`dmn_inteligencia_dados_prd` (testado via token OAuth M2M direto,
`current_user()` confirmado como o próprio SP) — a query direta contra
`dmn_inteligencia_dados_prd.gold.ranking_medicos_renovache_dim_medicos`
falha com `INSUFFICIENT_PERMISSIONS` a nível de catálogo, antes mesmo de
chegar a checar SELECT na tabela. Não bloqueava o pipeline do Hugo (que
roda com identidade própria de job/notebook, não com o SP da API).

**Resolução, descoberta em 2026-08-12 na comparação com a branch
`feature/aba-recomendacoes` do George (`AcheInfo_Apps/APP_RENOVAI`):** em
vez de solicitar o GRANT cruzado de catálogo, o George criou
`tb_dim_medicos` — uma **tabela espelho local**, dentro de
`acheinfo_dev.renovai` (catálogo que o SP já lê), replicando os campos
`especialidade`, `cidade` e `uf` da dimensão original. `RecomendacaoItem`
ganhou esses 3 campos (mais `meses_sem_visita`, calculado no SQL ancorado
no ciclo) via `LEFT JOIN tb_dim_medicos`. Comentário dele confirma o
motivo: "o Service Principal do portal só lê acheinfo_dev.renovai e o
catálogo da dimensão original é vetado para ele".

**Estado em `renovai-local`/`APP_RENOVAI` nesta data: ainda não
incorporado por mim** — é uma tabela nova, capacidade aditiva, sem
conflito com nada existente. Fica registrado aqui como candidato a task
separada, se fizer sentido para o roadmap (não é urgente, os endpoints
funcionam sem esses campos hoje).

**Estado atual:** `/recomendacoes/entrada` totalmente funcional com dado
real — nomes verdadeiros, sem fallback nos dados de hoje. Nenhuma limitação
de dado conhecida remanescente para este endpoint.

## RESOLVIDO — STATUS_RECOMENDACAO travado em "CONSOLIDADA" — 2026-07-30
Estava 100% `CONSOLIDADA` (nenhuma linha `PENDENTE`), bloqueante para
qualquer conteúdo real nos endpoints. **Corrigido**: revalidado em
2026-07-30 com **546.108 linhas com `STATUS_RECOMENDACAO = 'PENDENTE'`
(100%)** no ciclo `202607`. Confirmado com `/recomendacoes/entrada` e
`/recomendacoes/revisao` retornando conteúdo real via curl (ver seção de
validação de endpoints abaixo). Reportado ao Hugo em 2026-07-23, resolvido
até 2026-07-30 (data exata da correção não registrada — só a data de
revalidação).

## RESOLVIDO — Problema estrutural no JOIN da query de origem (afetava TIPO_RECOMENDACAO) — 2026-07-30
Não estava formalmente documentado neste arquivo antes (era conhecido
informalmente). O Hugo corrigiu um problema mais profundo no JOIN da query
que gera `tb_recomendacoes_painel_historico`, que afetava a classificação
de `TIPO_RECOMENDACAO` — como consequência, os volumes totais mudaram
significativamente:
- `ENTRADA_PAINEL`: **594.661 → 265.916** linhas (redução de ~55%),
  aproximando-se do valor real esperado de médicos elegíveis fora do
  painel (o volume antigo estava superestimado pelo JOIN incorreto).
- `REVISAO_PAINEL`: **280.192** linhas no estado atual.

Essa mudança de volume é **esperada, não é regressão** — é o efeito
correto da correção do JOIN. Como efeito colateral positivo, a correção
também parece ter resolvido o bug de `MOTIVO_RECOMENDACAO` documentado
anteriormente (ver RESOLVIDO específico abaixo).

## RESOLVIDO — MOTIVO_RECOMENDACAO com lógica incoerente (2 tentativas de correção) — 2026-07-30
Histórico do bug (preservado para rastreabilidade):
1. **Estado original:** 0 linhas na categoria incoerente, mas a
   nomenclatura ainda não tinha os 4 valores especificados (só 2 valores
   livres).
2. **1ª tentativa do Hugo:** reordenou as branches do `CASE`, mas não
   corrigiu a condição (`RANKING_SETOR <= 400` continuava errado na branch
   `REVISAO_SEM_VISITA_5_MESES`). Sintoma mudou de forma (0 → 153.775
   linhas incoerentes) sem resolver a causa raiz.
3. **Estado atual (revalidado 2026-07-30, provavelmente resolvido junto
   com o JOIN acima):** distribuição 100% coerente entre `TIPO_RECOMENDACAO`
   e `MOTIVO_RECOMENDACAO` no ciclo `202607`:
   - `ENTRADA_PAINEL` → `ENTRADA_RANKING_SETOR_ATE_400`: 265.916 (100%)
   - `REVISAO_PAINEL` → `REVISAO_RANKING_SETOR_ACIMA_400`: 130.668
   - `REVISAO_PAINEL` → `REVISAO_SEM_VISITA_5_MESES`: 146.853
   - `REVISAO_PAINEL` → `REVISAO_RANKING_SETOR_ACIMA_400_E_SEM_VISITA_5_MESES`: 2.671
   - **0 linhas** com combinação `TIPO`/`MOTIVO` incoerente.

   Confirmado também via API real: `GET /recomendacoes/revisao` para o rep
   `184430` (`luan.pereira@ache.com.br`) retorna 5 itens reais com
   `motivo_revisao = "REVISAO_SEM_VISITA_5_MESES"`, todos com
   `posicao_ranking <= 400` — confirma que a nova branch está acessível via
   API, não só via query direta.

**Mitigação do backend mantida mesmo assim** (defesa em profundidade,
resumo também em `.claude/rules/databricks.md`): `MOTIVO_RECOMENDACAO`
continua nunca sendo usado como filtro de consulta (`WHERE`), apenas como
campo de exibição — não depende mais de a fonte estar certa, mas não custa
manter.

## RESOLVIDO — QTD_MEDICOS_PAINEL_CICLO agregado nacional, não por rep
Já estava resolvido desde 2026-07-28 (ver abaixo) — revalidado em
2026-07-30: `MIN = 401`, `MAX = 993` para `REVISAO_PAINEL` no ciclo
`202607`, **0 violações** (`QTD_MEDICOS_PAINEL_CICLO <= 400`). Sem sinal de
regressão para o valor constante antigo.

## RESOLVIDO — Trava de 400 médicos no painel (REVISAO_PAINEL) — 2026-07-28
Confirmado por query: 0 violações (antes eram 63.622 de 205.790 linhas
violando a regra). `QTD_MEDICOS_PAINEL_CICLO` agora reflete valores reais
por propagandista (min 288, max 603), não mais um valor constante quebrado.
Mitigação de defesa em profundidade mantida no backend mesmo assim: filtro
explícito `WHERE QTD_MEDICOS_PAINEL_CICLO > 400` no endpoint de revisão,
como proteção contra regressão futura na fonte.

## RESOLVIDO — Permissão do SP nos 4 objetos novos — 2026-07-28
SP `sp-renovai-genie-api-poc` tem SELECT confirmado em
`tb_recomendacoes_painel_historico`, `vw_ranking_corte_hist`,
`vw_ranking_setor` e `vw_ultima_visita`, testado via token OAuth M2M direto.
`SHOW GRANTS` não mostrava isso por limitação de visibilidade da sessão de
inspeção (sem MANAGE), não por ausência real de grant. Ver
`docs/context/decisions-log.md`.

## RESOLVIDO — Fan-out eliminado
0 duplicatas por `CICLO_RECOMENDACAO + SETOR + UFCRM + TIPO_RECOMENDACAO`
(validado via `GROUP BY`/`HAVING COUNT > 1`).

## RESOLVIDO — Ranking recalculado por setor
`vw_ranking_setor` usa
`ROW_NUMBER() OVER (PARTITION BY SETOR ORDER BY SOMA_PONTUACAO DESC)`, sem
UFCRM como desempate — conforme especificado.

## RESOLVIDO — Corte de 400 aplicado corretamente
`vw_ranking_corte_hist` filtra `RANKING_SETOR <= 400`. Validado na tabela
final: ENTRADA_PAINEL max=400, REVISAO_PAINEL min=401.

## RESOLVIDO — vw_ultima_visita
Lógica correta: `MAX(data_visita)` por SETOR+UFCRM, filtrando
`visita_efetiva = 1`.

## RESOLVIDO — Bug de e-mail maiúsculo em tb_propagandistas — 2026-07-16
Ver `docs/context/decisions-log.md`. Corrigido em `auth/context.py` com
`WHERE LOWER(rep_email) = LOWER(:email)`.

---

## RESOLVIDO — Migração de código dos endpoints /entrada e /revisao — 2026-07-29
`routers/recomendacoes.py` agora usa `db/databricks_connection.py:get_engine()`
(respeita `DATA_SOURCE`) em vez de `create_engine(database_url)` hardcoded, e
as queries alternam tabela/colunas por fonte via `_schema()`, com alias SQL
para devolver sempre os nomes que `RecomendacaoItem` espera. Validado
end-to-end contra o Databricks real (`test_recomendacoes_integration.py` +
`uvicorn` local): conexão OK, todos os nomes de coluna corretos (incluindo
`ID_RECOMENDACAO`/`NOME_MEDICO`, que eram suposição e agora estão
confirmados por execução real), `/entrada` e `/revisao` respondem 200 com
payload estruturalmente coerente, `PROPAGANDISTA_NAO_ENCONTRADO` retorna 403.
`/revisao` corrigida: `ORDER BY` agora é `posicao_ranking DESC` (antes usava
`soma_pontuacao`, copiado por engano do endpoint de entrada) e ganhou o
filtro de defesa em profundidade `QTD_MEDICOS_PAINEL_CICLO > 400` (só
aplicado quando a fonte tem a coluna — schema local não tem equivalente).

## RESOLVIDO — Conteúdo real desbloqueado e validado — 2026-07-30
Com `STATUS_RECOMENDACAO` corrigido (ver acima), o conteúdo real dos dois
endpoints foi validado ponta a ponta contra o Databricks real:

**`GET /recomendacoes/revisao` — validado, pronto:**
- `curl` real (rep `185158`/`luisa.oliveira@ache.com.br`, ciclo `202607`):
  200 OK, 5 itens, `posicao_ranking` ordenado DESC (1396→1365), ≤5 itens.
- Cruzamento direto na fonte: **0 dos 15 itens retornados** (3 reps
  diferentes) violam `QTD_MEDICOS_PAINEL_CICLO > 400`.
- Motivo `REVISAO_SEM_VISITA_5_MESES` confirmado acessível via API (não só
  via query direta) — ver RESOLVIDO do MOTIVO_RECOMENDACAO acima.
- `test_recomendacoes_integration.py`: os 2 testes de revisão que ficavam
  em skip (`test_revisao_ordenada_por_posicao_ranking_desc`,
  `test_revisao_respeita_guarda_painel_maior_que_400`) agora **passam de
  verdade**, buscando um rep explicitamente elegível via query direta em
  vez de um e-mail aleatório (ver `_rep_elegivel()` no arquivo).

**`GET /recomendacoes/entrada` — 2026-07-30: bloqueado por 500
(NOME_MEDICO nulo). Atualização 2026-07-31: RESOLVIDO NA ORIGEM pelo Hugo,
ver seção "RESOLVIDO NA ORIGEM" acima** — o endpoint responde 200 com nomes
reais (fallback de defesa em profundidade continua no código, mas não é
mais exercido pelos dados reais).

## RESOLVIDO — default estático de CICLO_REFERENCIA — 2026-08-12
Descoberto durante a revalidação de 2026-07-30: o default `CICLO_REFERENCIA`
em `config.py`/`.env` (`202507`) não correspondia ao ciclo real mais recente
na fonte, e ficava obsoleto a cada rollover mensal — sem `?ciclo=`
explícito, os endpoints retornavam lista vazia mesmo com dado real
disponível. Mitigado em 2026-08-06 só atualizando o valor estático
manualmente (`202608`), o que não resolvia a causa raiz (voltaria a ficar
obsoleto no rollover seguinte).

**Resolvido de verdade em 2026-08-12** (`routers/recomendacoes.py`, função
nova `_ciclo_mais_recente()`): `/entrada` e `/revisao` agora resolvem
`SELECT MAX({ciclo_referencia}) FROM {tabela}` na própria fonte quando o
chamador não passa `?ciclo=` explícito — nunca mais depende do valor
estático de `settings.ciclo_referencia`. A capacidade de consultar um
ciclo específico via `?ciclo=` foi **preservada** (não removida): há
dependência real confirmada em `test_recomendacoes_integration.py` (3
usos programáticos) e no contrato documentado no `README.md`, então a
correção usa `MAX()` só como novo fallback, não substitui o parâmetro
explícito. Coberto por 4 testes novos em `test_recomendacoes.py`
(`test_entrada_sem_ciclo_usa_max_da_tabela`,
`test_entrada_com_ciclo_explicito_nao_consulta_max`, e os equivalentes de
`/revisao`).

**Escopo real do problema, mapeado em 2026-08-14: 4 lugares, não 1.**
Investigação de sincronização `renovai-local` ↔ `dev` encontrou mais 3
consumidores diretos de `settings.ciclo_referencia`, além de
`gerencial.py` (já sabido):

- **`genie/nl_to_sql.py:133` (`ciclo = settings.ciclo_referencia`, sem
  `or`, sem parâmetro de override nenhum) — era o mais grave: bug ativo,
  afetando todo usuário que interage com o Genie/chat, sempre, sem
  contorno possível.** Sozinho entre os 4, era o único sem nenhuma forma
  de mitigação — os outros aceitam `?ciclo=`/`--ciclo` explícito.
  **RESOLVIDO em 2026-08-14** — corrigido primeiro em `dev`
  (`AcheInfo_Apps/APP_RENOVAI`, o código que roda em homologação de
  verdade) e replicado para `renovai-local`, função nova
  `_ciclo_mais_recente(settings)` adaptada ao padrão deste módulo
  (Genie é simulação local, sempre via `create_engine(settings.database_url)`,
  sem a abstração dual-source `_schema()`/`col` de `recomendacoes.py`).
  Coberto por `test_nl_to_sql.py` (2 testes novos, nos dois ambientes):
  confirma que o ciclo no prompt reflete `MAX(ciclo_referencia)` de
  `tb_recomendacoes_painel`, não mais o valor estático, e que reflete
  mudança de ciclo entre chamadas (não fica cacheado/fixo).

- **`routers/gerencial.py`** — mesmo padrão (`ciclo = ciclo or
  settings.ciclo_referencia`) nos três endpoints (`/indicadores`,
  `/propagandistas`, `/recomendacoes`). **Ainda não corrigido**, fora de
  escopo da correção urgente de 2026-08-14 (não bloqueia em tempo real
  como o Genie bloqueava). Candidato a aplicar a mesma correção numa
  próxima task.

- **3 jobs em background** (`jobs/novo_ciclo.py`, `jobs/atualizar_status.py`,
  `jobs/gerar_recomendacoes.py`) — mesmo padrão, mas com `ciclo or`
  (aceitam `--ciclo` explícito na chamada manual, conforme os próprios
  docstrings de cada job documentam). **Ainda não corrigidos.** Gravidade
  real depende de como a automação de produção efetivamente dispara esses
  jobs (com ou sem `--ciclo` explícito) — não verificável só por leitura
  de código, precisa checar a configuração real do agendamento.

**Nota de comportamento (2026-08-12):** `_ciclo_mais_recente()` retorna
`None` se a tabela estiver vazia, resultando em lista vazia silenciosa
(`WHERE ciclo_referencia = NULL` nunca casa em SQL). Não é regressão do
comportamento anterior, mas é uma causa a descartar durante debug futuro
se um propagandista reportar lista vazia inesperada. Custo adicional: toda
chamada sem `?ciclo=` agora faz uma query extra (`MAX`) antes da
principal — aceitável, mas registrado caso volume de uso torne isso
relevante para otimização futura.

## RESOLVIDO — ampliação de escopo do REVISAO_PAINEL confirmada pelo George — 2026-08-06
Não era bug. O Hugo ampliou o critério de `REVISAO_PAINEL` para incluir
médicos com **ranking bom (≤400)** que estão no painel mas sem visita há 5+
meses (`REVISAO_SEM_VISITA_5_MESES`). Antes, o critério de `REVISAO_PAINEL`
considerava apenas ranking ruim (`> 400`,
`ABAIXO_CORTE`/`REVISAO_RANKING_SETOR_ACIMA_400`).

**Confirmação de negócio:** o George confirmou que "sem visita há 5 meses"
é regra real e intencional, e ele mesmo aplicou uma correção adicional na
condição: o médico só entra nessa regra se estiver há **5 ciclos
consecutivos no painel** — isso evita penalizar (marcar para revisão) um
médico recém-adicionado ao painel que ainda não teve tempo/oportunidade de
ser visitado.

**Execução oficial validada (2026-08-06):** rodada pelo notebook oficial do
Hugo (`notebookId 1296520715972786`), não mais por SQL solto como na
correção manual anterior do George. Distribuição de
`MOTIVO_RECOMENDACAO` no ciclo `202607`:
- `ENTRADA_RANKING_SETOR_ATE_400`: 287.232
- `REVISAO_RANKING_SETOR_ACIMA_400`: 107.691
- `REVISAO_SEM_VISITA_5_MESES`: 17.069
- `REVISAO_RANKING_SETOR_ACIMA_400_E_SEM_VISITA_5_MESES`: 4.753

`STATUS_RECOMENDACAO`: 100% `PENDENTE` (416.745 linhas) — esperado nesta
primeira carga completa pós-correção. Fan-out: 0 duplicatas. Trava de 400:
`MIN(RANKING_POSICAO_CICLO) = 401` para `REVISAO_PAINEL`. `NOME_MEDICO`: 0
nulos nos dois tipos. Médicos "nunca visitados" que caem na regra de
sem-visita têm exatamente 5 ciclos consecutivos no painel — regra
funcionando como especificado.

**Validação end-to-end via API real (2026-08-06, ciclo `202608` — o ciclo
rolou entre a validação técnica direta e esta validação de API):**
- `GET /recomendacoes/entrada?email=henrique.domingues@ache.com.br&ciclo=202608`
  (rep `187870`): 200 OK, 5 itens, nomes reais sem fallback, ordenado por
  `soma_pontuacao` DESC.
- `GET /recomendacoes/revisao?email=luan.pereira@ache.com.br&ciclo=202608`
  (rep `184430`, escolhido especificamente por ter a regra nova dominando
  seu top-5 por `posicao_ranking` DESC): 200 OK, 5 itens, **os 5** com
  `motivo_revisao = "REVISAO_SEM_VISITA_5_MESES"`, ordenado corretamente
  (234→206→197→102→86) — confirma que a regra corrigida do George está
  acessível de ponta a ponta via API, não só no dado bruto.
- Trava de 400 cruzada por fora, direto na fonte, para os 5 IDs retornados:
  todos com `QTD_MEDICOS_PAINEL_CICLO = 495 > 400` — defesa em profundidade
  continua funcionando mesmo com a nova regra.

**Observação sobre Cmd 12 do notebook (não é bug):** a célula usa um
placeholder `'<ID>'`, aparentemente pensada para parametrização externa
(execução via job/API com ID injetado), não uma célula quebrada ou
esquecida — registrar aqui para não ser confundida com problema novo numa
próxima leitura do notebook.

Nenhuma pendência de negócio remanescente neste item.

## NOTA DE MANUTENÇÃO — interpolação de `tabela` em resolver_contexto() — 2026-08-12
Não é bug. `auth/context.py`: `resolver_contexto()` interpola o parâmetro
`tabela` diretamente na query via f-string (`FROM {tabela}`). Seguro hoje
porque `_TABELAS_PERMITIDAS` (whitelist fixa: `tb_propagandistas`,
`tb_propagandista_teste`) é validada antes da execução, e o único chamador
que passa esse parâmetro é código de teste com valor fixo, nunca input de
usuário.

Se um futuro endpoint expuser esse parâmetro como entrada externa (query
param, body, etc.), a validação de whitelist precisa ser
mantida/reforçada antes disso — não trocar para SQL parametrizado
tradicional sem também preservar essa checagem, já que o nome de tabela
não pode ser parametrizado da forma usual (placeholder de valor) no
SQLAlchemy.

## ABERTO — Frontend Recomendacoes.tsx (branch do George) escrito contra contrato antigo — 2026-08-12
Não bloqueante, só registro para rastreabilidade futura. `frontend/src/pages/Recomendacoes.tsx`
(523 linhas) existe apenas na branch `feature/aba-recomendacoes` do George —
não incorporado ainda à árvore principal (`dev`/`APP_RENOVAI`). Foi escrito
contra o contrato do backend **dele** nessa branch: sem `LIMIT` (lista
completa), possivelmente com filtro de setor, contrato antigo de
`/desconsiderar` (resposta 501).

A decisão final da comparação (ver `docs/context/decisions-log.md`,
2026-08-12) manteve o contrato de `renovai-local` nos 3 pontos divergentes
(filtro de setor não adotado, `LIMIT 5` mantido no backend,
`/desconsiderar` com implementação completa em vez de 501) — não o do
George. Consequência: essa página **provavelmente precisará de ajuste**
quando for trazida para a árvore principal, para consumir o backend como
está hoje (com `LIMIT`, sem filtro de setor, contrato novo de
desconsiderar). Não é ação necessária agora — só registrar para quando a
incorporação do frontend for priorizada.

## ABERTO — bug no job gerar_recomendacoes (test_e2e_05_novo_ciclo_recorrencia) — achado durante sync com AcheInfo_Apps/APP_RENOVAI, 2026-08-12
`test_e2e_05_novo_ciclo_recorrencia` (`backend/app/tests/test_cenarios_completos.py`)
falha de forma determinística com `assert 0 >= 1` em
`resultado["entrada_incrementados"]` — o mock de `gerar_recomendacoes`
(job de recorrência de recomendação no novo ciclo) não está incrementando
o contador esperado. Confirmado como **pré-existente e sem relação** com
o trabalho de BARBARA-04/05, desconsiderar (161830/163626) ou registro de
envio do piloto: nenhum desses tocou `jobs/gerar_recomendacoes.py` nem
este teste, e o teste é 100% mockado (`patch(...create_engine...)`), sem
dependência de Postgres real.

**Achado adicional, ao mesclar os headers de sessão (`CABECALHO`) do
repositório `AcheInfo_Apps/APP_RENOVAI` de volta neste sandbox:** a versão
de `dev` desse mesmo teste tem `@pytest.mark.requer_banco` — marcador que,
via `conftest.py` de lá, faz skip automático quando o Postgres local não
está no ar. Como o teste é inteiramente mockado, esse marcador não deveria
ser necessário — a suspeita é que ele esteja mascarando esta mesma falha
pré-existente (skip silencioso em vez de vermelho visível), não resolvendo
a causa raiz no job. Mantido como está no merge de 2026-08-12 (fora do
escopo daquela sincronização, que era só sobre headers de auth) — comentário
inline deixado em `test_cenarios_completos.py` apontando para esta entrada.
Sugestão para quando alguém for corrigir o job: remover o marcador junto
com a correção, para o teste voltar a falhar visivelmente até o bug do job
ser corrigido de verdade.

## Próxima ação
1. ~~`NOME_MEDICO` nulo em `ENTRADA_PAINEL`~~ — **RESOLVIDO NA ORIGEM em
   2026-07-31**, ver seção acima. Nenhuma ação pendente neste item; o
   fallback de backend fica como defesa em profundidade permanente.
2. ~~Atualizar o default `CICLO_REFERENCIA`~~ — **RESOLVIDO DE VERDADE em
   2026-08-12** via `MAX(ciclo_referencia)` dinâmico, ver seção acima.
   Não é mais um valor estático que precisa de ajuste manual mensal.
3. ~~Levar a ampliação de escopo do `REVISAO_PAINEL` para confirmação com
   George/Bruno~~ — **RESOLVIDO em 2026-08-06**, ver seção acima. George
   confirmou a regra e aplicou a correção dos 5 ciclos consecutivos.
4. ~~Se algum dia o backend precisar consultar
   `dmn_inteligencia_dados_prd.gold.ranking_medicos_renovache_dim_medicos`
   diretamente: solicitar `USE CATALOG`~~ — **RESOLVIDO POR VIA
   ALTERNATIVA em 2026-08-12**, ver seção acima. George contornou com
   `tb_dim_medicos` (espelho local), sem precisar do GRANT cruzado.
5. Aplicar a mesma correção do item 2 (`MAX()` dinâmico) em
   `routers/gerencial.py` — mesmo known-issue, ainda não corrigido lá
   (ver seção "RESOLVIDO — default estático de CICLO_REFERENCIA" acima).
