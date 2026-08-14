-- =============================================================
-- Cenários fictícios para tb_envios_recomendacoes_piloto — 3 grupos do
-- piloto (WhatsApp, E-mail, Controle). Usa SELECT dinâmico (não UUIDs
-- fixos) sobre tb_recomendacoes_painel: ID_RECOMENDACAO é gerado por
-- gen_random_uuid() no INSERT original, então varia a cada recriação da
-- massa de teste — hardcoded quebraria em qualquer reseed. Mesmo padrão
-- de 07_simulate_recomendacoes.sql (SELECT sobre tabela já populada, não
-- literais).
--
-- Exclui os IDs fixos de teste de desconsiderar (prefixo '10000000-')
-- para não misturar cenários de tasks diferentes.
--
-- Requer tb_propagandistas e tb_recomendacoes_painel já populadas
-- (02_populate_propagandistas.sql + gerar_recomendacoes.py ou
-- 10_popular_cenarios_desconsiderar.sql).
-- =============================================================

-- Cenário 1: envio WHATSAPP — REP001, 3 recomendações agrupadas no mesmo ID_ENVIO
INSERT INTO tb_envios_recomendacoes_piloto (
    id_envio, id_recomendacao, rep_matricula, grupo_piloto, canal_envio,
    data_hora_envio, ciclo_recomendacao, tipo_recomendacao
)
SELECT
    '20000000-0000-0000-0000-000000000001',
    id_recomendacao, rep_matricula, 'WHATSAPP', 'WHATSAPP',
    '2026-08-01 09:00:00+00', ciclo_referencia, tipo_recomendacao
FROM tb_recomendacoes_painel
WHERE rep_matricula = 'REP001'
  AND id_recomendacao::text NOT LIKE '10000000%'
ORDER BY id_recomendacao
LIMIT 3
ON CONFLICT (id_envio, id_recomendacao) DO NOTHING;

-- Cenário 2: envio EMAIL — REP002, 2 recomendações agrupadas no mesmo ID_ENVIO
INSERT INTO tb_envios_recomendacoes_piloto (
    id_envio, id_recomendacao, rep_matricula, grupo_piloto, canal_envio,
    data_hora_envio, ciclo_recomendacao, tipo_recomendacao
)
SELECT
    '20000000-0000-0000-0000-000000000002',
    id_recomendacao, rep_matricula, 'EMAIL', 'EMAIL',
    '2026-08-01 09:05:00+00', ciclo_referencia, tipo_recomendacao
FROM tb_recomendacoes_painel
WHERE rep_matricula = 'REP002'
  AND id_recomendacao::text NOT LIKE '10000000%'
ORDER BY id_recomendacao
LIMIT 2
ON CONFLICT (id_envio, id_recomendacao) DO NOTHING;

-- Cenário 3: registro CONTROLE (canal NENHUM) — REP003, 1 recomendação
INSERT INTO tb_envios_recomendacoes_piloto (
    id_envio, id_recomendacao, rep_matricula, grupo_piloto, canal_envio,
    data_hora_envio, ciclo_recomendacao, tipo_recomendacao
)
SELECT
    '20000000-0000-0000-0000-000000000003',
    id_recomendacao, rep_matricula, 'CONTROLE', 'NENHUM',
    '2026-08-01 09:10:00+00', ciclo_referencia, tipo_recomendacao
FROM tb_recomendacoes_painel
WHERE rep_matricula = 'REP003'
  AND id_recomendacao::text NOT LIKE '10000000%'
ORDER BY id_recomendacao
LIMIT 1
ON CONFLICT (id_envio, id_recomendacao) DO NOTHING;
