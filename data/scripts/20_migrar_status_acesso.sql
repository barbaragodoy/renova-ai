-- =============================================================
-- tb_perfil_portal — bloqueio de acesso por STATUS_ACESSO/PERFIL_ACESSO
-- (task de Bárbara, confirmada carregada na fonte real desde 21/09/2026:
-- 2.146 propagandistas — 60 ATIVO, 2.086 BLOQUEADO — mais 13
-- administradores).
--
-- Quatro colunas novas, mesmo nome em minúsculo já usado no resto do
-- schema local:
--   status_acesso        — 'ATIVO' | 'BLOQUEADO'
--   acesso_liberado_em    — quando a liberação aconteceu
--   acesso_liberado_por   — quem liberou (auditoria)
--   perfil_acesso         — 'PROPAGANDISTA' | 'ADMINISTRADOR'
--
-- Administradores reais NÃO têm propagandista vinculado (REP_MATRICULA
-- nulo na fonte real, confirmado por consulta direta em 2026-09-23) — a
-- constraint local de rep_matricula NOT NULL + FK obrigatória nunca
-- prosupunha isso, porque nasceu antes desta tabela precisar representar
-- administradores. rep_matricula vira opcional; a FK continua válida (não
-- se aplica a NULL em Postgres), só deixa de ser obrigatória.
-- =============================================================

ALTER TABLE tb_perfil_portal ALTER COLUMN rep_matricula DROP NOT NULL;

-- tb_propagandistas local não tinha rep_login — sem ela, o caminho
-- AUTH_MODE=entra_id (que resolve identidade por REP_LOGIN, não REP_EMAIL)
-- não roda contra Postgres local, nem para testar. Fonte real confirmada em
-- 2026-09-15 (Task 170097): 2.154 propagandistas com REP_LOGIN preenchido e
-- único. Sintético aqui de propósito diferente do prefixo do e-mail, para o
-- teste provar que o caminho entra_id usa REP_LOGIN de verdade e não
-- coincide por acidente com o e-mail.
ALTER TABLE tb_propagandistas ADD COLUMN IF NOT EXISTS rep_login VARCHAR(60);

UPDATE tb_propagandistas SET rep_login = 'ana.lima.upn'    WHERE rep_matricula = 'REP001' AND rep_login IS NULL;
UPDATE tb_propagandistas SET rep_login = 'bruno.melo.upn'  WHERE rep_matricula = 'REP002' AND rep_login IS NULL;
UPDATE tb_propagandistas SET rep_login = 'carla.souza.upn' WHERE rep_matricula = 'REP003' AND rep_login IS NULL;
UPDATE tb_propagandistas SET rep_login = 'diego.costa.upn' WHERE rep_matricula = 'REP004' AND rep_login IS NULL;

ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS status_acesso       VARCHAR(20);
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS acesso_liberado_em  TIMESTAMP;
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS acesso_liberado_por VARCHAR(120);
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS perfil_acesso       VARCHAR(20);

COMMENT ON COLUMN tb_perfil_portal.status_acesso       IS 'ATIVO libera o login (senha ou entra_id); BLOQUEADO ou NULL (sem linha) nega com 403 ACESSO_BLOQUEADO. Deny-by-default: ausência de linha é tratada como bloqueado, nunca como liberado.';
COMMENT ON COLUMN tb_perfil_portal.acesso_liberado_em  IS 'Quando o status virou ATIVO pela última vez. Auditoria, não usado em lógica de negócio.';
COMMENT ON COLUMN tb_perfil_portal.acesso_liberado_por IS 'Quem liberou o acesso (auditoria).';
COMMENT ON COLUMN tb_perfil_portal.perfil_acesso        IS 'PROPAGANDISTA ou ADMINISTRADOR. Administrador pode não ter rep_matricula (sem vínculo com tb_propagandistas) — ver auth/administrativo.py.';

-- =============================================================
-- Cenários de teste — cobrem os 4 casos (sem linha, BLOQUEADO, ATIVO,
-- ATIVO+admin) tanto para propagandista quanto para administrador
-- fictício, para os dois modos de autenticação (senha usa rep_email,
-- entra_id usa rep_login → resolvido via tb_propagandistas antes de
-- chegar aqui; tb_perfil_portal.rep_email guarda sempre o e-mail
-- corporativo real do propagandista, nunca o rep_login).
--
-- Propagandistas usados (já existem em 02_populate_propagandistas.sql):
--   REP001 (ana.lima@ache.com.br)    -> ATIVO
--   REP002 (bruno.melo@ache.com.br)  -> BLOQUEADO
--   REP004                            -> sem linha nenhuma (já é o caso
--                                        hoje, não precisa de INSERT)
--
-- Administradores fictícios (sem rep_matricula, sem vínculo com
-- tb_propagandistas — mesmo padrão dos administradores reais):
--   admin.bloqueado.teste@ache.com.br -> BLOQUEADO, ADMINISTRADOR
--   admin.ativo.teste@ache.com.br     -> ATIVO, ADMINISTRADOR
--   (admin.semlinha.teste@ache.com.br não entra: "sem linha" é
--    ausência de INSERT, não precisa de cenário explícito)
-- =============================================================

UPDATE tb_perfil_portal
   SET status_acesso = 'ATIVO',
       perfil_acesso = 'PROPAGANDISTA',
       acesso_liberado_em = '2026-09-21 08:00:00',
       acesso_liberado_por = 'george.fernandes@ache.com.br'
 WHERE rep_email = 'ana.lima@ache.com.br';

INSERT INTO tb_perfil_portal (rep_email, rep_matricula, status_acesso, perfil_acesso, acesso_liberado_em, acesso_liberado_por)
VALUES ('bruno.melo@ache.com.br', 'REP002', 'BLOQUEADO', 'PROPAGANDISTA', NULL, NULL)
ON CONFLICT (rep_email) DO UPDATE
   SET status_acesso = 'BLOQUEADO',
       perfil_acesso = 'PROPAGANDISTA';

INSERT INTO tb_perfil_portal (rep_email, rep_matricula, status_acesso, perfil_acesso, acesso_liberado_em, acesso_liberado_por)
VALUES
    ('admin.bloqueado.teste@ache.com.br', NULL, 'BLOQUEADO', 'ADMINISTRADOR', NULL, NULL),
    ('admin.ativo.teste@ache.com.br',     NULL, 'ATIVO',     'ADMINISTRADOR', '2026-09-21 08:00:00', 'george.fernandes@ache.com.br')
ON CONFLICT (rep_email) DO UPDATE
   SET status_acesso = EXCLUDED.status_acesso,
       perfil_acesso = EXCLUDED.perfil_acesso;
