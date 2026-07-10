-- =============================================================
-- Ranking de médicos — 150 por setor, ciclo 202507
-- Médicos gerados com ufcrm sequencial por setor
-- Cenários garantidos (por setor/linha):
--   posicao 1-100  → dentro do corte, candidatos a ENTRADA
--   posicao 101-150 → fora do corte (> 400 simulado por proporção)
-- Nota: o corte real é <= 400. Aqui usamos 150 médicos por
-- questão de volume de simulação; os cenários são relativos.
-- =============================================================

-- -------------------------------------------------------
-- SP_INTERIOR / CARDIO — 150 médicos (pos 1-150)
-- -------------------------------------------------------
INSERT INTO tb_ranking_medicos
  (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  'CARDIO',
  'SP' || LPAD(n::TEXT, 5, '0'),
  'Dr. ' || chr(64 + ((n-1) % 26 + 1)) || '. Medico SP-C-' || n,
  ROUND((RANDOM() * 900 + 100)::NUMERIC, 4),
  n,
  '202507'
FROM generate_series(1, 150) AS n
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- SP_INTERIOR / SNC — 150 médicos (pos 1-150)
-- -------------------------------------------------------
INSERT INTO tb_ranking_medicos
  (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
SELECT
  'SP_INTERIOR',
  'SNC',
  'SP' || LPAD((n + 200)::TEXT, 5, '0'),
  'Dr. ' || chr(64 + ((n-1) % 26 + 1)) || '. Medico SP-S-' || n,
  ROUND((RANDOM() * 900 + 100)::NUMERIC, 4),
  n,
  '202507'
FROM generate_series(1, 150) AS n
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- RJ_CAPITAL / CARDIO — 150 médicos (pos 1-150)
-- -------------------------------------------------------
INSERT INTO tb_ranking_medicos
  (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  'CARDIO',
  'RJ' || LPAD(n::TEXT, 5, '0'),
  'Dr. ' || chr(64 + ((n-1) % 26 + 1)) || '. Medico RJ-C-' || n,
  ROUND((RANDOM() * 900 + 100)::NUMERIC, 4),
  n,
  '202507'
FROM generate_series(1, 150) AS n
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- RJ_CAPITAL / SNC — 150 médicos (pos 1-150)
-- -------------------------------------------------------
INSERT INTO tb_ranking_medicos
  (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
SELECT
  'RJ_CAPITAL',
  'SNC',
  'RJ' || LPAD((n + 200)::TEXT, 5, '0'),
  'Dr. ' || chr(64 + ((n-1) % 26 + 1)) || '. Medico RJ-S-' || n,
  ROUND((RANDOM() * 900 + 100)::NUMERIC, 4),
  n,
  '202507'
FROM generate_series(1, 150) AS n
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- MG_SUL / CARDIO — 150 médicos (pos 1-150)
-- -------------------------------------------------------
INSERT INTO tb_ranking_medicos
  (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
SELECT
  'MG_SUL',
  'CARDIO',
  'MG' || LPAD(n::TEXT, 5, '0'),
  'Dr. ' || chr(64 + ((n-1) % 26 + 1)) || '. Medico MG-C-' || n,
  ROUND((RANDOM() * 900 + 100)::NUMERIC, 4),
  n,
  '202507'
FROM generate_series(1, 150) AS n
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- MG_SUL / SNC — 150 médicos (pos 1-150)
-- -------------------------------------------------------
INSERT INTO tb_ranking_medicos
  (setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia)
SELECT
  'MG_SUL',
  'SNC',
  'MG' || LPAD((n + 200)::TEXT, 5, '0'),
  'Dr. ' || chr(64 + ((n-1) % 26 + 1)) || '. Medico MG-S-' || n,
  ROUND((RANDOM() * 900 + 100)::NUMERIC, 4),
  n,
  '202507'
FROM generate_series(1, 150) AS n
ON CONFLICT DO NOTHING;
