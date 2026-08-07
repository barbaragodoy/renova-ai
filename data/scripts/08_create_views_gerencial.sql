-- =============================================================
-- Views gerenciais — RenovAI
-- Cria vw_hierarquia_gd e vw_recomendacoes_gerencial
-- =============================================================

-- 1. Visão de hierarquia GD com todos os propagandistas vinculados
CREATE OR REPLACE VIEW vw_hierarquia_gd AS
SELECT
    h.gd_matricula,
    h.gd_email,
    h.gd_nome,
    h.rep_matricula,
    h.setor,
    p.rep_nome,
    p.rep_email,
    p.cod_linha,
    p.ativo AS rep_ativo
FROM tb_hierarquia_gd h
JOIN tb_propagandistas p ON p.rep_matricula = h.rep_matricula;

COMMENT ON VIEW vw_hierarquia_gd IS
    'GD com propagandistas e setores vinculados. Fonte: tb_hierarquia_gd + tb_propagandistas.';


-- 2. Visão gerencial de recomendações com contexto completo
-- DROP explícito: CREATE OR REPLACE VIEW não permite renomear/remover
-- colunas de saída (ex.: timestamp_desconsideracao -> data_desconsideracao,
-- task 161830/163626) — só troca a definição preservando os mesmos nomes.
DROP VIEW IF EXISTS vw_recomendacoes_gerencial;
CREATE VIEW vw_recomendacoes_gerencial AS
SELECT
    rec.id_recomendacao,
    rec.ciclo_referencia,
    rec.tipo_recomendacao,
    rec.status_recomendacao,
    rec.ufcrm,
    rec.nome_medico,
    rec.posicao_ranking,
    rec.soma_pontuacao,
    rec.motivo_revisao,
    rec.justificativa_texto,
    rec.motivo_desconsideracao,
    rec.data_desconsideracao,
    rec.desconsiderado_por,
    rec.qtd_vezes_desconsiderado,
    rec.bloquear_novas_recomendacoes,
    rec.qtd_vezes_recomendado,
    rec.data_geracao,
    rec.data_ultima_verificacao,
    -- propagandista
    rec.rep_matricula,
    p.rep_nome,
    p.rep_email,
    p.setor,
    p.cod_linha,
    -- GD responsável
    h.gd_matricula,
    h.gd_nome,
    h.gd_email
FROM tb_recomendacoes_painel rec
JOIN tb_propagandistas p ON p.rep_matricula = rec.rep_matricula
LEFT JOIN tb_hierarquia_gd h
       ON h.rep_matricula = rec.rep_matricula
      AND h.setor         = rec.setor;

COMMENT ON VIEW vw_recomendacoes_gerencial IS
    'Recomendações com propagandista, GD e campos de auditoria. Base para endpoints gerenciais.';


-- 3. Métricas agregadas por GD e ciclo
-- (usada como query de referência; pode ser materializada futuramente)
CREATE OR REPLACE VIEW vw_metricas_gerencial AS
SELECT
    h.gd_matricula,
    h.gd_nome,
    rec.ciclo_referencia,
    rec.tipo_recomendacao,
    COUNT(*)                                              AS total_gerado,
    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'PENDENTE')       AS total_pendente,
    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'APLICADA')       AS total_aplicado,
    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'DESCONSIDERADA') AS total_desconsiderado,
    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'EXPIRADA')       AS total_expirado,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE rec.status_recomendacao = 'APLICADA')
        / NULLIF(COUNT(*), 0),
        1
    )                                                     AS taxa_aceite_pct
FROM tb_recomendacoes_painel rec
JOIN tb_propagandistas p ON p.rep_matricula = rec.rep_matricula
LEFT JOIN tb_hierarquia_gd h ON h.rep_matricula = rec.rep_matricula AND h.setor = rec.setor
GROUP BY h.gd_matricula, h.gd_nome, rec.ciclo_referencia, rec.tipo_recomendacao;

COMMENT ON VIEW vw_metricas_gerencial IS
    'Métricas de aceite e desconsideração por GD, ciclo e tipo de recomendação.';


-- 4. Principais motivos de desconsideração por GD e ciclo
CREATE OR REPLACE VIEW vw_motivos_desconsideracao AS
SELECT
    h.gd_matricula,
    h.gd_nome,
    rec.ciclo_referencia,
    rec.motivo_desconsideracao,
    COUNT(*) AS total
FROM tb_recomendacoes_painel rec
JOIN tb_propagandistas p ON p.rep_matricula = rec.rep_matricula
LEFT JOIN tb_hierarquia_gd h ON h.rep_matricula = rec.rep_matricula AND h.setor = rec.setor
WHERE rec.status_recomendacao = 'DESCONSIDERADA'
  AND rec.motivo_desconsideracao IS NOT NULL
GROUP BY h.gd_matricula, h.gd_nome, rec.ciclo_referencia, rec.motivo_desconsideracao
ORDER BY h.gd_matricula, rec.ciclo_referencia, total DESC;

COMMENT ON VIEW vw_motivos_desconsideracao IS
    'Principais motivos de desconsideração agrupados por GD e ciclo.';
