-- =============================================================
-- Cenários fictícios para POST /recomendacoes/{id_recomendacao}/desconsiderar
-- (task 161830/163626). IDs fixos para permitir testes de
-- integração/manuais determinísticos contra o Postgres local.
-- Requer tb_propagandistas já populada (02_populate_propagandistas.sql):
-- REP001 (ana.lima@ache.com.br) e REP002 (bruno.melo@ache.com.br).
-- =============================================================

INSERT INTO tb_recomendacoes_painel (
    id_recomendacao, rep_matricula, setor, cod_linha, ufcrm, nome_medico,
    tipo_recomendacao, status_recomendacao, posicao_ranking, soma_pontuacao,
    ciclo_referencia
) VALUES
    -- Cenário 1: PENDENTE, sem histórico de desconsideração (caminho feliz)
    ('10000000-0000-0000-0000-000000000001', 'REP001', 'SP_INTERIOR', 'CARDIO',
     'SP00001', 'Dr. Teste Pendente', 'ENTRADA_PAINEL', 'PENDENTE', 5, 800.0, '202507'),

    -- Cenário 3: PENDENTE, mas pertence a OUTRO propagandista (REP002) —
    -- usado para validar o 403 quando REP001 tenta desconsiderar.
    ('10000000-0000-0000-0000-000000000003', 'REP002', 'SP_INTERIOR', 'SNC',
     'SP00003', 'Dr. Teste De Outro Rep', 'ENTRADA_PAINEL', 'PENDENTE', 8, 700.0, '202507'),

    -- Cenário 4: EXPIRADA — estado incompatível (não é PENDENTE nem DESCONSIDERADA)
    ('10000000-0000-0000-0000-000000000004', 'REP001', 'SP_INTERIOR', 'CARDIO',
     'SP00004', 'Dr. Teste Expirada', 'REVISAO_PAINEL', 'EXPIRADA', 450, 50.0, '202506'),

    -- Cenário 5: PENDENTE, REVISAO_PAINEL — usado para confirmar que
    -- /recomendacoes/revisao também para de retornar após desconsiderar.
    ('10000000-0000-0000-0000-000000000005', 'REP001', 'SP_INTERIOR', 'CARDIO',
     'SP00005', 'Dr. Teste Revisao Pendente', 'REVISAO_PAINEL', 'PENDENTE', 420, 40.0, '202507')
ON CONFLICT (id_recomendacao) DO NOTHING;

-- Cenário 2: já DESCONSIDERADA anteriormente — histórico completo já
-- preenchido, para validar 409 (idempotência) e QTD_VEZES_DESCONSIDERADO > 0.
INSERT INTO tb_recomendacoes_painel (
    id_recomendacao, rep_matricula, setor, cod_linha, ufcrm, nome_medico,
    tipo_recomendacao, status_recomendacao, posicao_ranking, soma_pontuacao,
    ciclo_referencia, motivo_desconsideracao, desconsiderado_por,
    data_desconsideracao, qtd_vezes_desconsiderado, bloquear_novas_recomendacoes
) VALUES
    ('10000000-0000-0000-0000-000000000002', 'REP001', 'SP_INTERIOR', 'CARDIO',
     'SP00002', 'Dr. Teste Ja Desconsiderada', 'ENTRADA_PAINEL', 'DESCONSIDERADA', 6, 750.0, '202507',
     'MEDICO_APOSENTADO', 'REP001', '2026-07-15 10:00:00+00', 1, FALSE)
ON CONFLICT (id_recomendacao) DO NOTHING;
