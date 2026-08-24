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
- Claim JWT do Entra ID com e-mail: `preferred_username` ou `upn` — a
  confirmar com Flávio. Configurável via `AUTH_EMAIL_CLAIM` em `config.py`,
  não hardcoded.
- Se `MOTIVO_RECOMENDACAO` deve bloquear re-sugestão no ciclo seguinte —
  aberto com George (ver seção 2026-07-23 acima).
