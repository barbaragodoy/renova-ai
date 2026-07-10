-- =============================================================
-- Prescrições — últimos 4 trimestres (jul/2024 a jun/2025)
-- Mix de fabricantes: Aché + concorrentes
-- Medicamentos Cardio: Vastarel, Concor, Crestor, Lisinopril
-- Medicamentos SNC: Rivotril, Zolpidem, Venlaxin, Depakote
-- =============================================================

-- -------------------------------------------------------
-- SP_INTERIOR — CARDIO (médicos SP00001-SP00090)
-- -------------------------------------------------------
INSERT INTO tb_prescricoes_geral
  (codigo_medico, ufcrm, nome_medico, especialidade, nome_medicacao, fabricante, quantidade, data_prescricao, setor)
SELECT
  'COD-' || r.ufcrm,
  r.ufcrm,
  r.nome_medico,
  'Cardiologista',
  med.nome,
  med.fab,
  (RANDOM() * 50 + 5)::INT,
  ('2024-07-01'::DATE + (RANDOM() * 365)::INT),
  'SP_INTERIOR'
FROM tb_ranking_medicos r
CROSS JOIN (VALUES
  ('Vastarel MR', 'Servier'),
  ('Concor 5mg', 'Merck'),
  ('Crestor 10mg', 'AstraZeneca'),
  ('Lisinopril 10mg', 'Aché'),
  ('Atenolol 50mg', 'Aché'),
  ('Losartana 50mg', 'EMS')
) AS med(nome, fab)
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking <= 90
  AND r.ciclo_referencia = '202507'
  AND RANDOM() > 0.3  -- ~70% de cobertura para variar
ON CONFLICT DO NOTHING;

-- SP_INTERIOR — SNC
INSERT INTO tb_prescricoes_geral
  (codigo_medico, ufcrm, nome_medico, especialidade, nome_medicacao, fabricante, quantidade, data_prescricao, setor)
SELECT
  'COD-' || r.ufcrm,
  r.ufcrm,
  r.nome_medico,
  'Neurologista',
  med.nome,
  med.fab,
  (RANDOM() * 40 + 5)::INT,
  ('2024-07-01'::DATE + (RANDOM() * 365)::INT),
  'SP_INTERIOR'
FROM tb_ranking_medicos r
CROSS JOIN (VALUES
  ('Venlaxin 75mg', 'Aché'),
  ('Rivotril 2mg', 'Roche'),
  ('Zolpidem 10mg', 'EMS'),
  ('Depakote 500mg', 'Abbott'),
  ('Sertralina 50mg', 'Aché'),
  ('Risperidona 2mg', 'Janssen')
) AS med(nome, fab)
WHERE r.setor = 'SP_INTERIOR' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking <= 90
  AND r.ciclo_referencia = '202507'
  AND RANDOM() > 0.3
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- RJ_CAPITAL — CARDIO
-- -------------------------------------------------------
INSERT INTO tb_prescricoes_geral
  (codigo_medico, ufcrm, nome_medico, especialidade, nome_medicacao, fabricante, quantidade, data_prescricao, setor)
SELECT
  'COD-' || r.ufcrm,
  r.ufcrm,
  r.nome_medico,
  'Cardiologista',
  med.nome,
  med.fab,
  (RANDOM() * 50 + 5)::INT,
  ('2024-07-01'::DATE + (RANDOM() * 365)::INT),
  'RJ_CAPITAL'
FROM tb_ranking_medicos r
CROSS JOIN (VALUES
  ('Vastarel MR', 'Servier'),
  ('Lisinopril 10mg', 'Aché'),
  ('Atenolol 50mg', 'Aché'),
  ('Amlodipino 5mg', 'Pfizer'),
  ('Losartana 50mg', 'EMS'),
  ('Metformina 850mg', 'Merck')
) AS med(nome, fab)
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking <= 90
  AND r.ciclo_referencia = '202507'
  AND RANDOM() > 0.3
ON CONFLICT DO NOTHING;

-- RJ_CAPITAL — SNC
INSERT INTO tb_prescricoes_geral
  (codigo_medico, ufcrm, nome_medico, especialidade, nome_medicacao, fabricante, quantidade, data_prescricao, setor)
SELECT
  'COD-' || r.ufcrm,
  r.ufcrm,
  r.nome_medico,
  'Psiquiatra',
  med.nome,
  med.fab,
  (RANDOM() * 40 + 5)::INT,
  ('2024-07-01'::DATE + (RANDOM() * 365)::INT),
  'RJ_CAPITAL'
FROM tb_ranking_medicos r
CROSS JOIN (VALUES
  ('Venlaxin 75mg', 'Aché'),
  ('Rivotril 2mg', 'Roche'),
  ('Sertralina 50mg', 'Aché'),
  ('Zolpidem 10mg', 'EMS'),
  ('Quetiapina 100mg', 'AstraZeneca'),
  ('Escitalopram 10mg', 'Lundbeck')
) AS med(nome, fab)
WHERE r.setor = 'RJ_CAPITAL' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking <= 90
  AND r.ciclo_referencia = '202507'
  AND RANDOM() > 0.3
ON CONFLICT DO NOTHING;

-- -------------------------------------------------------
-- MG_SUL — CARDIO
-- -------------------------------------------------------
INSERT INTO tb_prescricoes_geral
  (codigo_medico, ufcrm, nome_medico, especialidade, nome_medicacao, fabricante, quantidade, data_prescricao, setor)
SELECT
  'COD-' || r.ufcrm,
  r.ufcrm,
  r.nome_medico,
  'Clínico Geral',
  med.nome,
  med.fab,
  (RANDOM() * 50 + 5)::INT,
  ('2024-07-01'::DATE + (RANDOM() * 365)::INT),
  'MG_SUL'
FROM tb_ranking_medicos r
CROSS JOIN (VALUES
  ('Lisinopril 10mg', 'Aché'),
  ('Atenolol 50mg', 'Aché'),
  ('Concor 5mg', 'Merck'),
  ('Crestor 10mg', 'AstraZeneca'),
  ('Amlodipino 5mg', 'Pfizer'),
  ('Hidroclorotiazida 25mg', 'EMS')
) AS med(nome, fab)
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'CARDIO'
  AND r.posicao_ranking <= 90
  AND r.ciclo_referencia = '202507'
  AND RANDOM() > 0.3
ON CONFLICT DO NOTHING;

-- MG_SUL — SNC
INSERT INTO tb_prescricoes_geral
  (codigo_medico, ufcrm, nome_medico, especialidade, nome_medicacao, fabricante, quantidade, data_prescricao, setor)
SELECT
  'COD-' || r.ufcrm,
  r.ufcrm,
  r.nome_medico,
  'Neurologista',
  med.nome,
  med.fab,
  (RANDOM() * 40 + 5)::INT,
  ('2024-07-01'::DATE + (RANDOM() * 365)::INT),
  'MG_SUL'
FROM tb_ranking_medicos r
CROSS JOIN (VALUES
  ('Venlaxin 75mg', 'Aché'),
  ('Sertralina 50mg', 'Aché'),
  ('Depakote 500mg', 'Abbott'),
  ('Rivotril 2mg', 'Roche'),
  ('Lamotrigina 100mg', 'GSK'),
  ('Zolpidem 10mg', 'EMS')
) AS med(nome, fab)
WHERE r.setor = 'MG_SUL' AND r.cod_linha = 'SNC'
  AND r.posicao_ranking <= 90
  AND r.ciclo_referencia = '202507'
  AND RANDOM() > 0.3
ON CONFLICT DO NOTHING;
