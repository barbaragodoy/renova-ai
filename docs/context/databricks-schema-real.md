# Schema real (Databricks) vs. schema local (Postgres)

Mapeamento entre o schema local usado em dev (`data/scripts/01_create_tables.sql`)
e o schema real confirmado no Databricks (`acheinfo_dev.renovai`). Usar este
arquivo ao escrever SQL contra `DATA_SOURCE=databricks` ou ao portar lógica do
Postgres local. Ver também `.claude/rules/databricks.md` (versão resumida,
carregada automaticamente ao editar `backend/app/db/**`, `routers/recomendacoes.py`
e `auth/**`).

## tb_propagandistas

| Local (Postgres)         | Databricks real                                    | Observação |
|---------------------------|-----------------------------------------------------|------------|
| `rep_matricula`            | mesmo nome                                          | PK |
| `rep_email`                 | mesmo nome                                         | 14/2156 registros gravados em maiúsculas — comparar sempre com `LOWER()`, ver `docs/context/decisions-log.md` (2026-07-16) |
| `setor`                     | mesmo nome                                         | |
| `cod_linha`                 | **NÃO EXISTE** no schema real                       | Removida de `resolver_contexto()`/`ContextoResponse`. `jobs/gerar_recomendacoes.py`, `routers/gerencial.py` e `schemas/gerencial.py` ainda assumem essa coluna — alinhar com Hugo antes da promoção a produção |
| `rep_nome`                   | mesmo nome                                         | |
| `ativo` (boolean)           | **NÃO EXISTE** no schema real                       | Registros "VAGO" já são removidos na origem pelo pipeline de ingestão. Ausência de linha para o e-mail é o proxy de "não encontrado/inativo" — `resolver_contexto()` não filtra por `ativo` |
| — (não existe local) | `GD_MATRICULA`, `GD_NOME`, `GD_EMAIL`, `GD_LOGIN`, `GR_*`, `GN_*` | Hierarquia GD embutida por linha de SETOR/REP. Pode eliminar a necessidade de uma tabela separada equivalente a `tb_hierarquia_gd` em produção — não resolvido como isso afeta `routers/gerencial.py` (HUGO-08, a confirmar com Hugo/Caio) |

## tb_recomendacoes_painel (local) → tb_recomendacoes_painel_historico (real)

Mudança de modelo: local é "estado mais recente sobrescrito"; real é
histórico por ciclo mensal (ver `docs/context/decisions-log.md`, 2026-07-23).
15 colunas no schema real, aderente à especificação `tb_recomendacoes_painel_v2`.

| Local (Postgres)              | Databricks real (histórico)                    | Observação |
|--------------------------------|--------------------------------------------------|------------|
| `id_recomendacao`               | equivalente presente                             | |
| `rep_matricula`                  | mesmo conceito                                  | |
| `setor`                           | `SETOR`                                        | |
| `cod_linha`                       | **não existe** (ver acima)                     | |
| `ufcrm`                            | `UFCRM`                                       | chave, junto com SETOR + CICLO |
| `nome_medico`                      | equivalente presente                          | |
| `tipo_recomendacao`                | `TIPO_RECOMENDACAO`                          | valores `ENTRADA_PAINEL` / `REVISAO_PAINEL` — validado e correto, ver known-issues.md |
| `status_recomendacao`              | `STATUS_RECOMENDACAO`                        | **BUG ABERTO**: 100% das linhas = `CONSOLIDADA`, sem PENDENTE/APLICADA/EXPIRADA — ver known-issues.md |
| `posicao_ranking`                  | `RANKING_SETOR` (via `vw_ranking_setor`)     | recalculado POR SETOR via `ROW_NUMBER() OVER (PARTITION BY SETOR ORDER BY SOMA_PONTUACAO DESC)`, sem UFCRM como desempate. Corte 400 aplicado em `vw_ranking_corte_hist` |
| `soma_pontuacao`                   | `PONTUACAO_CICLO` / `SOMA_PONTUACAO` (view)  | |
| `motivo_revisao`                    | `MOTIVO_RECOMENDACAO`                       | **BUG ABERTO**: lógica incoerente entre TIPO e MOTIVO — nunca usar como filtro WHERE, só exibição — ver known-issues.md |
| `justificativa_texto`               | equivalente presente                        | |
| `ciclo_referencia`                   | `CICLO_RECOMENDACAO`                       | chave de particionamento do histórico |
| `data_geracao`                        | equivalente presente                      | |
| `motivo_desconsideracao`             | **NÃO EXISTE** no novo schema             | fluxo `/desconsiderar` está CONGELADO — ver decisions-log.md |
| `timestamp_desconsideracao`          | **NÃO EXISTE**                            | idem |
| `rep_matricula_desconsiderou`        | **NÃO EXISTE**                            | idem |
| `qtd_vezes_recomendado`               | equivalente presente                     | |
| `data_ultima_verificacao`             | equivalente presente                     | |
| — (não existe local) | `QTD_MEDICOS_PAINEL_CICLO`                            | contagem de médicos no painel do rep no ciclo — usada para a trava de revisão (`> 400`). RESOLVIDO em 2026-07-28, ver known-issues.md |

## Views auxiliares (só existem no Databricks)

- `vw_ranking_setor` — `ROW_NUMBER() OVER (PARTITION BY SETOR ORDER BY SOMA_PONTUACAO DESC)`, sem UFCRM como desempate.
- `vw_ranking_corte_hist` — filtra `RANKING_SETOR <= 400`. Validado: ENTRADA_PAINEL max=400, REVISAO_PAINEL min=401.
- `vw_ultima_visita` — `MAX(data_visita)` por SETOR+UFCRM, filtrando `visita_efetiva = 1`.

## Config relevante (`backend/app/config.py`)

- `DATA_SOURCE` (`local` | `databricks`) — controla qual engine `db/databricks_connection.py:get_engine()` retorna.
- `DATABRICKS_CATALOG` = `acheinfo_dev`, `DATABRICKS_SCHEMA` = `renovai`.
- `DATABRICKS_HTTP_PATH` deve apontar para o warehouse `783ae0217086255c` (`sql-warehouse-renovai-dev`) — ver `.env.example`. **Nunca** `e0bbf85808a7e35b` (SP sem CAN USE).
- `DOMINIOS_EMAIL_ACEITOS` = `ache.com.br,biosintetica.com.br` — configurável, não hardcoded.
- `AUTH_EMAIL_CLAIM` = `preferred_username` (padrão) — a confirmar com Flávio se produção usa `upn`.
