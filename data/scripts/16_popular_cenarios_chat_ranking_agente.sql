-- =============================================================
-- Cenários de teste — Chat / Ranking / Agente.
--
-- Reaproveita SETOR/UFCRM já existentes em 02_populate_propagandistas.sql
-- e 03_populate_ranking.sql (REP001..REP010, SP00001..SP00003,
-- SP00201..SP00203, MG00001..) para os testes ponta a ponta poderem
-- atravessar tb_propagandistas -> tb_ranking_medicos (já existentes) e
-- as tabelas novas sem precisar de fixture paralela.
--
-- SP00001 (Dr. A. Medico SP-C-1, setor SP_INTERIOR, REP001) é o
-- "médico completo": tem linha em todas as tabelas novas, cobrindo o
-- fluxo ponta a ponta de Chat/Ranking/Agente num só UFCRM. SP00002 e
-- SP00201 ficam propositalmente incompletos (sem conduta, sem edição
-- de segmentação) para cobrir os cenários de dado ausente que a
-- interface precisa tratar sem quebrar.
-- =============================================================


-- =============================================================
-- tb_perfil_medico_setor
-- =============================================================
INSERT INTO tb_perfil_medico_setor (
    ciclo_referencia, setor, linha_produto, ufcrm, nome_medico,
    posicao_ranking_setor, pontos, flag_no_painel, qtd_medicos_painel_setor,
    recomendacao, motivo_recomendacao, data_ultima_visita, meses_desde_ultima_visita,
    ciclos_no_painel_janela,
    ciclo_top1_categoria, ciclo_top1_pct, ciclo_top2_categoria, ciclo_top2_pct,
    ciclo_top3_categoria, ciclo_top3_pct,
    ciclo_top1_produto, ciclo_top2_produto, ciclo_top3_produto,
    ciclo_qtd_categorias, ciclo_qtd_produtos, ciclo_rx_total, ciclo_rx_ache, ciclo_pct_ache,
    ytd_top1_categoria, ytd_top1_pct, ytd_qtd_categorias, ytd_rx_total, ytd_rx_ache, ytd_pct_ache,
    geral_top1_categoria, geral_top1_pct, geral_top1_produto,
    geral_qtd_categorias, geral_qtd_produtos, geral_rx_total, geral_rx_ache, geral_pct_ache,
    produto_recomendado_linha, produto_recomendado_categoria,
    categoria_esta_no_top3, ultimo_periodo_na_categoria, origem_da_recomendacao,
    ja_prescreve_o_produto, prescreve_no_ciclo, prescreve_no_ano, rec_e_top1,
    produto_recomendado_ache, produto_recomendado_ache_linha, produto_recomendado_ache_categoria,
    periodo_prescricao_usado, dt_geracao
) VALUES
    -- SP00001: médico completo, ranking bom, painel cheio de dado.
    ('202608', 'SP_INTERIOR', '1', 'SP00001', 'Dr. A. Medico SP-C-1',
     1, 950.50, 1, 280,
     'MANTER', 'TOP1_MANTIDO', '2026-08-10', 0,
     6,
     'HIPERTENSAO ARTERIAL', 42.5, 'DISLIPIDEMIA', 30.0, 'INSUFICIENCIA CARDIACA', 15.0,
     'RENOVAI CARDIO FORTE (ACHE)', 'CONCORRENTE CARDIO X', 'CONCORRENTE CARDIO Y',
     3, 5, 1200.0, 480.0, 40.0,
     'HIPERTENSAO ARTERIAL', 41.0, 4, 9800.0, 3900.0, 39.8,
     'HIPERTENSAO ARTERIAL', 39.5, 'RENOVAI CARDIO FORTE (ACHE)',
     5, 8, 42000.0, 16500.0, 39.3,
     '1', 'HIPERTENSAO ARTERIAL',
     1, 1, 'TOP3_PRESCRICAO',
     1, 1, 1, 1,
     'RENOVAI CARDIO FORTE', '1', 'HIPERTENSAO ARTERIAL',
     3, '2026-08-20'),

    -- SP00002: painel, mas dado esparso (sem categoria geral, sem produto recomendado).
    ('202608', 'SP_INTERIOR', '1', 'SP00002', 'Dr. B. Medico SP-C-2',
     2, 820.00, 1, 280,
     'REVISAR', 'FORA_TOP3', NULL, NULL,
     2,
     'DISLIPIDEMIA', 28.0, NULL, NULL, NULL, NULL,
     'CONCORRENTE CARDIO X', NULL, NULL,
     1, 2, 300.0, 60.0, 20.0,
     NULL, NULL, NULL, NULL, NULL, NULL,
     NULL, NULL, NULL,
     NULL, NULL, NULL, NULL, NULL,
     NULL, NULL,
     0, NULL, NULL,
     0, 0, 0, 0,
     NULL, NULL, NULL,
     NULL, '2026-08-20'),

    -- SP00201: setor SP_INTERIOR, linha SNC (REP002).
    ('202608', 'SP_INTERIOR', '2', 'SP00201', 'Dr. A. Medico SP-S-1',
     1, 890.00, 1, 265,
     'MANTER', 'TOP1_MANTIDO', '2026-07-28', 1,
     4,
     'EPILEPSIA', 35.0, 'ENXAQUECA', 25.0, NULL, NULL,
     'RENOVAI NEURO PLUS (ACHE)', 'CONCORRENTE SNC Z', NULL,
     2, 3, 700.0, 300.0, 42.8,
     'EPILEPSIA', 33.0, 2, 5200.0, 2100.0, 40.4,
     'EPILEPSIA', 31.0, 'RENOVAI NEURO PLUS (ACHE)',
     3, 4, 22000.0, 8800.0, 40.0,
     '2', 'EPILEPSIA',
     1, 1, 'TOP3_PRESCRICAO',
     1, 1, 1, 1,
     'RENOVAI NEURO PLUS', '2', 'EPILEPSIA',
     3, '2026-08-20'),

    -- MG00001: setor MG_SUL, linha CARDIO (REP008), cidade/especialidade diferentes.
    ('202608', 'MG_SUL', '1', 'MG00001', 'Dr. A. Medico MG-C-1',
     1, 910.00, 1, 300,
     'MANTER', 'TOP1_MANTIDO', '2026-08-05', 0,
     5,
     'HIPERTENSAO ARTERIAL', 38.0, 'DISLIPIDEMIA', 22.0, NULL, NULL,
     'RENOVAI CARDIO FORTE (ACHE)', 'CONCORRENTE CARDIO X', NULL,
     2, 3, 900.0, 340.0, 37.7,
     'HIPERTENSAO ARTERIAL', 36.0, 3, 7400.0, 2700.0, 36.5,
     'HIPERTENSAO ARTERIAL', 34.0, 'RENOVAI CARDIO FORTE (ACHE)',
     4, 6, 31000.0, 11500.0, 37.1,
     '1', 'HIPERTENSAO ARTERIAL',
     1, 1, 'TOP3_PRESCRICAO',
     1, 1, 1, 1,
     'RENOVAI CARDIO FORTE', '1', 'HIPERTENSAO ARTERIAL',
     3, '2026-08-20')
;


-- =============================================================
-- tb_ranking_medicos_validacao
-- =============================================================
INSERT INTO tb_ranking_medicos_validacao (
    ciclo_referencia, setor, ufcrm, nome_medico, pontos, posicao_ranking_setor,
    flag_no_painel, qtd_medicos_painel_setor, data_ultima_visita, meses_desde_ultima_visita,
    flag_sem_visita_5_meses, flag_sem_visita_registrada, ciclos_no_painel_janela,
    flag_nunca_visitado_com_janela, limite_painel, recomendacao, motivo_recomendacao
) VALUES
    ('202608', 'SP_INTERIOR', 'SP00001', 'Dr. A. Medico SP-C-1', 950.50, 1,
     1, 280, '2026-08-10', 0,
     0, 0, 6,
     0, 318, 'MANTER', 'TOP1_MANTIDO'),

    ('202608', 'SP_INTERIOR', 'SP00002', 'Dr. B. Medico SP-C-2', 820.00, 2,
     1, 280, NULL, NULL,
     1, 1, 2,
     0, 318, 'REVISAR', 'FORA_TOP3'),

    ('202608', 'SP_INTERIOR', 'SP00201', 'Dr. A. Medico SP-S-1', 890.00, 1,
     1, 265, '2026-07-28', 1,
     0, 0, 4,
     0, 318, 'MANTER', 'TOP1_MANTIDO'),

    ('202608', 'MG_SUL', 'MG00001', 'Dr. A. Medico MG-C-1', 910.00, 1,
     1, 300, '2026-08-05', 0,
     0, 0, 5,
     0, 318, 'MANTER', 'TOP1_MANTIDO')
;


-- =============================================================
-- tb_dim_medicos
-- =============================================================
INSERT INTO tb_dim_medicos (ufcrm, medico, especialidade, cidade) VALUES
    ('SP00001', 'Dr. A. Medico SP-C-1', 'CARDIOLOGIA', 'SAO PAULO'),
    ('SP00002', 'Dr. B. Medico SP-C-2', 'CARDIOLOGIA', 'CAMPINAS'),
    ('SP00201', 'Dr. A. Medico SP-S-1', 'NEUROLOGIA', 'RIBEIRAO PRETO'),
    ('MG00001', 'Dr. A. Medico MG-C-1', 'CARDIOLOGIA', 'BELO HORIZONTE')
;


-- =============================================================
-- tb_conduta_medico
-- Só SP00001 tem conduta registrada — SP00002/SP00201/MG00001 cobrem
-- o cenário "nunca registrado" (NULL na leitura, sem quebrar a tela).
-- =============================================================
INSERT INTO tb_conduta_medico (id_registro, setor, ufcrm, texto, condicao, origem_texto, registrado_por, registrado_em, versao_esquema) VALUES
    (gen_random_uuid()::text, 'SP_INTERIOR', 'SP00001',
     'Prefere iniciar com monoterapia e só escala se pressão não responde em 30 dias.',
     NULL, 'digitado', 'REP001', '2026-08-10 09:30:00', 1),
    (gen_random_uuid()::text, 'SP_INTERIOR', 'SP00001',
     'Costuma pedir material de referência antes de trocar de linha terapêutica.',
     NULL, 'ditado', 'REP001', '2026-08-15 11:00:00', 1)
;


-- =============================================================
-- tb_segmentacao_medico
-- Só SP00001 tem edição do propagandista — os demais caem no baseline
-- (tb_segmentacao_salesfarma_seed) ou em 'A DEFINIR'.
-- =============================================================
INSERT INTO tb_segmentacao_medico (setor, ufcrm, perfil, alterado_por, alterado_em, perfil_anterior, observacao, versao_esquema) VALUES
    ('SP_INTERIOR', 'SP00001', 'RELACIONAL', 'REP001', '2026-08-15 11:05:00', 'PESSOAL',
     'Prioriza construir relação antes de falar de produto.', 1)
;


-- =============================================================
-- tb_segmentacao_salesfarma_seed
-- Baseline SalesFarma simulado. SP00001 tem baseline (mas é
-- sobreposto pela edição acima). SP00002 só tem baseline, sem edição.
-- SP00201 tem linha com perfil NULL (residual "PLANO 90"/"NOVO
-- MEDICO", igual ao caso real) -> cai em 'A DEFINIR'. MG00001 não tem
-- nenhuma linha (nem aqui nem em tb_segmentacao_medico) -> também
-- 'A DEFINIR', cenário de médico fora de qualquer cobertura.
-- =============================================================
INSERT INTO tb_segmentacao_salesfarma_seed (setor, ufcrm, perfil) VALUES
    ('SP_INTERIOR', 'SP00001', 'PESSOAL'),
    ('SP_INTERIOR', 'SP00002', 'ANALITICO'),
    ('SP_INTERIOR', 'SP00201', NULL)
;


-- =============================================================
-- vw_gold_auditpharma (tabela física simplificada)
-- 2 mercados fictícios, cobrindo os dois setores usados acima, com
-- produto Aché (FLAG=1) e concorrentes (FLAG=0) em cada.
-- =============================================================
INSERT INTO vw_gold_auditpharma (
    referencia, setor, mercado, produto, esp_audit, flag, rx_mercado_atual, rx_mercado_anterior, cod_linha, ufcrm
) VALUES
    ('202608', 'SP_INTERIOR', 'HIPERTENSAO ARTERIAL', 'RENOVAI CARDIO FORTE (ACHE)', 'CARDIOLOGIA', 1, 4200.00, 3950.00, '51', 'SP00001'),
    ('202608', 'SP_INTERIOR', 'HIPERTENSAO ARTERIAL', 'CONCORRENTE CARDIO X (LAB X)', 'CARDIOLOGIA', 0, 3100.00, 3000.00, '51', 'SP00001'),
    ('202608', 'SP_INTERIOR', 'HIPERTENSAO ARTERIAL', 'CONCORRENTE CARDIO Y (LAB Y)', 'CARDIOLOGIA', 0, 2600.00, 2700.00, '51', 'SP00001'),
    ('202608', 'SP_INTERIOR', 'EPILEPSIA', 'RENOVAI NEURO PLUS (ACHE)', 'NEUROLOGIA', 1, 1800.00, 1650.00, '52', 'SP00201'),
    ('202608', 'SP_INTERIOR', 'EPILEPSIA', 'CONCORRENTE SNC Z (LAB Z)', 'NEUROLOGIA', 0, 2200.00, 2100.00, '52', 'SP00201'),
    ('202608', 'MG_SUL', 'HIPERTENSAO ARTERIAL', 'RENOVAI CARDIO FORTE (ACHE)', 'CARDIOLOGIA', 1, 3600.00, 3400.00, '51', 'MG00001'),
    ('202608', 'MG_SUL', 'HIPERTENSAO ARTERIAL', 'CONCORRENTE CARDIO X (LAB X)', 'CARDIOLOGIA', 0, 2900.00, 2850.00, '51', 'MG00001')
;


-- =============================================================
-- vw_agente_produtos (tabela física simplificada)
-- =============================================================
INSERT INTO vw_agente_produtos (linha_produto, especialidade, produto, categoria_atc, area_terapeutica, prioridade, motivo, ordem_sugerida) VALUES
    ('1', 'CARDIOLOGIA', 'RENOVAI CARDIO FORTE', 'ANTI-HIPERTENSIVO', 'Cardio', 1, 'area corresponde a especialidade CARDIOLOGIA', 1),
    ('1', 'CARDIOLOGIA', 'RENOVAI CARDIO LEVE', 'HIPOLIPEMIANTE', 'Cardio', 1, 'area corresponde a especialidade CARDIOLOGIA', 2),
    ('1', 'CARDIOLOGIA', 'RENOVAI GASTRO BASE', 'ANTIACIDO', 'Gastro', 2, 'outra area da linha, mantida porque a regra ordena e nao filtra', 3),
    ('2', 'NEUROLOGIA', 'RENOVAI NEURO PLUS', 'ANTIEPILEPTICO', 'SNC', 1, 'area corresponde a especialidade NEUROLOGIA', 1),
    ('2', 'NEUROLOGIA', 'RENOVAI NEURO CALM', 'ANTIEPILEPTICO', 'SNC', 1, 'area corresponde a especialidade NEUROLOGIA', 2)
;


-- =============================================================
-- tb_agente_persona
-- =============================================================
INSERT INTO tb_agente_persona (perfil, pergunta, texto, documentos, kb_versao, dt_geracao, fonte_hash) VALUES
    ('ANALITICO',
     'Como conduzir uma visita com um médico de perfil ANALÍTICO?',
     'Leve dado clínico e comparativo direto. Traga estudo, número e critério de decisão — evite apelo emocional ou histórias de caso isoladas.',
     '{"documentos": ["persona-analitico-v1.md"]}', 'kb-2026-08-20', '2026-08-20 08:00:00', 'seed-local-analitico'),
    ('PERFORMANCE',
     'Como conduzir uma visita com um médico de perfil PERFORMANCE?',
     'Seja objetivo e vá direto ao ponto: resultado esperado, tempo de resposta, e por que o produto resolve mais rápido que a alternativa atual.',
     '{"documentos": ["persona-performance-v1.md"]}', 'kb-2026-08-20', '2026-08-20 08:00:00', 'seed-local-performance'),
    ('PESSOAL',
     'Como conduzir uma visita com um médico de perfil PESSOAL?',
     'Construa relação antes de falar de produto. Pergunte sobre a rotina do consultório, mostre interesse genuíno, deixe o produto para o fim da conversa.',
     '{"documentos": ["persona-pessoal-v1.md"]}', 'kb-2026-08-20', '2026-08-20 08:00:00', 'seed-local-pessoal'),
    ('RELACIONAL',
     'Como conduzir uma visita com um médico de perfil RELACIONAL?',
     'Priorize o vínculo de longo prazo: reconheça histórico de parceria, evite pressão de fechamento, ofereça suporte contínuo em vez de urgência.',
     '{"documentos": ["persona-relacional-v1.md"]}', 'kb-2026-08-20', '2026-08-20 08:00:00', 'seed-local-relacional')
;


-- =============================================================
-- tb_renovai_parametros
-- Valores REAIS confirmados via DESCRIBE/SELECT contra
-- acheinfo_dev.renovai.tb_renovai_parametros em 26/08/2026.
-- =============================================================
INSERT INTO tb_renovai_parametros (id, limite_painel_padrao, janela_visita_meses, janela_painel_ciclos, alterado_por, dt_alteracao) VALUES
    (1, 318, 3, 3, 'seed-local', now())
ON CONFLICT (id) DO NOTHING;


-- tb_agente_log fica vazia de propósito: é write-only (log de
-- interação), preenchida pelos próprios testes/execuções, não por
-- seed fixo.
