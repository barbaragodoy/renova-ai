-- =============================================================
-- Views reais para Chat / Ranking / Agente.
--
-- As 3 daqui são replicadas com a MESMA lógica da fonte real (não são
-- simplificação) — só a sintaxe muda de Databricks/Spark SQL para
-- Postgres (REGEXP_EXTRACT -> substring(... from ...), sem WITH SCHEMA
-- COMPENSATION). Depende das tabelas criadas em
-- 14_create_tabelas_chat_ranking_agente.sql.
-- =============================================================


-- =============================================================
-- vw_segmentacao_efetiva
-- Mesma lógica de acheinfo_dev.renovai.vw_segmentacao_efetiva: edição
-- do propagandista (tb_segmentacao_medico, deduplicada pela mais
-- recente por SETOR+UFCRM) tem precedência sobre o baseline
-- SalesFarma; sem nenhum dos dois, cai em 'A DEFINIR'. O baseline aqui
-- é o seed local tb_segmentacao_salesfarma_seed (ver comentário na
-- tabela) — a lógica de combinação é idêntica à fonte real.
-- =============================================================
CREATE OR REPLACE VIEW vw_segmentacao_efetiva AS
WITH edicao AS (
    SELECT setor, ufcrm, perfil, alterado_por, alterado_em
    FROM (
        SELECT e.*,
               ROW_NUMBER() OVER (PARTITION BY e.setor, e.ufcrm ORDER BY e.alterado_em DESC) AS rn
        FROM tb_segmentacao_medico e
    ) x
    WHERE rn = 1
)
SELECT
    COALESCE(e.setor, s.setor) AS setor,
    COALESCE(e.ufcrm, s.ufcrm) AS ufcrm,
    COALESCE(e.perfil, s.perfil, 'A DEFINIR') AS perfil_efetivo,
    CASE
        WHEN e.perfil IS NOT NULL THEN 'propagandista'
        WHEN s.perfil IS NOT NULL THEN 'salesfarma'
        ELSE 'a definir'
    END AS origem_do_valor,
    e.alterado_por,
    e.alterado_em
FROM tb_segmentacao_salesfarma_seed s
FULL OUTER JOIN edicao e ON e.setor = s.setor AND e.ufcrm = s.ufcrm;

COMMENT ON VIEW vw_segmentacao_efetiva IS 'Perfil de comunicação efetivo do médico por setor — mesma lógica de acheinfo_dev.renovai.vw_segmentacao_efetiva, baseline SalesFarma substituído pelo seed local tb_segmentacao_salesfarma_seed.';


-- =============================================================
-- vw_agente_medico
-- Mesma lógica de acheinfo_dev.renovai.vw_agente_medico: superfície de
-- busca do agente, LEFT JOIN de tb_perfil_medico_setor com
-- tb_dim_medicos por UFCRM, com NOME_BUSCA normalizado (maiúsculo,
-- sem acento) para busca por nome parcial.
-- =============================================================
CREATE OR REPLACE VIEW vw_agente_medico AS
SELECT
    p.setor AS setor,
    p.ufcrm AS ufcrm,
    p.nome_medico AS nome_medico,
    UPPER(translate(p.nome_medico, 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'AAAAAEEEEIIIIOOOOOUUUUC')) AS nome_busca,
    d.especialidade AS especialidade,
    d.cidade AS cidade,
    p.linha_produto AS linha_produto,
    p.posicao_ranking_setor AS posicao_ranking,
    (p.flag_no_painel = 1) AS no_painel,
    p.data_ultima_visita AS data_ultima_visita,
    p.meses_desde_ultima_visita AS meses_desde_ultima_visita,
    p.ciclo_top1_categoria AS categoria_1,
    p.ciclo_top2_categoria AS categoria_2,
    p.ciclo_top3_categoria AS categoria_3,
    p.ciclo_pct_ache AS participacao_ache_pct,
    p.ciclo_referencia AS ciclo_referencia
FROM tb_perfil_medico_setor p
LEFT JOIN tb_dim_medicos d ON d.ufcrm = p.ufcrm;

COMMENT ON VIEW vw_agente_medico IS 'Superfície de busca do agente do chat — mesma lógica de acheinfo_dev.renovai.vw_agente_medico.';


-- =============================================================
-- vw_agente_participacao
-- Mesma lógica de acheinfo_dev.renovai.vw_agente_participacao:
-- participação percentual dos produtos dentro de um mercado, NO SETOR
-- do propagandista, agrupado sobre vw_gold_auditpharma (aqui, a tabela
-- física simplificada de mesmo nome). REGEXP_EXTRACT(...) da fonte
-- Databricks vira substring(... from ...) em Postgres — mesmo padrão
-- de captura de grupo único entre parênteses.
-- =============================================================
CREATE OR REPLACE VIEW vw_agente_participacao AS
SELECT
    g.setor,
    g.mercado AS agrupamento,
    g.produto,
    substring(g.produto FROM '\(([^)]+)\)\s*$') AS laboratorio,
    bool_or(g.flag = 1) AS e_ache,
    ROUND(
        (100.0 * SUM(g.rx_mercado_atual)
         / NULLIF(SUM(SUM(g.rx_mercado_atual)) OVER (PARTITION BY g.setor, g.mercado), 0))::numeric,
        1
    ) AS participacao_pct,
    g.referencia
FROM vw_gold_auditpharma g
GROUP BY g.setor, g.mercado, g.produto, g.referencia;

COMMENT ON VIEW vw_agente_participacao IS 'Participação percentual de produtos por mercado, no setor — mesma lógica de acheinfo_dev.renovai.vw_agente_participacao, sobre a tabela física simplificada vw_gold_auditpharma.';


-- =============================================================
-- vw_visitacao_comentarios
-- Superfície local da Memória de Visitas. A view real também entrega apenas
-- visitas efetivas; manter o filtro aqui evita que tentativas sem contato
-- sejam interpretadas pelo agente como conversa com o médico.
-- =============================================================
CREATE OR REPLACE VIEW vw_visitacao_comentarios AS
SELECT setor, ufcrm, data_visita, visita_tipo, comentarios
FROM tb_visitacao_medica
WHERE visita_efetiva = TRUE;

COMMENT ON VIEW vw_visitacao_comentarios IS 'Visitas efetivas com comentários para a Memória de Visitas; equivalente local da view governada no Databricks.';
