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
