-- =============================================================
-- Hierarquia GD — 1 GD por setor, vinculado aos reps do setor
-- GD01 → SP_INTERIOR (REP001, REP002, REP003)
-- GD02 → RJ_CAPITAL  (REP004, REP005, REP006)
-- GD03 → MG_SUL      (REP007, REP008, REP009, REP010)
-- =============================================================

INSERT INTO tb_hierarquia_gd (gd_matricula, gd_email, gd_nome, rep_matricula, setor) VALUES
  ('GD001', 'marcos.vieira@ache.com.br',  'Marcos Vieira',  'REP001', 'SP_INTERIOR'),
  ('GD001', 'marcos.vieira@ache.com.br',  'Marcos Vieira',  'REP002', 'SP_INTERIOR'),
  ('GD001', 'marcos.vieira@ache.com.br',  'Marcos Vieira',  'REP003', 'SP_INTERIOR'),
  ('GD002', 'patricia.leal@ache.com.br',  'Patricia Leal',  'REP004', 'RJ_CAPITAL'),
  ('GD002', 'patricia.leal@ache.com.br',  'Patricia Leal',  'REP005', 'RJ_CAPITAL'),
  ('GD002', 'patricia.leal@ache.com.br',  'Patricia Leal',  'REP006', 'RJ_CAPITAL'),
  ('GD003', 'roberto.pinto@ache.com.br',  'Roberto Pinto',  'REP007', 'MG_SUL'),
  ('GD003', 'roberto.pinto@ache.com.br',  'Roberto Pinto',  'REP008', 'MG_SUL'),
  ('GD003', 'roberto.pinto@ache.com.br',  'Roberto Pinto',  'REP009', 'MG_SUL'),
  ('GD003', 'roberto.pinto@ache.com.br',  'Roberto Pinto',  'REP010', 'MG_SUL')
ON CONFLICT DO NOTHING;
