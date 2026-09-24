# Decisions Log — RenovAI Local

Decisões de negócio e arquitetura confirmadas ao longo do projeto, com data e
evidência. Registro cronológico — não reescrever entradas antigas quando um
novo achado corrige uma anterior; adicionar entrada nova referenciando a
antiga (ver exemplo do warehouse abaixo).

## Baseline — regras de negócio vigentes (não datadas, estáveis)

- Corte de entrada: posição no ranking <= 400 (local: <= 100).
- Corte de revisão: posição no ranking > 400 (local: > 100).
- Limite de sugestões: 5 por retorno, separados por tipo.
- Priorização: pontuação do ranking.
- Médico sem visita há mais de 5 meses: critério adicional de revisão.
- Propagandista não informa matrícula manualmente.
- Backend nunca expõe `tb_propagandistas` para o usuário.
- Motivos de revisão (modelo local/antigo): `ABAIXO_CORTE` ou
  `SEM_VISITA_5_MESES`. No schema real histórico os motivos têm 4 valores —
  ver `docs/context/databricks-schema-real.md` e bug ativo em
  `docs/context/known-issues.md`.

**Status de resolução de contexto** (`resolver_contexto()`,
`auth/context.py`):
- `SETOR_RESOLVIDO`: avança.
- `PROPAGANDISTA_NAO_ENCONTRADO`: bloqueia.
- `IDENTIDADE_AMBIGUA`: bloqueia.

**Erros padronizados do Genie/LLM** (`genie/nl_to_sql.py`, `llm/adapter.py`):
`GENIE_TIMEOUT`, `GENIE_ERROR`, `EMPTY_RESPONSE`, `CONTEXT_ERROR`.

## 2026-07-15 — Permissão do SP confirmada (tb_propagandistas)
SP `sp-renovai-genie-api-poc` tem SELECT sobre todas as tabelas atualmente
consultadas pelo Genie Space, incluindo `tb_propagandistas` — confirmado por
George.

Atenção: toda nova tabela adicionada ao escopo do Genie precisa de
confirmação de grant separada — não assumir herança automática.

## 2026-07-16 — Conexão com Databricks real confirmada
- SP `sp-renovai-genie-api-poc` autenticado com sucesso via OAuth M2M
  (`client_credentials`).
- Warehouse correto e testado: `783ae0217086255c`
  (`sql-warehouse-renovai-dev`). O ID antigo `e0bbf85808a7e35b` **não deve
  ser usado** — SP não tem CAN USE nele. Esta entrada corrige um registro
  anterior que apontava o nome antigo como confirmado.
- SELECT confirmado sobre `acheinfo_dev.renovai.tb_propagandistas` via teste
  direto com token do SP (retornou 2156 registros).
- `current_user()` do SP retorna o ClientID
  (`1831a9d4-97cd-4b56-8243-83a777dde138`), confirmando que a identidade
  usada é do SP, não de sessão de usuário humano.

## 2026-07-16 — Domínio de e-mail confirmado
`ache.com.br` e `biosintetica.com.br` são domínios válidos — confirmado por
George (mesmo grupo econômico). Validação de domínio implementada como lista
configurável (`DOMINIOS_EMAIL_ACEITOS` em `config.py`), não hardcoded — ver
schema em `docs/context/databricks-schema-real.md`.

## 2026-07-16 — Bug de e-mail maiúsculo corrigido
14 dos 2156 registros reais em `tb_propagandistas` têm `REP_EMAIL` gravado em
maiúsculas (ex.: `SUELEN.BRITO@ACHE.COM.BR`). `resolver_contexto()` fazia
match exato (`=`), então e-mail em minúsculas vindo do Auth0/Entra ID
retornava incorretamente `PROPAGANDISTA_NAO_ENCONTRADO`.

Corrigido em `auth/context.py`: comparação via
`WHERE LOWER(rep_email) = LOWER(:email)`. Confirmado 0 colisões via
`GROUP BY LOWER(rep_email)` nos 2156 registros — não é caso de
`IDENTIDADE_AMBIGUA` (essa regra é para múltiplas linhas distintas
colidindo no mesmo e-mail; aqui é uma única linha com inconsistência de
caixa). Coberto por teste de regressão dinâmico em
`test_context_integration.py::test_setor_resolvido_com_email_gravado_em_maiusculo`.

## 2026-07-23 — Mudança de modelo de dados: tb_recomendacoes_painel_historico
George documentou revisão completa do modelo de recomendações, migrando de
"estado mais recente sobrescrito" para histórico por ciclo mensal
(especificação `tb_recomendacoes_painel_v2`, enviada por George em
2026-07-22).

Mudanças de regra de negócio confirmadas nesta revisão (substituem o
comportamento descrito para o modelo antigo em `tb_recomendacoes_painel`):
- Revisão do painel exige que o propagandista tenha MAIS DE 400 médicos no
  painel (trava adicional, confirmada por George como regra real — ver
  status em `docs/context/known-issues.md`).
- Ranking de corte (400) deve ser recalculado POR SETOR, não usar a posição
  geral/original da fonte de ranking.
- Motivo da recomendação passa a ter 4 valores possíveis, diferenciando
  revisão por ranking, por ausência de visita, ou por ambos.

### Desconsiderar — CONGELADO (histórico, ver resolução em 2026-08-06)
`POST /recomendacoes/desconsiderar` (implementado, em produção em hmg) estava
**CONGELADO** por decisão do George — não desativar, não investir manutenção
nova. Motivo: ainda não decidido o canal/local final da solução; George
avaliava tornar o fluxo conversacional (linguagem natural, não botão/REST), o
que mudaria a arquitetura do endpoint e envolveria a camada de LLM/intent.
Campos de desconsideração (`motivo_desconsideracao`,
`rep_matricula_desconsiderou`) não existiam no novo schema histórico — ficaram
fora do contrato ativo até o redesenho ser aprovado. **Superado pela entrada
de 2026-08-06 abaixo.**

### Pendência em aberto com George
Não resolvido: se determinados `MOTIVO_RECOMENDACAO` devem bloquear a mesma
recomendação de ser sugerida novamente no ciclo seguinte, ou se toda
recomendação elegível é sempre re-sugerida independente do motivo anterior.
Impacta a lógica de geração mensal — aguardando resposta antes de implementar
essa parte.

## 2026-07-23/24 — Verificação técnica de tb_recomendacoes_painel_historico
Tabela criada pelo Hugo. Schema 100% aderente à especificação (15 colunas,
nomes e tipos batendo exatamente). Volume: 813.679 linhas (vs. 18.607.644 da
tabela antiga `tb_recomendacoes_painel`, descontinuada mas ainda presente no
catálogo).

Detalhes técnicos completos (fan-out, ranking por setor, corte, status,
motivo, qtd_medicos_painel) estão em `docs/context/known-issues.md` — este
log registra só a decisão/contexto, não o estado corrente do bug.

## 2026-07-28 — Permissão do SP nos 4 objetos novos: CONFIRMADA
Testado via token OAuth M2M direto (não via sessão de usuário): SP
`sp-renovai-genie-api-poc` tem SELECT confirmado em
`tb_recomendacoes_painel_historico`, `vw_ranking_corte_hist`,
`vw_ranking_setor` e `vw_ultima_visita`.

O `SHOW GRANTS` não mostrava isso porque a sessão de usuário usada para
inspecionar não tem MANAGE nesses objetos — não é ausência real de
permissão, é limitação de visibilidade da ferramenta de inspeção. **Ponto
fechado, não precisa mais ser revalidado.** Corrige o registro anterior
("GRANT pendente") que constava como bloqueante.

## 2026-07-28 — TRUNCATE no notebook de geração: esclarecido
O notebook de geração (`nb_dev_criacao_renovai_tb_recomendacoes_painel_hist`,
de `3vlhugo@ache.com.br`) contém `TRUNCATE TABLE` antes do `INSERT`.
Confirmado com o Hugo: em produção esse TRUNCATE ficará **comentado** — só
será executado manualmente em caso de necessidade comprovada de recriar a
tabela. As múltiplas execuções observadas em um único dia foram testes do
Hugo ajustando as correções descritas em `known-issues.md`, não o
comportamento real de produção. Preserva o conceito de histórico por ciclo
como especificado (não é um "estado mais recente sobrescrito" disfarçado).

## 2026-07-28 — Genie Room "RenovAI - Prescrições Médicas POC": contexto histórico
Confirmado com George: essa POC (usa `tb_ranking_medicos_validacao`, modelo
simples de 3 estados) é iniciativa anterior/exploratória, não o caminho de
produção atual (que é `tb_recomendacoes_painel_historico`, ver acima). Uso
registrado: 109 perguntas de um único usuário, 0 avaliações — fase de teste
manual. **Não precisa de migração nem alinhamento** — é resquício de fase
anterior do projeto, não um bloqueio ativo.

## 2026-07 — IDENTIDADE_AMBIGUA: não reproduzível na tb_propagandistas real
Lógica defensiva mantida no código (`resolver_contexto()`), mas **não
reproduzível** na `tb_propagandistas` real: 2156/2156 e-mails únicos
confirmado via `GROUP BY LOWER(rep_email)`. Coberta por teste unitário com
mock (`test_context.py::test_identidade_ambigua`) **e** por teste de
integração com dado real em `acheinfo_dev.renovai.tb_propagandista_teste` —
tabela dedicada, criada especificamente para esse cenário, com massa própria
(par de e-mails duplicados). Ver `resolver_contexto(email, tabela=...)` em
`auth/context.py` e
`test_context_integration.py::test_identidade_ambigua_tabela_teste`. Esse
teste pula (skip) se o SP ainda não tiver SELECT na tabela ou se a massa de
teste ainda não tiver sido carregada.

## 2026-08-06 — Desconsiderar Recomendação: reconciliação de 3 referências e descongelamento
Implementação definitiva do fluxo de desconsiderar, reconciliando três
referências que existiam em paralelo:

1. **Endpoint antigo neste repositório** (`POST /recomendacoes/desconsiderar`,
   ID no corpo) — CONGELADO desde 2026-07-23 (ver entrada acima), aguardando
   definição de canal.
2. **Notebook de referência da task 163626** (outro profissional) —
   `POST /recomendacoes/{id_recomendacao}/desconsiderar`, ID no path,
   `UPDATE ... WHERE STATUS_RECOMENDACAO='PENDENTE'` com `COALESCE` no
   contador. Rodava contra `tb_recomendacoes_painel_clone` (tabela de
   desenvolvimento do profissional, não a tabela do projeto), sem checagem de
   dono da recomendação, sem `bloquear_novas_recomendacoes`, sem tratamento
   de `OUTROS`, SQL não parametrizado, `SparkSession` direto.
3. **Especificação oficial da task 161830** (George) — fonte de verdade das
   regras de negócio. Registra explicitamente: *"Opção definida: Endpoint
   controlado de atualização, implementado pela task 163626"* — ou seja, o
   George já havia decidido o canal (REST, ID no path), resolvendo a
   pendência que mantinha o item 1 congelado.

**Decisão:** o endpoint do item 1 foi **descontinuado** (removido de
`routers/recomendacoes.py`, `schemas/recomendacoes.py` e
`test_desconsiderar.py`). A rota e abordagem do item 2 (ID no path) viraram a
base, com todos os gaps corrigidos e as regras completas da 161830
implementadas: identidade exclusivamente via `resolver_contexto()`,
autorização de dono (403 sem vazar detalhe), `bloquear_novas_recomendacoes`
obrigatório sem default, motivo `OUTROS` formatado como `"OUTROS: <texto>"`,
SQL 100% parametrizado via SQLAlchemy, `get_engine()` (schema-agnóstico,
mesmo padrão de `/entrada` e `/revisao`), UPDATE atômico com
`WHERE status_recomendacao='PENDENTE'` cobrindo concorrência sem lock
explícito.

Desenvolvido primeiro contra o Postgres local (`tb_recomendacoes_painel`) —
migração das colunas antigas (`timestamp_desconsideracao` →
`data_desconsideracao`, `rep_matricula_desconsiderou` → `desconsiderado_por`)
mais as 2 colunas novas (`qtd_vezes_desconsiderado`,
`bloquear_novas_recomendacoes`) em
`data/scripts/09_migrar_colunas_desconsideracao.sql`. A tabela real
(`tb_recomendacoes_painel_historico`) **ainda não tem** essas 5 colunas —
pendência formal com o Hugo antes de migrar, mesmo processo já usado em
BARBARA-04/05 (ver `docs/context/known-issues.md`).

**Reforço de risco (2026-08-12, encontrado na revisão de
`routers/recomendacoes.py`):** se `DATA_SOURCE=databricks` for ativado em
`APP_RENOVAI` antes das 5 colunas de desconsideração existirem na tabela
real, o `UPDATE` do endpoint `/desconsiderar` vai gerar erro SQL cru do
Databricks (coluna inexistente), não um erro tratado. Diferente do
comportamento da branch do George, que retornava 501 (mensagem clara de
indisponibilidade) para o mesmo cenário. Considerar adicionar uma
verificação defensiva (try/except específico, ou checagem de schema no
startup) antes de habilitar Databricks em produção para este endpoint,
para evitar expor erro cru ao usuário final.

**Confirmado na prática (2026-08-14, teste de ponta a ponta):** deixou de
ser risco teórico. Rodando `renovai-local` com `DATA_SOURCE=databricks`
contra dado real, `POST /recomendacoes/{id}/desconsiderar` falhou com 500
de verdade — `DESCONSIDERADO_POR` e `QTD_VEZES_DESCONSIDERADO` confirmadas
ausentes na tabela real (via `DESCRIBE`/erro do próprio Databricks:
`UNRESOLVED_COLUMN.WITH_SUGGESTION`). As outras 3 das 5 colunas
(`MOTIVO_DESCONSIDERACAO`, `BLOQUEAR_NOVAS_RECOMENDACOES`,
`DATA_DESCONSIDERACAO`) já existem — achado colateral também confirmado
nesse mesmo teste. O frontend tratou o erro corretamente (alerta genérico,
sem vazar SQL, item não removido da lista) — o problema é
exclusivamente a tabela real, não o código. Detalhe completo do teste em
`docs/context/known-issues.md`. **Reforça a prioridade de resolver as 2
colunas pendentes com o Hugo antes de qualquer deploy que inclua
desconsiderar contra Databricks** — o try/except defensivo sugerido acima
continua uma mitigação válida, mas não substitui a correção na origem.

## 2026-08-10 — Registro de Envio do Piloto (Sprint 5): tabela nova, sem bloqueio externo
`tb_envios_recomendacoes_piloto` registra o histórico de envio de
recomendações aos propagandistas durante o piloto, para comparar os grupos
`WHATSAPP`, `EMAIL` e `CONTROLE`. **Diferente de todas as tarefas
anteriores envolvendo `tb_recomendacoes_painel*`: esta é uma tabela nova,
sem dependência de correção externa** — propriedade e criação da própria
Bárbara, não do Hugo. Sem bloqueio de dado, só implementação.

Decisão de design confirmada: o grupo `CONTROLE` também gera registro de
envio, com `CANAL_ENVIO = 'NENHUM'` — representa "recomendação estava
disponível para este propagandista, sem push ativo". Garante que a tabela
sozinha permita comparar timing entre os três grupos sem depender de outra
fonte (ex.: não precisa cruzar com log de disparo do Twilio para saber
quando o grupo Controle "teria" recebido).

Implementada primeiro no Postgres local
(`data/scripts/11_create_tb_envios_recomendacoes_piloto.sql` +
`12_popular_cenarios_envios_recomendacoes_piloto.sql`), como função de
serviço (`registrar_envio_recomendacoes()`,
`backend/app/services/registro_envio.py`) — não endpoint REST, já que ainda
não existe job/integração de disparo real (Twilio/WhatsApp, templates Meta,
e-mail) que a chame. Desenvolvida de forma totalmente independente dessas
integrações. `ID_ENVIO` e `DATA_HORA_ENVIO` sempre gerados pelo backend.

Ainda **não existe no Databricks real** — criação lá planejada para sessão
separada, em paralelo. Ver `docs/context/databricks-schema-real.md`.

## 2026-08-12 — Comparação com feature/aba-recomendacoes (George): decisão final por item
Comparação técnica da branch `feature/aba-recomendacoes` (PR 22544, George)
contra o estado de `APP_RENOVAI` pós-sincronização (Grupos A/B/D). George
confirmou: nos pontos de divergência real, a implementação de `renovai-local`
prevalece, exceto um item de mérito técnico independente. Decisão item a
item:

1. **Filtro por setor** — NÃO adotado. A versão do George filtra
   `WHERE ... AND setor = :setor`, mas isso contradiz uma auditoria anterior
   (relação SETOR × COD_LINHA confirmada 1:1 via query direta no ranking) e
   tem uma inconsistência interna própria: `resolver_contexto()` (que ele
   não alterou) trata `len(rows) > 1` para o mesmo e-mail como
   `IDENTIDADE_AMBIGUA` (bloqueio 403) — ou seja, um propagandista com
   duas linhas em `tb_propagandistas` (uma por setor) nunca chegaria a
   acionar esse filtro, porque a resolução de identidade já teria barrado
   antes. Mantido sem filtro de setor, só `rep_matricula`.
2. **Remoção do `LIMIT 5`** — NÃO adotada. Divergência de arquitetura
   (backend limita vs. frontend limita) com implicação real de contrato
   (tamanho do payload) e performance (lista completa sempre trafegando).
   Mantido `LIMIT :limite` no backend.
3. **`POST /desconsiderar` retornando 501** — NÃO adotado. A implementação
   de `renovai-local` (task 161830/163626 reconciliada) já é completa e
   testada contra Postgres local, com mapeamento Databricks pronto e
   dormente aguardando as 5 colunas do Hugo — trata os cenários reais
   (404/403/409/400/200), não bloqueia com 501. Mantida a implementação
   completa.
4. **Ciclo via `MAX(ciclo_recomendacao)`** — **ADOTADO**, por mérito técnico
   próprio: resolve o known-issue documentado do default estático de ciclo
   ficando obsoleto a cada rollover mensal (ver
   `docs/context/known-issues.md`). Implementado preservando `?ciclo=`
   explícito (dependência real confirmada em
   `test_recomendacoes_integration.py` e no contrato do `README.md`) — o
   `MAX()` só substitui o fallback estático, não remove a consulta a
   ciclos específicos. Aplicado em `/entrada` e `/revisao`.
5. **Teste de introspecção estática** (`test_sql_usa_tabela_e_colunas_do_contrato`,
   verifica via `inspect.getsource` que nomes do contrato antigo só
   aparecem como `AS alias`) — NÃO adotado como está. Incompatível com a
   arquitetura dual-source (`_schema()`/`_COLUNAS_POR_FONTE`): esses mesmos
   nomes são colunas literais e corretas no Postgres local, não "contrato
   antigo" nesse contexto. Precisaria de adaptação para conviver com a
   abstração, não copiado.

**Achado colateral, não relacionado a nenhuma divergência:** a comparação
revelou que o George resolveu a pendência de `USE CATALOG` em
`dmn_inteligencia_dados_prd` (SP sem esse grant) por via alternativa —
criou `tb_dim_medicos`, espelho local dentro de `acheinfo_dev.renovai`, em
vez de solicitar o GRANT cruzado. Ver `docs/context/known-issues.md`. Não
incorporado nesta data — capacidade aditiva, candidata a task separada.

Branch do George confirmada como atualizada em relação a `dev`
(`git log origin/feature/aba-recomendacoes..dev` = 0 commits, ou seja, tudo
que existe em `dev` hoje já está na ancestralidade da branch dele) — risco
de conflito por desatualização de sessão/auth era baixo, e se confirmou
baixo nos diffs de arquivo (`auth/context.py`, `db/databricks_connection.py`,
`config.py`, `gerencial.py` idênticos ao estado pós-sync).

## 2026-08-20 — SP tem permissão de escrita confirmada; as 5 colunas de desconsideração já existem na tabela real
Investigando um 500 relatado em produção no `/desconsiderar`, testado se o
Service Principal `sp-renovai-genie-api-poc` (ClientID
`1831a9d4-97cd-4b56-8243-83a777dde138`) tem `MODIFY`/`UPDATE` na tabela real
(só `SELECT` estava confirmado antes). Metodologia: `get_engine()` do
próprio projeto com `DATA_SOURCE=databricks` (mesmo mecanismo do backend,
sem PAT) — `SELECT current_user()` confirmou a sessão autenticada como o
ClientID do SP, não usuário humano.

Executado o UPDATE exato do endpoint `/desconsiderar` contra uma linha
`PENDENTE` real (`ID_RECOMENDACAO = a55774fb-ad65-49c3-b6bf-f5d70f09c0ff`),
com `WHERE STATUS_RECOMENDACAO = 'PENDENTE'` de guarda de concorrência —
**sucesso**, confirmado por `SELECT` de volta (status virou
`DESCONSIDERADA`, todos os campos gravados corretamente). Revertido
imediatamente com o mesmo padrão do endpoint `/reverter` (4 campos voltam a
`NULL`, `QTD_VEZES_DESCONSIDERADO` mantido em 1 propositalmente, mesma regra
já documentada na Aba Arquivadas abaixo) — linha confirmada de volta ao
estado original. **O SP tem permissão de escrita completa nesta tabela.**

**Achado que muda o diagnóstico:** `DESCRIBE TABLE` na mesma sessão mostrou
que as 5 colunas de desconsideração
(`MOTIVO_DESCONSIDERACAO`, `DESCONSIDERADO_POR`, `DATA_DESCONSIDERACAO`,
`QTD_VEZES_DESCONSIDERADO`, `BLOQUEAR_NOVAS_RECOMENDACOES`) **já existem
todas** na tabela real, incluindo `DESCONSIDERADO_POR` e
`QTD_VEZES_DESCONSIDERADO` — as 2 que a entrada de 2026-08-14 acima
("Confirmado na prática") havia confirmado **ausentes**, causando
`UNRESOLVED_COLUMN.WITH_SUGGESTION` e o 500 daquele teste. Ou seja, entre
2026-08-14 e hoje o Hugo aparentemente concluiu a migração pendente — as
duas colunas que faltavam agora têm inclusive comentário de coluna
(`DESCONSIDERADO_POR`: "Matricula do propagandista que desconsiderou a
recomendacao"; `QTD_VEZES_DESCONSIDERADO`: "Quantas vezes a recomendacao ja
foi desconsiderada"), sinal de que foi um trabalho intencional, não
acidental.

**Conclusão sobre o 500 relatado em produção:** com escrita liberada para o
SP e as 5 colunas presentes, nem permissão nem coluna ausente explicam um
500 *novo*. As duas causas historicamente documentadas para esse endpoint
(`UNRESOLVED_COLUMN` de 2026-08-14 acima, congelamento antigo do George —
ver `docs/context/decisions-log.md` entrada de 2026-07-23 e memória
`projeto_desconsiderar_congelado`) já não se aplicam ao estado atual da
tabela. Se o 500 relatado for recente, a causa raiz está em outro lugar —
candidatos a checar primeiro: `resolver_contexto()` (nota de manutenção em
`known-issues.md`, 2026-08-12), payload/validação do request
(`DesconsiderarRequest`), ou se o 500 relatado é datado de antes de
2026-08-14/hoje e já está obsoleto. Ver `docs/context/databricks-schema-real.md`
(linhas das 5 colunas, atualizadas nesta mesma data).

## 2026-08-13 — Aba Arquivadas (consulta + reversão de desconsideradas)
Implementados `GET /recomendacoes/desconsideradas` e
`POST /recomendacoes/{id_recomendacao}/reverter` **localmente** (Postgres),
sobre a mesma base do Desconsiderar Recomendação (2026-08-06 acima). As 5
colunas de desconsideração já existiam no schema local desde aquela task —
sem pendência de dado nova, só implementação.

Decisões de design assumidas nesta implementação (sem alinhamento formal
prévio, mas sem conflito identificado com nada já existente no código ou
neste log):
- **4 campos limpos na reversão** (`motivo_desconsideracao`,
  `desconsiderado_por`, `bloquear_novas_recomendacoes`,
  `data_desconsideracao` voltam a `NULL`); `qtd_vezes_desconsiderado`
  **não** é zerado — mantém o histórico acumulado de quantas vezes aquela
  recomendação já foi desconsiderada ao longo do tempo, mesmo após
  reversões.
- **Sem `LIMIT`** na consulta de `/desconsideradas` — diferente de
  `/entrada` e `/revisao` (que limitam a `settings.limite_sugestoes` por
  serem sugestões priorizadas), esta é uma tela de histórico completo.
- **Ordenação `DATA_DESCONSIDERACAO DESC`** (mais recente primeiro) — mais
  natural para uma tela de arquivo/histórico.
- Novo status da reversão: `PENDENTE` se `CICLO_RECOMENDACAO` da
  recomendação é igual ao ciclo mais recente (`_ciclo_mais_recente()`,
  reaproveitado sem alteração), `EXPIRADA` caso contrário (ciclo passado).
- `POST /reverter` não recebe payload no corpo — só `id_recomendacao` no
  path, mesmo padrão de ação simples sem parâmetros adicionais.

Mapeamento para Databricks continua dormente em
`_COLUNAS_POR_FONTE["databricks"]`, aguardando as mesmas 5 colunas do Hugo
já formalizadas como pendência na entrada de 2026-08-06.

## 2026-08-26/27 — Chat/Ranking/Agente + Perfil unificado: sincronizado com dev
Trazido para `renovai-local` o trabalho do George na branch
`merge/portal-agente-e-recomendacoes` (`AcheInfo_Apps/APP_RENOVAI`):
agente de chat, aba Chat, aba Ranking, e unificação de `tb_perfil_portal`
com a edição de nome/foto/limite de painel dele. Diagnóstico prévio
(mesmo padrão cauteloso de sempre — dev vs. branch do George, arquivo por
arquivo) confirmou os 4 arquivos centrais da Sprint 6 idênticos entre
`dev` e a branch do George: sem conflito real, decisão foi copiar/mesclar
direto, não reconciliar regra de negócio divergente.

**Decisão de arquitetura confirmada durante o port**: o código do George
não usava a abstração dual-source (`_schema()`/`get_engine()` consciente
de `DATA_SOURCE`) e tinha 6 padrões de SQL que só funcionam no Databricks
— corrigidos sem alterar comportamento em nenhuma das duas fontes
(detalhe técnico completo, achado por achado, em
`docs/context/known-issues.md`). Decisão: preservar a abstração
dual-source como padrão obrigatório para todo código novo trazido de
fora, mesmo quando a origem não segue esse padrão.

**Migração do 318**: o George criou `tb_renovai_parametros` no Databricks
real em 26/08/2026 como fonte única de parâmetros de negócio
(`LIMITE_PAINEL_PADRAO`, `JANELA_VISITA_MESES`, `JANELA_PAINEL_CICLOS`).
Decisão: eliminar todo literal `318` hardcoded no código (Sprint 6 tinha
introduzido esse literal em 4 lugares) e ler da tabela em tempo real —
aplicado em `routers/recomendacoes.py`, `jobs/gerar_recomendacoes.py`,
`genie/nl_to_sql.py`, `auth/perfil.py`. Nota de hardening (não
implementada, registrada em known-issues.md): o comentário real da
coluna sugere intenção de "erro declarado" se a tabela ficar
inacessível, mas a fórmula atual só falha de verdade se a tabela não
existir — devolve `NULL` silencioso se existir sem a linha `ID=1`.

**Achado de segurança, tratado fora desta sincronização**:
`acessos.csv.bak-20260820` na branch do George continha e-mail +
hash de senha reais de funcionários Aché. Não copiado para
`renovai-local` em nenhuma hipótese, em nenhum commit.

**Publicado**: 6 commits em `renovai-local` (`364e3c0`..`b0ee9b5`), 5
commits equivalentes em `AcheInfo_Apps/dev` (`0630b17`..`67dd775`) —
mesmo agrupamento temático nos dois repositórios, mensagens adaptadas
onde a realidade de `dev` divergia (`requirements.txt`,
`docs/context/known-issues.md` gitignored em `dev`, aplicado só
fisicamente). Push confirmado nos dois remotos.

## 2026-08-28 — Integração WhatsApp via Twilio (Sprint 7): SQL cru, sem ORM
Uma proposta de estrutura de código de outra sessão de trabalho usava
SQLAlchemy ORM (`Base`, `Column`, `Session`) e pastas `backend/app/
models/`/`backend/app/api/` — nenhum dos dois existe em qualquer lugar
deste projeto. Decisão: reescrever seguindo o padrão real (SQL
parametrizado via `get_engine()` + `text()`, mesmo padrão de
`services/registro_envio.py`; estrutura de pastas real —
`routers/`/`services/`/`schemas/`/`db/`), não introduzir ORM nem pastas
novas fora do padrão estabelecido.

`tb_notificacoes_whatsapp` fica no Postgres local por enquanto — mesmo
padrão de desenvolvimento das outras sprints, sem tocar Databricks real
nesta fase (`data/scripts/17_create_tb_notificacoes_whatsapp.sql`).

Configuração da Twilio (`integrations/whatsapp/config.py`) deliberadamente
isolada de `Settings`/`config.py` central: é credencial de UMA API
externa, categoria distinta de `DATA_SOURCE` (que escolhe entre duas
fontes de dado equivalentes e é consumido por quase todo o backend).
`TWILIO_ENV=production` recusado com erro claro — sem credencial de
produção configurada ainda (ver `docs/context/known-issues.md`).

Implementado e testado localmente (19 testes novos, suíte completa 360
passed / 1 failed pré-existente / 3 skipped) — **nada commitado ainda**,
decisão de divisão de commits fica para sessão seguinte.

## 2026-09-15 — Task 170097: Entra ID usa App Service Easy Auth

Confirmado que homologação já usa App Service Easy Auth com autenticação
obrigatória e Token Store ativo. Não haverá MSAL customizado nem validação
local do token corporativo.

Decisões:
- `AUTH_MODE=senha` permanece como default e mantém o JWT próprio do portal;
- `AUTH_MODE=entra_id` confia nos headers injetados pelo Easy Auth;
- header primário: `X-MS-CLIENT-PRINCIPAL-NAME`;
- fallback: decodificar `X-MS-CLIENT-PRINCIPAL` e procurar claim `upn`;
- o UPN é cortado no primeiro `@`, sem domínio fixo;
- a identidade resultante é comparada com `REP_LOGIN`;
- comparação via `LOWER()` nos dois lados, pois há registros em maiúsculas;
- `AUTH_REQUIRE_JWT`, `AUTH_EMAIL_CLAIM` e JWKS pertencem ao desenho legado
  e não participam do fluxo real de `entra_id`.

Evidência de dados informada pelo time: 2.154 propagandistas com `REP_LOGIN`
preenchido e único; 16 valores armazenados em maiúsculas.

Bloqueio externo, fora do código: cadastrar
`https://pedai.ache.com.br/.auth/login/aad/callback` como redirect URI.

## 2026-09-15 — Deploy da Task 170097 em homologação mantém AUTH_MODE=senha

Deploy da Task 170097 (login por Entra ID) em homologação: apenas o
**CÓDIGO** foi publicado na imagem. `AUTH_MODE` permanece `senha`
deliberadamente — o modo `entra_id` existe no código mas está **INATIVO**.

Decisão consciente: não ativar até:

1. o time de Entra ID cadastrar o redirect URI de
   `pedai.ache.com.br` — erro `AADSTS50011` ainda pendente; e
2. haver validação com login real confirmando qual header/formato o Easy
   Auth realmente entrega: `X-MS-CLIENT-PRINCIPAL-NAME` diretamente ou
   exercitando o fallback de decodificação do
   `X-MS-CLIENT-PRINCIPAL`.

Trocar `AUTH_MODE=entra_id` nas Application Settings do Web App
`asp-renoveai-hmg` sem essas duas condições resolvidas desativaria o login
por senha para todo o piloto, sem garantia de que o login por Entra ID
funcione no lugar — risco de bloquear o acesso de todos os usuários
simultaneamente.

## 2026-09-16 — Easy Auth temporariamente anônimo em homologação

Por sugestão do George, decidiu-se alterar temporariamente
`unauthenticated-client-action` de `RedirectToLoginPage` para
`AllowAnonymous` em `asp-renoveai-hmg`, para destravar o trabalho do Thiago
na tela de login e no acabamento visual. **Status deste registro: decisão
documentada; comando Azure ainda não executado.**

Após a mudança, o Easy Auth deixará passar requisições autenticadas e não
autenticadas sem impor login Microsoft. O endpoint `/.auth/login/aad`
continuará disponível para iniciar esse fluxo manualmente.

`AUTH_MODE=senha` deve permanecer ativo. As rotas de negócio que chamam
`resolver_email_autenticado()` continuarão exigindo o JWT de sessão próprio;
rotas como `/health`, `/docs` e a entrega do frontend não exigem essa sessão.
É um retorno deliberado ao modelo de proteção das rotas de negócio anterior
à imposição de login pelo Easy Auth, **com remoção da barreira adicional da
plataforma**. Não ativar `AUTH_MODE=entra_id` enquanto `AllowAnonymous`
estiver vigente: nesse modo, headers de identidade poderiam ser forjados.

Reverter para `RedirectToLoginPage` assim que Thiago concluir a tela de
login. O redirect URI de `pedai.ache.com.br` (`AADSTS50011`) permanece
pendente e é uma questão separada.

## 2026-09-17 — PRs 23635/23670 mesclados; autenticação de homologação preservada

PR 23635 (`f82996d`) e PR 23670 (`54e3c0e`) aprovados e concluídos com
squash em `dev`. Antes de cada conclusão, o diff literal entre as pontas
remotas confirmou zero diferença fora de `APP_RENOVAI/`; os commits finais
alteram apenas sete arquivos de frontend desse aplicativo. As branches de
origem foram preservadas e não houve transição de work items.

Decisão do usuário: deixar o botão Microsoft do PR 23635 visível por
agora, mantendo o login por e-mail e senha. `AUTH_MODE=senha` e Easy Auth
`AllowAnonymous` foram confirmados após os merges e não alterados. O link
do botão é clicável e inicia `/.auth/login/aad`, mas esse fluxo ainda não
cria a sessão exigida pelo portal no modo `senha`; o redirect URI de
`pedai.ache.com.br` continua pendente. A imagem de homologação não mudou
(`ed64685-entra-id-20260915`); build e deploy ficaram suspensos.

`renovai-local` recebeu os sete arquivos com os hunks dos PRs e nenhuma
alteração de backend. Sem commit. Validação: frontend `npm run lint` OK;
suíte backend, ignorando o golden set com falha de coleta já documentada,
476 passed / 5 failed preexistentes / 3 skipped.

## 2026-09-17 — Preparação do deploy: botão inerte e senhas preservadas

O usuário aprovou manter o botão Microsoft visível, porém sem ação, enquanto
`AUTH_MODE=senha` continua ativo. O ajuste mínimo em `Login.tsx` substitui o
link `/.auth/login/aad` por `<button disabled>` nos dois ambientes locais.
Checagem TypeScript passou em ambos. Ainda não há commit, build ou deploy
desse ajuste; Easy Auth deve permanecer em `AllowAnonymous`.

Decisão para continuidade das credenciais: reutilizar o `acessos.csv` local
confirmado pelo usuário como o do último build, sem executar
`gerar_acesso_portal.py --limite 25`, que geraria novas senhas e hashes.
`acessos.csv` e `senhas-portal-*.csv` estão fora do Git; o segundo também
está fora do contexto Docker. O primeiro entra na imagem por `COPY` no
Dockerfile quando o build for autorizado. Antes de commit, conferir que
nenhum desses arquivos está rastreado ou preparado.

## Próximos passos técnicos (não iniciados)
- Implementar `llm/genie_provider.py` com Databricks SDK (para promoção a
  produção) — ver `docs/promocao_producao.md`.
- Criar frontend React que consome os endpoints.
- Alinhar `genie/intent_rules.json` com Pavan após revisão de critérios —
  único arquivo a mudar após esse alinhamento.
- Confirmar equivalente de `tb_hierarquia_gd` em produção (HUGO-08, com
  Caio) — ver nota de schema em `databricks-schema-real.md`.

## Pendências de decisão (ainda sem data de resolução)
- Critério de desempate de sugestões: a definir com Caio.
- Perfis autorizados além do GD: a definir.
- Regra de exibição de justificativa de recusa para GD: a definir
  (implementado hoje: GD vê `motivo_desconsideracao`).
- Fonte oficial da hierarquia GD em produção: a confirmar com Hugo
  (HUGO-08) — ver `docs/context/databricks-schema-real.md` sobre
  GD_MATRICULA/GD_NOME/GD_EMAIL/GD_LOGIN já embutidos em
  `tb_propagandistas`.
- ~~Claim JWT do Entra ID com e-mail: `preferred_username` ou `upn`~~ —
  **RESOLVIDO em 2026-09-15**: o identificador é o UPN recebido pelo Easy
  Auth. `AUTH_EMAIL_CLAIM` pertence somente ao caminho legado de JWKS.
- Se `MOTIVO_RECOMENDACAO` deve bloquear re-sugestão no ciclo seguinte —
  aberto com George (ver seção 2026-07-23 acima).

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

## 2026-09-17 — Performance: medir antes de alterar

Diagnóstico somente leitura encontrou latência no Web App sem saturação
aparente de CPU ou fila HTTP. Ainda não há duração por rota nem por consulta
SQL. Nenhuma decisão de cache, infraestrutura ou mudança de código foi tomada.

## 2026-09-17 — Performance: evidência direta do Databricks

O teste somente leitura no warehouse real reproduziu a lentidão sem
alterar código ou configuração. A configuração observada de auto-stop
é 5 minutos; o comentário antigo de 10 minutos em
`backend/app/db/databricks_connection.py` está desatualizado.
Não foi decidida nenhuma mudança de cache ou infraestrutura.

## 2026-09-19 — Rotação integral das senhas do piloto e novo deploy

Foi mantido o mesmo conjunto de 25 usuários e gerada uma senha nova para cada
um. O arquivo de distribuição permanece somente no ambiente local, fora do
contexto Docker; `acessos.csv` contém apenas hashes, continua fora do Git e foi
incluído na imagem `app-renovai:4be1660-dualsource-senhas-20260919`.

O deploy manteve `AUTH_MODE=senha`, Easy Auth `AllowAnonymous` e o botão
Microsoft visível e desabilitado. A rotação invalida as senhas antigas para
novos logins. Não foi implementada revogação de tokens: sessões existentes
expiram pelo prazo configurado de 60 minutos.

## 2026-09-23 — Bloqueio de redirect URI (Entra ID) confirmado resolvido

Verificação direta no App Registration real (`az ad app show --id
a702ad79-643d-4361-831a-95d7bca3b2b6 --query "web.redirectUris"`) confirmou
que `https://pedai.ache.com.br/.auth/login/aad/callback` e
`https://asp-renoveai-hmg.azurewebsites.net/.auth/login/aad/callback` já
estão cadastrados. `GET /.auth/login/aad` em `asp-renoveai-hmg` redireciona
corretamente para `login.microsoftonline.com` com `client_id`/`redirect_uri`
corretos — sem indício de `AADSTS50011` nessa etapa.

Isso resolve a condição 1 da decisão de 2026-09-15 acima. A condição 2 (login
real confirmando o formato do header do Easy Auth) **não foi validada** nesta
verificação — não havia credencial/browser disponíveis para completar um
login interativo de ponta a ponta.

Isso sozinho **não muda** a decisão de manter `AUTH_MODE=senha`: falta ainda
a checagem de `STATUS_ACESSO`/`PERFIL_ACESSO` em `resolver_contexto()` (hoje
inexistente — confirmado lendo o código), sem a qual ativar `entra_id` abriria
acesso a todos os ~2.154 propagandistas reais com conta corporativa válida,
não só aos ~72 aprovados para o piloto (72 `ATIVO` / 2.087 `BLOQUEADO`,
contagem real em `tb_perfil_portal` na mesma data). Ver
`docs/context/known-issues.md`, entradas "RESOLVIDO (2026-09-23)" e "ALERTA
— não ativar AUTH_MODE=entra_id em homologação ainda".

## 2026-09-24 — STATUS_ACESSO publicado em hmg; virada de AUTH_MODE adiada

Decisões desta etapa:

1. **Onde fica a checagem de acesso.** A checagem fica em
   `jwt_auth.py::resolver_email_autenticado()`, sobre `email_real`, e em
   `POST /auth/login`, logo depois da senha conferir e antes de
   `buscar_cadastro()`. Não fica em `resolver_contexto()`: todo chamador real
   já passa para essa função o e-mail personificado (`X-Ver-Como`), e checar
   ali olharia o propagandista visualizado, não quem está logado. A resposta é
   um único helper, 403 `{"codigo": "ACESSO_BLOQUEADO", "detail": ...}`. Sem
   linha em `tb_perfil_portal`, o acesso é negado.
2. **Administrador vem de `tb_perfil_portal.PERFIL_ACESSO`.** `ADMIN_EMAILS`
   foi removido do `config.py`. A consulta tenta primeiro o propagandista
   (pela coluna do modo de autenticação, via `rep_matricula`) e depois
   `tb_perfil_portal.REP_EMAIL` direto, para administradores sem
   propagandista. Para eles, `REP_EMAIL` guarda a identidade do Entra ID tal
   como recebida.
3. **Frontend `entra_id`.** Foi reimplementado sobre `dev`, sem mesclar
   `virada-entraid-front`. A sessão nunca vai para sessionStorage nesse modo:
   no F5, a identidade é reconfirmada via cookie. O logout passa por
   `/.auth/logout`. Um administrador sem propagandista cai no fallback
   `GET /admin/sessao`. `ACESSO_BLOQUEADO` é detectado pelo código, não pelo
   texto.
4. **Deploy com `AUTH_MODE=senha`.** A Bárbara aceitou publicar a checagem
   antes da virada, mesmo bloqueando os 25 usuários de `acessos.csv` (todos
   `BLOQUEADO`), porque ninguém usa essas credenciais em hmg.
5. **Configurações da virada.** `AUTH_REQUIRE_JWT` e `AUTH_EMAIL_CLAIM` não
   mudam, porque não influenciam o modo `entra_id`. O que muda, junto e com
   confirmação explícita da Bárbara: `AUTH_MODE=entra_id`, Easy Auth
   `unauthenticatedClientAction=RedirectToLoginPage` e uma imagem gerada com
   `VITE_AUTH_MODE=entra_id`. Alvo de rollback de imagem:
   `53b8067-ranking-admin-menus-20260923`. O rollback de configuração
   (`senha` + `AllowAnonymous`) já basta na maioria dos casos, porque a
   imagem nova continua funcionando em modo senha.
6. **Claim de identidade.** `upn` não existe no token da Aché. O claim certo é
   `preferred_username`, nunca `emailaddress`. A correção do código espera a
   confirmação do header real no Log Stream (ver known-issues de 24/09).
7. **Execução.** As mudanças foram feitas direto pelo Claude Code, sem
   delegar ao Codex CLI: `codex exec` não oferece um checkpoint de aprovação
   real, como foi verificado antes nesta mesma sessão.
