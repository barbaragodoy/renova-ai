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
`especialidade` e `cidade` da dimensão original (correção de 2026-08-14:
**`uf` não vem dessa tabela** — `DESCRIBE EXTENDED` confirmou que
`tb_dim_medicos` só tem 4 colunas, `UFCRM`/`MEDICO`/`ESPECIALIDADE`/`CIDADE`;
`uf` é calculado como `LEFT(ufcrm, 2)` direto na query do George, sem
depender do espelho). `RecomendacaoItem` ganhou esses campos (mais
`meses_sem_visita`, calculado via `DATA_ULTIMA_VISITA_CONSIDERADA`, também
confirmada real) via `LEFT JOIN tb_dim_medicos`. Comentário dele confirma o
motivo: "o Service Principal do portal só lê acheinfo_dev.renovai e o
catálogo da dimensão original é vetado para ele".

**Incorporado em `renovai-local` em 2026-08-14** (`routers/recomendacoes.py`,
helpers `_fragmentos_dim_medicos()`/`_fragmento_meses_sem_visita()`) —
condicional por fonte via `_COLUNAS_POR_FONTE`: só o Databricks tem
`tb_dim_medicos`/`DATA_ULTIMA_VISITA_CONSIDERADA`, o Postgres local não tem
tabela nem coluna equivalente, então `especialidade`/`cidade`/`meses_sem_visita`
ficam sempre `None` lá (`uf` funciona nos dois lados, é só cálculo sobre
`ufcrm`). Aplicado em `/entrada`, `/revisao` e `/desconsideradas`. Testado
com integração real confirmando que o `LEFT JOIN` casa de verdade
(`test_especialidade_cidade_vem_preenchidos_para_pelo_menos_um_registro_real`).
Ainda não replicado em `dev`/`APP_RENOVAI` — decisão de quando fica para
depois.

**Ressalva de atualidade do dado, registrada em 2026-08-14:** o comentário
da própria tabela real confirma que a fonte original
(`dmn_inteligencia_dados_prd.gold.ranking_medicos_renovache_dim_medicos`)
está **parada desde 08/06/2026**, sem atualização automática agendada —
`tb_dim_medicos` é um espelho estático, feito uma vez em 11/08/2026. Médicos
que entrarem no ranking depois dessa data terão `especialidade`/`cidade`
vazios (`LEFT JOIN` sem match) — não é bug, é característica do dado atual,
mas vale acompanhar se isso afeta a experiência do piloto (ex.: se boa parte
dos candidatos a `ENTRADA_PAINEL` de ciclos futuros vier sem esses campos).

**Achado colateral, ao confirmar `DATA_ULTIMA_VISITA_CONSIDERADA` em
`tb_recomendacoes_painel_historico` (2026-08-14):** a tabela real já tem 3
das 5 colunas de desconsideração esperadas do Hugo —
`MOTIVO_DESCONSIDERACAO`, `BLOQUEAR_NOVAS_RECOMENDACOES` e
`DATA_DESCONSIDERACAO` já existem de verdade. Ainda faltam
`DESCONSIDERADO_POR` e `QTD_VEZES_DESCONSIDERADO`. Não investigado a fundo
agora — candidato a confirmação própria futura, fora do escopo desta
sincronização (pode significar que a migração do Hugo está parcialmente
em andamento).

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

## RESOLVIDO — regressão em test_prescricoes.py de dev — achada em 2026-08-14, corrigida em 2026-08-13
Ao trazer os módulos de sessão/perfil do George (`AcheInfo_Apps/APP_RENOVAI`)
para `renovai-local`, o diff de `test_prescricoes.py` em `dev` revertia
`EMAIL_VALIDO` de `"ana.lima@ache.com.br"` para `"ana.silva@ache.com.br"` e
removia o `pytestmark = pytest.mark.usefixtures("forcar_data_source_local")`
(junto do comentário que explica o motivo). `"ana.silva@ache.com.br"` nunca
existiu na seed local (`02_populate_propagandistas.sql`) — `resolver_contexto()`
roda de verdade nesse arquivo (não é mockado), então isso reintroduzia o
mesmo bug que motivou a correção original em `renovai-local`.

**Decisão inicial (2026-08-14): não replicado em `renovai-local`** — manteve
`EMAIL_VALIDO="ana.lima@ache.com.br"` e `forcar_data_source_local` como
estavam, trazendo só o que era necessário para o merge de CABECALHO/
requer_banco. Divergência intencional entre os dois ambientes nesse momento,
não um esquecimento.

**Corrigido em `dev` na Fase 3 da sincronização (2026-08-13):** aplicada a
mesma correção completa já validada em `renovai-local` — não bastava trocar
o valor de `EMAIL_VALIDO`, já que com `auth_mode=senha` a identidade vem
exclusivamente do token de sessão (`CABECALHO`), e o e-mail do corpo da
requisição é ignorado por `resolver_email_autenticado()`. A correção real
foi gerar um `CABECALHO` próprio do arquivo com `cabecalho(email=EMAIL_VALIDO)`
em vez do `CABECALHO` padrão compartilhado de `apoio_sessao.py`.

**Segundo achado, descoberto ao validar a correção acima contra `dev`:**
o padrão `new_callable=lambda: lambda: X()` usado nos 5 testes mockados de
`dev` está incorreto — `new_callable` precisa ser algo que, chamado sem
argumentos, devolve o substituto; aqui devolvia uma função que não aceita
os `kwargs` (`pergunta=`, `setor=`, etc.) que o router realmente passa,
causando `TypeError` em 5 dos 6 testes mesmo depois da correção de
identidade. Isso **confirma, com evidência concreta, a decisão tomada na
sincronização anterior de não adotar esse estilo de mock em
`renovai-local`** — não era diferença de convenção sem impacto, era um
`TypeError` ativo. Corrigido em `dev` na mesma correção do `EMAIL_VALIDO`
(2026-08-13), revertendo para `new=X()`, mesmo padrão já usado no resto do
projeto. `test_prescricoes.py` de `dev` confirmado 6/6 passando após as
duas correções.

## ABERTO — Segfault em test_recomendacoes_integration.py — agravado (2026-08-13)
Já documentado antes como intermitente; nesta sessão passou a ocorrer de
forma consistente no endpoint `/entrada`, mesmo com a correção de
identidade (`CABECALHO` dinâmico) aplicada corretamente. Não foi possível
confirmar empiricamente que a correção funciona neste arquivo por causa do
crash nativo (Arrow→pandas, `databricks-sql-connector`/`pyarrow`). Vale
investigar se houve mudança de versão de biblioteca ou ambiente (memória
disponível) desde a última vez que este teste rodou sem crash — antes de
depender dele para validação de regressão futura. Requer sessão de
investigação própria, fora do escopo de qualquer sincronização.

## NOTA DE AMBIENTE — Node.js instalado neste WSL — 2026-08-13
Node.js 20 LTS instalado via `apt`/NodeSource neste WSL (2026-08-13), não
via `nvm` como inicialmente planejado — decisão tomada durante a
sincronização, afeta o ambiente todo, não só este projeto. `npm audit`
reportou 1 vulnerabilidade "high" nas dependências do frontend (herdado de
`dev`, não introduzido agora) — não corrigido, fora de escopo desta
sincronização, vale revisar depois com `npm audit fix` ou análise manual.

## RESOLVIDO — 2 bugs reais achados em teste de ponta a ponta — 2026-08-14
Primeiro teste visual completo de `Recomendacoes.tsx` + backend, com
navegador de verdade (Playwright, instalado nesta sessão — não havia
nenhuma ferramenta de browser disponível antes). Achou 4 pontos fora do
esperado; 1 já documentado (ver entrada em `decisions-log.md`, 2026-08-12,
"Confirmado na prática"), 2 eram bugs reais de código (corrigidos abaixo),
1 não precisou de ação.

**Bug 1 — `DesconsideradaItem.bloquear_novas_recomendacoes` quebrava
`GET /desconsideradas` com 500.** Estava tipado como `bool` obrigatório,
mas a coluna real permite `NULL` de propósito ("NULL = sem decisão", ver
comentário da coluna). Reproduzido com 2 registros reais e antigos no
Postgres local (`motivo_desconsideracao = 'teste swagger'`, de
15/07/2026 — resíduo de teste manual anterior a este trabalho, sem
relação com nenhuma sincronização recente) que têm esse campo `NULL`.
Um único registro legado quebrava a listagem inteira para o usuário, sem
degradar graciosamente. **Corrigido:** campo virou
`Optional[bool] = None` em `schemas/recomendacoes.py`. Coberto por
`test_lista_desconsideradas_com_bloqueio_nulo_nao_quebra` (novo).
`DesconsiderarRequest.bloquear_novas_recomendacoes` (o campo do *corpo*
de `POST /desconsiderar`) não muda — esse continua `bool` obrigatório de
propósito, é regra de negócio diferente (entrada nova, não leitura de
dado histórico).

**Bug 2 — lista de Entrada/Exclusão não atualizava depois de "Reverter"
bem-sucedido.** O item sumia de Arquivadas corretamente e o backend
gravava certo (`status_recomendacao = PENDENTE`, confirmado direto no
banco), mas `entrada`/`exclusao` no frontend só eram buscadas uma vez no
carregamento inicial da tela — o item só reaparecia depois de recarregar
a página inteira (novo login). **Corrigido:** `reverterItem()` agora
chama `recarregarListasAtivas()` (função extraída, reaproveitada do
carregamento inicial) depois de um reverter bem-sucedido, em vez de
assumir que "o backend já garante" sem nenhuma ação do frontend — essa
premissa original estava errada. Decisão de design: recarregar via nova
chamada de API, não atualização otimista do estado local — evita
duplicar no frontend a regra de qual ciclo conta como vigente
(`_ciclo_mais_recente()`, que decide `PENDENTE` vs `EXPIRADA` no
backend).

**Achado 4 — toggle "Não recomendar novamente" parecia visualmente
desligado num screenshot logo após o clique — sem ação.** O valor salvo
no banco (`bloquear_novas_recomendacoes = true`) e o badge exibido depois
em Arquivadas confirmaram que o dado estava correto; provável só atraso
de renderização no instante exato do screenshot, não reproduzido como
problema funcional.

## ABERTO — hardening futuro: `_limite_painel()` retorna NULL silencioso se `tb_renovai_parametros` existir sem a linha ID=1 — 26/08/2026
Registrado a pedido explícito do usuário ao aprovar a Fase 3.5 da
sincronização com `merge/portal-agente-e-recomendacoes` (nota, não ação).

O comentário real da coluna `tb_renovai_parametros.LIMITE_PAINEL_PADRAO`
("o código deixa de ser um número e passa a ser erro declarado, para que
indisponibilidade não vire valor silenciosamente errado") sinaliza intenção
de **erro declarado** quando o parâmetro não está disponível. A fórmula
implementada (`COALESCE(pp.LIMITE_PAINEL, (SELECT LIMITE_PAINEL_PADRAO FROM
tb_renovai_parametros WHERE ID=1))`, aplicada em `routers/recomendacoes.py`,
`jobs/gerar_recomendacoes.py`, `genie/nl_to_sql.py` e `auth/perfil.py`) já
falha de verdade (exceção) se a tabela estiver inacessível — mas devolve
`NULL` em silêncio se a tabela existir sem a linha `ID=1`. Fechar essa borda
(fazer a ausência da linha também virar erro declarado) fica para uma
iteração futura, por decisão explícita de manter a fórmula exatamente como
especificada nesta sincronização.

## ABERTO — `auth/perfil.py` não roda contra Postgres local: `tb_propagandistas` sem 11 colunas — achado em teste de fumaça real, 26/08/2026
Pré-existente (código de `auth/perfil.py`, commit `fac188c`, anterior a
qualquer trabalho desta sincronização) — só descoberto agora porque foi a
primeira vez que alguém rodou a API de verdade contra `DATA_SOURCE=local`
com token de sessão real. `_CAMPOS_PESSOA` (base de `GET/PUT /auth/perfil`
e `PUT /auth/perfil/limite-painel`) seleciona `p.linha_produto,
p.rep_login, p.gd_nome, p.gd_email, p.gr_nome, p.gn_nome, p.cargo,
p.regional, p.uf, p.linha_nome, p.cidades_setor, p.especialidades_setor` de
`tb_propagandistas` — nenhuma dessas 11 colunas existe na tabela local
(`data/scripts/01_create_tables.sql` só tem `rep_matricula, rep_email,
setor, cod_linha, rep_nome, ativo`). Erro real:
`psycopg2.errors.UndefinedColumn: column p.linha_produto does not exist`.

Fora de escopo da sincronização de Chat/Ranking/Agente de 26/08/2026 (que
tratou só das tabelas novas dessas 3 features) — registrado aqui para quando
a aba Usuário completa (nome editável, limite de painel, foto) for
priorizada para teste local de ponta a ponta. Precisaria ampliar
`tb_propagandistas` local com as 11 colunas e popular dado realista.

## RESOLVIDO — dialeto SQL Databricks vs Postgres no código novo do George — 26/08/2026
Achados em teste de fumaça real (API rodando de verdade contra
`DATA_SOURCE=local`, não só suíte mockada) ao trazer Chat/Ranking/Agente.
Todos corrigidos, sem alterar o comportamento em nenhuma das duas fontes:

- **Qualificação de catálogo** (`acheinfo_dev.renovai.tabela` ou
  `f"{catalog}.{schema}.tabela"`) quebra contra Postgres (identificador de 3
  partes não existe lá) — removida em `chat/perfil_medico.py`,
  `routers/agente.py`, `routers/chat.py`; nomes sem qualificação já resolvem
  certo nos dois lados via `connect_args` (Databricks) / `search_path`
  (local). Ver `agente/ferramentas.py::Ferramentas._qualificar()`.
- **Convenção de maiúsculas mista entre objetos reais**: tabelas mais
  antigas (`tb_perfil_medico_setor`, `tb_ranking_medicos_validacao`,
  `tb_dim_medicos`) têm coluna maiúscula real; as mais novas
  (`tb_conduta_medico`, `tb_segmentacao_medico`, `tb_agente_persona`,
  `vw_segmentacao_efetiva`) têm coluna minúscula real — confirmado via
  `DESCRIBE EXTENDED`. Postgres sempre devolve minúsculo para identificador
  sem aspas, então acesso por `["MAIUSCULO"]` quebrava com `KeyError`
  contra local. Corrigido na borda (`chat/executor.py::ExecutorDoPortal`),
  acrescentando a chave maiúscula ao dict sem remover a original — resolve
  as duas convenções sem tocar nenhuma query.
- **`MERGE ... WHEN MATCHED THEN UPDATE SET destino.coluna = valor`**:
  Databricks aceita a coluna alvo qualificada pelo alias do destino,
  Postgres 15 não (`column "destino" of relation ... does not exist`) — só
  o lado direito (leitura do valor antigo) pode ficar qualificado. Corrigido
  em 4 MERGEs (`auth/perfil.py` × 3, `auth/foto.py`, `routers/ranking.py`).
- **`current_timestamp()`** (com parênteses) é erro de sintaxe no Postgres
  (é palavra reservada, não função) — trocado por `current_timestamp` (sem
  parênteses, válido nos dois) em todas as ~10 ocorrências dos arquivos
  acima.
- **`uuid()`** só existe no Databricks — `routers/ranking.py` (INSERT em
  `tb_conduta_medico`) passou a gerar o UUID em Python
  (`str(uuid.uuid4())`) e passar como parâmetro, funcionando igual nas duas
  fontes sem chamar função SQL nenhuma para o id.
- **`CAST(:x AS STRING)` / `CAST(:x AS INT)`**: `STRING`/`INT` não são tipo
  válido no Postgres (`TEXT`/`INTEGER`) — `agente/registro.py::sql_merge()`
  passou a escolher o nome do tipo conforme `settings.data_source`. Sem
  isto, toda gravação em `tb_agente_log` falhava contra local — ou seja,
  toda interação real com o chat/agente, não um caso de borda.
- **Subquery em `FROM` sem alias**: Databricks aceita, Postgres exige
  (`subquery in FROM must have an alias`) — corrigido em
  `routers/ranking.py` (subquery de conduta mais recente por
  setor+ufcrm).

## RESOLVIDO — `test_revisao_respeita_guarda_painel_maior_que_400` desatualizado — achado e corrigido em 26/08/2026
`test_recomendacoes_integration.py` (roda contra Databricks real) falhou
com `assert 368 > 400` — pré-existente, sem relação com a sincronização de
Chat/Ranking/Agente (não tocou `routers/recomendacoes.py` além do já
documentado na Fase 3.5, nem este teste).

**Causa confirmada por reprodução manual direta contra o Databricks real**
(não hipótese): o rep elegível do teste (matrícula `182749`,
`joao.trisnoski@ache.com.br`) não tem linha em `tb_perfil_portal`, então
`_limite_painel()` resolve para o default de `tb_renovai_parametros`
(**318**, não 400). O item que o endpoint `/recomendacoes/revisao`
devolveu tem `QTD_MEDICOS_PAINEL_CICLO = 368` — **368 > 318** (passa no
filtro real do endpoint, `AND QTD_MEDICOS_PAINEL_CICLO > :limite_painel`,
código de `routers/recomendacoes.py` já existente desde a Sprint 6,
24/08/2026, não alterado por esta investigação) mas **368 ≤ 400** (viola a
asserção antiga do teste). Confirma que é o teste desatualizado, não bug de
código: a trava real do endpoint sempre foi o limite por propagandista, não
400 — só a asserção do teste não tinha acompanhado a mudança da Sprint 6, e
por isso ficou dormente até a fonte real trazer um propagandista sem
personalização com painel entre 319 e 400 (cenário que passou a ser
elegível para revisão desde a Sprint 6, não antes).

**Corrigido:** o teste (renomeado para
`test_revisao_respeita_guarda_painel_maior_que_o_limite_do_propagandista`)
agora resolve o limite real via `_limite_painel()` — a mesma função que o
endpoint usa — em vez de comparar contra outro número fixo no lugar do 400.
Suíte completa reconfirmada 340 passed / 1 failed (só o
`test_e2e_05_novo_ciclo_recorrencia` pré-existente, documentado acima) após
a correção.

## NOTA — `test_golden_set.py` aponta um diretório acima do correto — achado em 26/08/2026
Pré-existente desde o primeiro commit do repositório (`fc06059`), sem
relação com nenhuma sincronização. `GOLDEN_SET_PATH = Path(__file__).parents[4]
/ "docs" / "cenarios" / "golden_set.json"` resolve para
`/home/admin/projetos/docs/cenarios/golden_set.json` (um nível acima de
`renovai-local/`), mas o arquivo real está em
`renovai-local/docs/cenarios/golden_set.json` — `parents[4]` deveria ser
`parents[3]`. Quebra a coleção do pytest para a suíte inteira
(`FileNotFoundError` na importação do módulo) se o arquivo não for
explicitamente ignorado (`--ignore=backend/app/tests/test_golden_set.py`).
Não corrigido nesta sincronização — fora de escopo, só registrado para não
ser confundido com problema novo.

## ABERTO — Twilio/WhatsApp: sem credencial de produção — Sprint 7, 28/08/2026
`TWILIO_ENV=production` não é suportado hoje por decisão explícita, não
por esquecimento: `get_twilio_config()`
(`backend/app/integrations/whatsapp/config.py`) recusa esse valor com
`TwilioConfigError` clara em vez de deixar a Twilio devolver um erro de
autenticação confuso na hora do envio. Não existe conta/número de
WhatsApp de produção aprovado ainda — só o ambiente sandbox está
configurado. Quando a conta de produção existir, `get_twilio_config()`
precisa ganhar o caminho `production` de verdade (hoje só sandbox lê
`TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/etc. do ambiente).

**Achado colateral, não bloqueante:** nesta sessão, `env | grep -i
twilio` não mostrou nenhuma variável `TWILIO_*`, apesar de a
instrução da task afirmar que já estavam exportadas localmente. Não
investigado a fundo — mais provável escopo de subprocesso do Bash tool
não herdando o shell interativo onde as variáveis foram exportadas do
que ausência real. Não bloqueou o desenvolvimento (nenhum teste
automatizado bate na API real — ver `test_whatsapp_service.py`), mas
quem for rodar `data/scripts/testar_envio_whatsapp_sandbox.py` precisa
confirmar que as variáveis estão visíveis no shell usado para isso.

## NOTA DE SEGURANÇA — headers do Easy Auth exigem proteção da plataforma — Task 170097

No modo `AUTH_MODE=entra_id`, o backend confia em
`X-MS-CLIENT-PRINCIPAL-NAME` e, como fallback,
`X-MS-CLIENT-PRINCIPAL`. Isso é seguro em homologação/produção somente
enquanto o App Service Easy Auth estiver configurado com
`Require authentication`, bloqueando requisições não autenticadas antes do
FastAPI.

Se a API for exposta diretamente — inclusive localmente — esses headers
podem ser forjados pelo cliente. Portanto, `AUTH_MODE=entra_id` não deve ser
tratado como proteção suficiente sem Easy Auth na frente.

**PRECISA DE VALIDAÇÃO COM LOGIN REAL:** confirmar se
`X-MS-CLIENT-PRINCIPAL-NAME` sempre contém o UPN puro no ambiente da Aché ou
se o fallback pelo claim `upn` de `X-MS-CLIENT-PRINCIPAL` é exercitado.

`AUTH_EMAIL_CLAIM=preferred_username` está desatualizado, mas não participa
do fluxo real de `entra_id`. Ele pertence somente ao caminho legado
`AUTH_REQUIRE_JWT`/JWKS e fica intocado nesta task.

## ABERTO — caminho legado JWKS não valida issuer como documentado

`auth/jwt_auth.py::_extrair_email_do_token()` informa no comentário que
valida issuer, mas a chamada de `jwt.decode()` não recebe `issuer=`.
Esse caminho é legado e não é usado por `AUTH_MODE=entra_id`; registrado
para correção futura, sem alteração na Task 170097.

## RESOLVIDO (2026-09-23) — redirect URI de pedai.ache.com.br

Confirmado via `az ad app show --id a702ad79-643d-4361-831a-95d7bca3b2b6
--query "web.redirectUris"` que `https://pedai.ache.com.br/.auth/login/aad/callback`
e `https://asp-renoveai-hmg.azurewebsites.net/.auth/login/aad/callback` já
estão registrados no App Registration. `GET /.auth/login/aad` em
`asp-renoveai-hmg` redireciona corretamente para
`login.microsoftonline.com` com `client_id`/`redirect_uri` batendo com o
registrado — sem sinal de `AADSTS50011` nessa etapa. Não foi completado um
login interativo real de ponta a ponta (sem credencial/browser disponível
nesta verificação), então a condição 2 da decisão de 15/09/2026 abaixo
("validação com login real confirmando qual header o Easy Auth entrega")
continua em aberto — só o bloqueio externo do redirect URI está resolvido.

## SUPERADO (2026-09-24) — não ativar AUTH_MODE=entra_id em homologação ainda

**Superado em 24/09:** as duas condições foram cumpridas (header real
confirmado no Log Stream; STATUS_ACESSO publicado) e a virada foi executada
às 11:49 UTC. Texto original abaixo.

A imagem pode conter o código da Task 170097, mas `AUTH_MODE` deve permanecer
`senha`. O bloqueio de redirect URI foi resolvido (ver entrada acima,
2026-09-23), mas isso sozinho não autoriza a virada: falta (1) validar um
login real confirmando o formato do header do Easy Auth, e (2) implementar a
checagem de `STATUS_ACESSO`/`PERFIL_ACESSO` — hoje `resolver_contexto()` só
confere `tb_propagandistas`, sem olhar status de acesso, então ativar
`entra_id` sem essa checagem abriria o portal para os ~2.154 propagandistas
reais com conta corporativa válida, não só os ~72 aprovados para o piloto
(72 `ATIVO`, 2.087 `BLOQUEADO`, contagem real em `tb_perfil_portal` conferida
em 2026-09-23). Ativar `entra_id` sem essas duas condições resolvidas
desativaria o login por senha sem garantia de que o Entra ID funcione
corretamente no lugar, ou com o controle de acesso certo.

Decisão completa registrada em `docs/context/decisions-log.md`, entrada
“2026-09-15 — Deploy da Task 170097 em homologação mantém AUTH_MODE=senha”.

**Atualização 2026-09-24:** a condição (2) está resolvida. A checagem de
`STATUS_ACESSO`/`PERFIL_ACESSO` foi implementada e publicada em hmg (imagem
`b9342ea-status-acesso-debug-20260924`). Ela não ficou em
`resolver_contexto()`, e sim em `jwt_auth.py::resolver_email_autenticado()`
e `POST /auth/login`, sobre a identidade real. Ver decisions-log de 24/09.
A condição (1) continua aberta, e surgiram duas pendências novas antes da
virada: o fallback `upn` (entrada abaixo) e a imagem gerada sem
`VITE_AUTH_MODE` (entrada abaixo).

## RESOLVIDO (2026-09-24) — claim `upn` não existe no token real da Aché

`/.auth/me` com a conta `3gobarbara@ache.com.br` mostrou a lista completa de
claims: nenhum `typ="upn"`. O login está em `preferred_username`
(`3gobarbara@ache.com.br`). `emailaddress` traz outro valor
(`barbara.godoy_terceiro@ache.com.br`) e **não** serve para comparar com
`REP_LOGIN`: usar esse claim quebraria a identidade de qualquer usuário na
mesma situação (terceiros, por exemplo).

O fallback de `jwt_auth.py::_extrair_upn_do_client_principal()` procura só
`upn`, então nunca acha nada nesse tenant. O caminho principal lê
`X-MS-CLIENT-PRINCIPAL-NAME`, mas o valor real desse header ainda **não foi
observado**: pode ser `preferred_username` ou o `name` de exibição
("Barbara Godoy"), que seria inutilizável. O log temporário `EASY_AUTH_DEBUG`
está publicado em hmg para capturar esse valor. A tentativa de 24/09 parou
porque o Entra ID bloqueou o login (Smart Lockout ou política de horário).

Correção prevista depois da evidência:
- Se o header vier com `preferred_username`: trocar só o fallback, de `upn`
  para `preferred_username`.
- Se vier com `name`: deixar de confiar no header simples, decodificar
  `X-MS-CLIENT-PRINCIPAL` e extrair `preferred_username` direto.

**Evidência (24/09):** o buffer do Log Stream guardou 11 requisições
autenticadas da Bárbara entre 05:25 e 05:38 UTC, anteriores ao bloqueio.
Todas registraram `X-MS-CLIENT-PRINCIPAL-NAME='barbara.godoy_terceiro@ache.com.br'`,
ou seja, o **`emailaddress`**. Esse caso não constava da lista acima e é pior
que o `name`, porque tem forma de e-mail. O payload trazia
`preferred_username='3gobarbara@ache.com.br'` e nenhum `upn`.

**Corrigido (24/09; `dev` `aad27c5`, em hmg desde 11:49 UTC):** `jwt_auth.py` não lê mais
`X-MS-CLIENT-PRINCIPAL-NAME`. A identidade vem de `X-MS-CLIENT-PRINCIPAL`,
pelo claim `preferred_username` e, na falta dele, por `upn`. Sem nenhum dos
dois, responde 401. O log `EASY_AUTH_DEBUG` foi removido. Os testes cobrem
o payload real e garantem que o header `-NAME` sozinho não autentica.

## RESOLVIDO (2026-09-24) — 3 administradores gravados com e-mail em vez do UPN

**Resolução (24/09, 07:12 UTC):** INSERT em `acheinfo_dev.renovai.tb_perfil_portal`
com `CGMACezar@ache.com.br` e `PFEduardo@ache.com.br`, `ATIVO`/`ADMINISTRADOR`,
`ACESSO_LIBERADO_POR='3gobarbara'`. Conferido por SELECT. As 3 linhas antigas,
com o e-mail, foram mantidas. Reversão: `DELETE ... WHERE REP_EMAIL IN
('CGMACezar@ache.com.br','PFEduardo@ache.com.br')`.


Domínio não é o problema. `biosintetica.com.br` é domínio verificado no mesmo
tenant da Aché. O caminho do propagandista corta no primeiro `@` e compara
com `REP_LOGIN`, que é único e não se repete entre domínios. O problema é o
**formato** gravado para administradores.

O fallback de administrador (`status_acesso.py`) compara a identidade inteira
recebida do Easy Auth com `tb_perfil_portal.REP_EMAIL`. Consulta de leitura
ao Entra ID (`az ad user show`) em 24/09, para os 13 administradores:

- **10 linhas estão gravadas com o UPN.** Exemplos: `3gobarbara@...`,
  `alcaio@...`, `feorafael@...`. O UPN é um código de login, e o `mail` é
  nome.sobrenome (`_terceiro` para terceiros). Isso vale para terceiros e
  também para funcionários, e bate com o que se viu no token: o
  `preferred_username` é o UPN, e o `emailaddress` é o `mail`.
- **3 linhas estão gravadas com o `mail`, que não é o UPN:**

| `REP_EMAIL` gravado | UPN real no Entra ID |
|---|---|
| `cezar.moreira@ache.com.br` | `CGMACezar@ache.com.br` |
| `cezar.moreira@biosintetica.com.br` | `CGMACezar@ache.com.br` |
| `eduardo.pavan@ache.com.br` | `PFEduardo@ache.com.br` |

Com `AUTH_MODE=entra_id`, Cezar e Eduardo chegariam como `CGMACezar@...` e
`PFEduardo@...`, não achariam linha e seriam bloqueados (sem linha, o acesso é
negado). A comparação usa `LOWER()`, então as maiúsculas não importam.

Correção recomendada: no dado, não no código. Gravar o UPN no `REP_EMAIL`
dessas linhas de `tb_perfil_portal`. As linhas de e-mail podem ficar ou ser
removidas, porque não fazem mal. Não se recomenda aceitar `emailaddress` como
segunda chave: isso abriria outro identificador justamente no ponto de
controle de acesso. Precisa ser feito antes da Fase 4.

O padrão "UPN = código de login" também reforça a premissa do caminho do
propagandista (prefixo do UPN = `REP_LOGIN`, que difere do prefixo do e-mail
em 97% dos casos). Mas isso só fica confirmado com a captura do header real
(Fase 2).

## RESOLVIDO (2026-09-24) — imagem não recebe `VITE_AUTH_MODE`

O Dockerfile de `APP_RENOVAI` roda `npm run build` sem `ARG`/`ENV` para
`VITE_AUTH_MODE`, e `.env` está no `.dockerignore`. Toda imagem sai com a
tela de login por senha, inclusive a de 24/09. Na virada, trocar só
`AUTH_MODE=entra_id` deixaria a tela pedindo senha e o backend respondendo
404 em `POST /auth/login`. A imagem da virada precisa ser gerada com
`VITE_AUTH_MODE=entra_id` (via `ARG` no Dockerfile ou arquivo de build
versionado). **Corrigido em 24/09** (`dev` `baa063a`) com `ARG
VITE_AUTH_MODE=senha` + `ENV` antes do `npm run build`. `vite build` com
`VITE_AUTH_MODE=entra_id` gera o link `/.auth/login/aad`, e com `senha`, não.
Imagem da virada: `az acr build ... --build-arg VITE_AUTH_MODE=entra_id`.

## RESOLVIDO (2026-09-24) — 403 na personificação com `entra_id`

Em hmg (13:26 UTC), ao personificar um propagandista, `/ranking` e
`/recomendacoes/*` davam 403: `aplicar_personificacao()` devolve o
`REP_EMAIL` do alvo e, em `entra_id`, `resolver_contexto()` buscava por
`REP_LOGIN` (`sandro.menezes` x `MSandro`) → `PROPAGANDISTA_NAO_ENCONTRADO`.
Corrigido em `dev` `d416de6`: a personificação marca o e-mail do alvo
(ContextVar, só depois de confirmar administrador) e `resolver_contexto()`
busca essa identidade por `rep_email`. Validado em hmg com 3 administradores.

## RESOLVIDO (2026-09-24) — perfil e foto não achavam propagandista em `entra_id`

`auth/perfil.py` e `auth/foto.py` buscam por `rep_email`; em `entra_id` a
identidade é o UPN. `email_cadastrado()` (`auth/context.py`, `dev`
`91bedaf`) troca o UPN pelo `REP_EMAIL` do mesmo `REP_LOGIN`. Coberto por
teste; ainda sem login real de propagandista (Fase 5).

## RESOLVIDO (2026-09-24) — login bloqueado sem tela em `entra_id`

`resolverEntrada()` devolvia `estado: "bloqueado"`, mas `Login.tsx` não
tratava esse estado no modo `entra_id` (cartão vazio; após o PR 23965, botão
em loop). `dev` `4316976` mostra `AcessoBloqueado`. Não visto em navegador.

## ABERTO (2026-09-24) — front local não usa mais a API de hmg sem cookie

Com `RedirectToLoginPage`, o proxy do Vite apontando para hmg recebe 401 (o
Easy Auth descarta `X-MS-CLIENT-PRINCIPAL` vindo de fora). `dev` `ec6eea5`:
`DEV_EASY_AUTH_COOKIE` repassa o cookie `AppServiceAuthSession` copiado do
navegador; `DEV_EASY_AUTH_LOGIN` simula o header com API local. Sem cookie e
com cookie inválido: 401 (conferido). Com cookie válido: **não testado**.

## ABERTO (2026-09-24) — decisões pendentes do PR 23965 (login Figma)

Mesclado como veio (`dab8eb2`). A decidir com o Thiago: (1) a tela só
confere a sessão sozinha se o clique ocorreu na mesma aba, então após o
redirect do Easy Auth e em todo F5 há um clique extra; (2) marca "PedAI" e
logo "R" vs "Ped.AI"; (3) texto de termos/privacidade sem link; (4) botões
de aceitar/desconsiderar ativos em sessão personificada, que a API recusa
com 403 (`escrita bloqueada em sessao personificada`, 4 vezes em 24/09).

## RISCO ACEITO (2026-09-24) — 25 usuários do piloto por senha bloqueados em hmg

Os 25 e-mails de `acessos.csv` existem em `tb_propagandistas`, e **todos**
estão `BLOQUEADO` em `tb_perfil_portal` (consulta real no Databricks em
24/09). São uma população disjunta dos 72 `ATIVO`. Com a imagem de 24/09,
`POST /auth/login` responde 403 `ACESSO_BLOQUEADO` para os 25, mesmo com a
senha certa. A Bárbara aceitou esse efeito porque ninguém usa essas
credenciais em homologação. Se o login por senha voltar a ser necessário
antes da virada, é preciso liberar essas linhas em `tb_perfil_portal` ou
publicar uma imagem sem a checagem no login por senha.

## RESOLVIDO (2026-09-24) — `renovai-local` atrás de `dev` em trabalho de terceiros

**Resolução (24/09, tarde):** frontend e backend trazidos de `dev` (`91bedaf`)
por merge de 3 vias. A base de cada arquivo foi a última versão comum aos
dois históricos. `frontend/src/` ficou idêntico ao de `dev`. No backend, as
únicas diferenças que restam existem só no local: WhatsApp/Twilio (Sprint 7),
`agente/modelo.py` (`extrair_estruturado`) e o import de `webhooks_twilio` em
`main.py`. Com isso, as 5 falhas de `test_gerar_recomendacoes.py`
(`KeyError: 'T0006'`) passaram a aparecer também no local, como em `dev`.
Texto original abaixo.


A sincronização de 24/09 mostrou código que existe só em `AcheInfo_Apps/dev`:
busca de médico (`App.tsx`/`Home.tsx`), reversão de aceite
(`test_reverter.py` e o router correspondente), `ciclo_referencia` 202608 em
`config.py`, branding `Ped.AI` (inclusive em `Header.tsx`/`MenuLateral.tsx`)
e `test_gerar_recomendacoes.py`. Esse último tem 5 falhas que já existiam em
`dev` (`KeyError: 'T0006'`), conferidas antes e depois da sincronização. As
próximas sincronizações precisam de merge de 3 vias, e não de cópia de
arquivo, até que isso seja trazido para `renovai-local`.

## RESOLVIDO (2026-09-24) — reverter unauthenticated-client-action depois do trabalho do Thiago

**Resolvido:** `RedirectToLoginPage` ativado junto com `AUTH_MODE=entra_id`
em 24/09, 11:49 UTC. Texto original abaixo.

Há uma decisão temporária de usar `AllowAnonymous` no Easy Auth de
`asp-renoveai-hmg` para permitir o trabalho na tela de login. Reverter para
`RedirectToLoginPage` após a conclusão desse trabalho. Enquanto isso,
manter `AUTH_MODE=senha`; nunca ativar `entra_id` sem a barreira de
autenticação da plataforma. Ver a entrada de 2026-09-16 em
`docs/context/decisions-log.md`.

Estado conferido em 24/09 via `az webapp auth show`:
`requireAuthentication=true` e `unauthenticatedClientAction=AllowAnonymous`.
Na virada (Fase 4), `AUTH_MODE=entra_id` e `RedirectToLoginPage` mudam
juntos. No rollback, os dois voltam juntos (`senha` e `AllowAnonymous`),
porque com `RedirectToLoginPage` até a tela de senha fica atrás do login da
Microsoft.

## ABERTO — massa local ausente para testes de registro de envios

Quatro testes de `test_registro_envio.py` dependem de massa previamente
carregada no Postgres local: recomendações reais para `REP005`, `REP006`
e `REP008`, além dos grupos-piloto `WHATSAPP`, `EMAIL` e `CONTROLE`.

Sem essa carga, os testes falham antes de exercitar as operações que
pretendem validar. Em 15/09/2026, as alterações da Task 170097 foram
guardadas com `git stash` e os quatro testes foram executados contra o
código anterior; todos falharam com as mesmas mensagens. Portanto, trata-se
de uma pendência preexistente da massa local, sem relação com a implementação
de autenticação por Entra ID. Não corrigida nesta task.

## SUPERADO (2026-09-24) — botão Microsoft visível ainda não completa o login do portal

**Superado:** hmg está em `entra_id` desde 24/09 e o login Microsoft é o
único caminho. Texto original abaixo.

O PR 23635, mesclado em 17/09/2026, adiciona um link ativo para
`/.auth/login/aad` na tela que também mostra o formulário de e-mail e
senha. Em homologação, `AUTH_MODE=senha` continua ativo e Easy Auth está
em `AllowAnonymous`; mesmo após uma autenticação Microsoft, o frontend
não cria o JWT de sessão próprio exigido pelas rotas de negócio. O redirect
URI de `pedai.ache.com.br` foi confirmado registrado em 2026-09-23 (ver
entrada acima), então esse risco específico de `AADSTS50011` não se aplica
mais — mas o login por Entra ID continua inativo por `AUTH_MODE=senha`. O
usuário decidiu manter o botão visível por enquanto,
sem ativar `AUTH_MODE=entra_id`. Não confundir o rótulo "Funcionalidade em
desenvolvimento" com um botão desabilitado: o link é clicável.

## 2026-09-17 — Estado do botão Microsoft antes do próximo build

Há um ajuste local, ainda sem commit nem deploy, que mantém o botão Microsoft
visível e o torna desabilitado. O link ativo incluído no PR 23635 permanece na `dev` remota até o commit
do ajuste; o novo comportamento só chegará à homologação após build e troca
de imagem.
`AUTH_MODE=senha` e Easy Auth `AllowAnonymous` continuam necessários.

## 2026-09-17 — baseline após sincronização dos PRs 23635/23670

A coleta da suíte completa continua bloqueada pelo caminho incorreto de
`test_golden_set.py` descrito acima. Com esse arquivo ignorado, o resultado
foi 476 passed / 5 failed / 3 skipped. As falhas são
`test_e2e_05_novo_ciclo_recorrencia` e os quatro testes de
`test_registro_envio.py` dependentes de massa local ausente, todos
preexistentes e documentados. A checagem TypeScript do frontend
(`npm run lint`) passou. Nenhuma falha nova foi identificada.

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

## 2026-09-17 — ABERTO: latência de login e listas em homologação

O login real funciona. Em janelas de 5 minutos às 15:25, 15:30, 15:45 e
16:00 UTC, as médias de resposta foram 11,58, 9,75, 13,74 e 8,98 s, com
12, 4, 2 e 4 requisições e zero 5xx. CPU média do plano nessas janelas:
14,4%, 8,8%, 8,6% e 8,6%; memória ~66–67%; fila HTTP zero.

No código, o login faz PBKDF2 e uma consulta de cadastro ao Databricks;
o hash sintético local levou mediana de 0,17 s. A primeira abertura de
Recomendações dispara duas listas e um perfil, totalizando cerca de 10–11
consultas SQL. O cliente mantém abas visitadas montadas, portanto voltar
a uma aba não deve repetir essas buscas sem outra ação.

`/`, `/health` e `/docs` tiveram mediana próxima de 0,78 s fim a fim
no terminal local, incluindo ~0,58 s de TLS. O JavaScript principal tem
311.187 bytes e foi servido sem compressão; compressão gzip local o
reduziria para cerca de 90.838 bytes. O arquivo tem cache longo.

Não há logs HTTP nem diagnóstico por rota habilitados. Esta sessão não
dispõe de CLI ou variáveis Databricks para medir duração/espera das
consultas no warehouse. A hipótese principal é custo acumulado das
idas ao Databricks, ainda não comprovada por consulta. Medir tempo por
rota e etapa SQL sem registrar textos, parâmetros ou identidade antes
de escolher cache ou alterar infraestrutura.

## 2026-09-17 — Complemento: medições no Databricks real

O `.env` de `renovai-local` foi usado apenas em processos de teste, sem
exibir valores. O código executado veio da cópia Aché implantada.
Criar a engine levou 3,82 s; primeira conexão 3,33 s e SELECT 1,
0,75 s. Com pool aquecido, conexões levaram 0,34–0,37 s e SELECT 1,
~0,35 s. Consulta de cadastro: 1,02 s; perfil: 5,38 s (uma SQL de
5,04 s); entrada: 4,94 s (quatro SQL); revisão: 4,71 s (seis SQL);
ranking: 3,84 s (três SQL). Abertura paralela de entrada, revisão
e perfil: 5,35 s inicialmente e 3,48 s com pool aquecido.

Uma amostra com recomendações pendentes trouxe 36 itens de entrada em
3,25 s e 50 de revisão entre 224 em 4,52 s. O warehouse está em
2X-Small serverless, auto-stop de 5 minutos. Seu histórico mostrou
consultas de até 20,45 s e eventos de fila de provisionamento; o texto
SQL está oculto para esta identidade, impedindo mapear cada evento
histórico a uma rota. Estas medições confirmam custo no Databricks;
o peso exato de cada rota em homologação ainda requer correlação.

## 2026-09-17 — Comparação do Perfil com e sem resumos

No Databricks real, para três identidades mantidas apenas em memória,
as consultas completas levaram 4,76 s, 3,40 s e 2,82 s (mediana 3,40 s).
As consultas sem os resumos de ranking/recomendações levaram 2,44 s,
1,21 s e 1,09 s (mediana 1,21 s). Recomendações usa o Perfil apenas
para nome, cidade e UF no cabeçalho; a aba Usuário usa os resumos.
Uma opção é pedir o Perfil sem resumo somente em Recomendações,
preservando a resposta completa na aba Usuário. Ainda não aplicado.

## 2026-09-19 — Rotação de senha não revoga sessão já emitida

Homologação usa a imagem
`app-renovai:4be1660-dualsource-senhas-20260919`, com novos hashes para os 25
usuários do piloto. Senhas antigas são rejeitadas em novos logins. O JWT de
sessão não consulta novamente o hash após ser emitido, então uma sessão aberta
antes do deploy pode permanecer válida por até `SESSAO_TOKEN_MINUTOS=60`.
Encerramento imediato de todas as sessões exigiria rotação do segredo JWT ou
um mecanismo explícito de revogação; nenhuma dessas mudanças foi feita.
