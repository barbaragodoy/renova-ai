-- =============================================================
-- Propagandistas fictícios — 10 reps, 3 setores, 2 linhas
-- Setores: SP_INTERIOR, RJ_CAPITAL, MG_SUL
-- Linhas:  CARDIO, SNC
-- =============================================================

INSERT INTO tb_propagandistas (rep_matricula, rep_email, setor, cod_linha, rep_nome, ativo) VALUES
  ('REP001', 'ana.lima@ache.com.br',        'SP_INTERIOR', 'CARDIO', 'Ana Lima',        TRUE),
  ('REP002', 'bruno.melo@ache.com.br',      'SP_INTERIOR', 'SNC',    'Bruno Melo',      TRUE),
  ('REP003', 'carla.souza@ache.com.br',     'SP_INTERIOR', 'CARDIO', 'Carla Souza',     TRUE),
  ('REP004', 'diego.costa@ache.com.br',     'RJ_CAPITAL',  'CARDIO', 'Diego Costa',     TRUE),
  ('REP005', 'elaine.ferreira@ache.com.br', 'RJ_CAPITAL',  'SNC',    'Elaine Ferreira', TRUE),
  ('REP006', 'fabio.nunes@ache.com.br',     'RJ_CAPITAL',  'CARDIO', 'Fabio Nunes',     TRUE),
  ('REP007', 'gisele.rocha@ache.com.br',    'MG_SUL',      'SNC',    'Gisele Rocha',    TRUE),
  ('REP008', 'henrique.dias@ache.com.br',   'MG_SUL',      'CARDIO', 'Henrique Dias',   TRUE),
  ('REP009', 'igor.martins@ache.com.br',    'MG_SUL',      'SNC',    'Igor Martins',    TRUE),
  ('REP010', 'juliana.alves@ache.com.br',   'MG_SUL',      'CARDIO', 'Juliana Alves',   FALSE)
ON CONFLICT (rep_matricula) DO NOTHING;
