-- =============================================================
-- Painel médico — ciclo 202507
-- 80 médicos por setor no painel (posições 1-80 do ranking)
-- Cenários garantidos:
--   C1: posição <= 100 fora do painel → médicos 81-100 de cada setor
--   C2: posição <= 100 no painel      → médicos 1-80 de cada setor
--   C3: posição > 100 no painel       → médicos 101-110 forçados no painel
--   C4: médico sem visita há > 5 meses → controlado em 07_populate_visitacao
-- =============================================================

-- -------------------------------------------------------
-- SP_INTERIOR — CARDIO (ufcrm SP00001-SP00080 no painel)
-- -------------------------------------------------------
INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  r.ufcrm,
  r.nome_medico,
  CASE WHEN r.posicao_ranking % 3 = 0 THEN 'Cardiologista'
       WHEN r.posicao_ranking % 3 = 1 THEN 'Clínico Geral'
       ELSE 'Internista' END,
  '2025-01-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 1 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- Cenário C3: médicos fora do corte (pos 101-110) forçados no painel
INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  r.ufcrm,
  r.nome_medico,
  'Cardiologista',
  '2024-06-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 101 AND 110
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- SP_INTERIOR — SNC (ufcrm SP00201-SP00280 no painel)
-- -------------------------------------------------------
INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  r.ufcrm,
  r.nome_medico,
  CASE WHEN r.posicao_ranking % 2 = 0 THEN 'Neurologista' ELSE 'Psiquiatra' END,
  '2025-01-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking BETWEEN 1 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  r.ufcrm,
  r.nome_medico,
  'Neurologista',
  '2024-06-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking BETWEEN 101 AND 110
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- RJ_CAPITAL — CARDIO
-- -------------------------------------------------------
INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  r.ufcrm,
  r.nome_medico,
  CASE WHEN r.posicao_ranking % 3 = 0 THEN 'Cardiologista'
       WHEN r.posicao_ranking % 3 = 1 THEN 'Clínico Geral'
       ELSE 'Internista' END,
  '2025-01-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 1 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  r.ufcrm,
  r.nome_medico,
  'Cardiologista',
  '2024-06-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 101 AND 110
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- RJ_CAPITAL — SNC
-- -------------------------------------------------------
INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  r.ufcrm,
  r.nome_medico,
  CASE WHEN r.posicao_ranking % 2 = 0 THEN 'Neurologista' ELSE 'Psiquiatra' END,
  '2025-01-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking BETWEEN 1 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  r.ufcrm,
  r.nome_medico,
  'Neurologista',
  '2024-06-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking BETWEEN 101 AND 110
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- MG_SUL — CARDIO
-- -------------------------------------------------------
INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'MG_SUL',
  r.ufcrm,
  r.nome_medico,
  CASE WHEN r.posicao_ranking % 3 = 0 THEN 'Cardiologista'
       WHEN r.posicao_ranking % 3 = 1 THEN 'Clínico Geral'
       ELSE 'Internista' END,
  '2025-01-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 1 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'MG_SUL',
  r.ufcrm,
  r.nome_medico,
  'Cardiologista',
  '2024-06-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking BETWEEN 101 AND 110
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- MG_SUL — SNC
-- -------------------------------------------------------
INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'MG_SUL',
  r.ufcrm,
  r.nome_medico,
  CASE WHEN r.posicao_ranking % 2 = 0 THEN 'Neurologista' ELSE 'Psiquiatra' END,
  '2025-01-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking BETWEEN 1 AND 80
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;

INSERT INTO tb_painel_medico (setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia)
SELECT
  'MG_SUL',
  r.ufcrm,
  r.nome_medico,
  'Neurologista',
  '2024-06-01'::DATE,
  TRUE,
  '202507'
FROM tb_ranking_medicos r
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking BETWEEN 101 AND 110
  AND r.ciclo_referencia = '202507'
ON CONFLICT DO NOTHING;
