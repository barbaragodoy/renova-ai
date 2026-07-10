-- =============================================================
-- Visitação médica — ciclo 202507 + histórico
-- Cenário C4: médicos pos 1-10 de cada setor sem visita há > 5 meses
--   (última visita em janeiro/2025 = ~6 meses antes de julho/2025)
-- Demais médicos no painel têm visitas recentes
-- =============================================================

-- -------------------------------------------------------
-- SP_INTERIOR — visitas recentes (fev-jun/2025) pos 11-80
-- -------------------------------------------------------
INSERT INTO tb_visitacao_medica (setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  r.ufcrm,
  ('2025-02-01'::DATE + (RANDOM() * 150)::INT),
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 11 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- SP_INTERIOR — sem visita recente: pos 1-10 (C4: última visita jan/2025)
INSERT INTO tb_visitacao_medica (setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  r.ufcrm,
  ('2025-01-05'::DATE + (generate_series % 20)),
  TRUE,
  '202412'
FROM tb_ranking_medicos r
CROSS JOIN generate_series(1, 1)
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 1 AND 10
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- RJ_CAPITAL — visitas recentes pos 11-80
-- -------------------------------------------------------
INSERT INTO tb_visitacao_medica (setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  r.ufcrm,
  ('2025-02-01'::DATE + (RANDOM() * 150)::INT),
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 11 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- RJ_CAPITAL — sem visita recente pos 1-10
INSERT INTO tb_visitacao_medica (setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  r.ufcrm,
  ('2025-01-05'::DATE + (generate_series % 20)),
  TRUE,
  '202412'
FROM tb_ranking_medicos r
CROSS JOIN generate_series(1, 1)
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 1 AND 10
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- MG_SUL — visitas recentes pos 11-80
-- -------------------------------------------------------
INSERT INTO tb_visitacao_medica (setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia)
SELECT
  'MG_SUL',
  r.ufcrm,
  ('2025-02-01'::DATE + (RANDOM() * 150)::INT),
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 11 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- MG_SUL — sem visita recente pos 1-10
INSERT INTO tb_visitacao_medica (setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia)
SELECT
  'MG_SUL',
  r.ufcrm,
  ('2025-01-05'::DATE + (generate_series % 20)),
  TRUE,
  '202412'
FROM tb_ranking_medicos r
CROSS JOIN generate_series(1, 1)
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 1 AND 10
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;
