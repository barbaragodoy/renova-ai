-- =============================================================
-- tb_perfil_portal — Sprint 6 (limite de painel por propagandista)
-- Equivalente local (Postgres) da tabela real já usada em produção
-- (AcheInfo_Apps/APP_RENOVAI/backend/app/auth/perfil.py, branch
-- merge/portal-agente-e-recomendacoes do George) para NOME_EXIBICAO/
-- FOTO_PATH — aqui criada do zero porque o Postgres local nunca teve
-- nenhum equivalente dela (nem a base, nem as colunas de limite; ver
-- docs/context/decisions-log.md, investigação de 2026-08-23).
--
-- Este script cria só o necessário para consumir LIMITE_PAINEL na regra
-- de negócio de recomendações (Sprint 6) — colunas de nome de
-- exibição/foto (NOME_EXIBICAO, FOTO_PATH, etc., já usadas por
-- auth/perfil.py) ficam fora de escopo aqui, não fazem parte desta
-- tarefa.
--
-- Padrão de consumo (confirmado pelo Hugo, validado com dado real no
-- Databricks): LEFT JOIN tb_perfil_portal ON REP_MATRICULA, com
-- COALESCE(LIMITE_PAINEL, 318). O 318 vive só como literal SQL — não
-- existe settings.limite_painel_padrao em config.py, por decisão
-- explícita desta task.
-- =============================================================

CREATE TABLE IF NOT EXISTS tb_perfil_portal (
    rep_email             VARCHAR(120) NOT NULL,
    rep_matricula          VARCHAR(20)  NOT NULL,
    limite_painel           INTEGER,
    limite_alterado_por     VARCHAR(20),
    limite_dt_alteracao     TIMESTAMP,

    CONSTRAINT pk_perfil_portal PRIMARY KEY (rep_email),
    CONSTRAINT fk_perfil_portal_propagandista FOREIGN KEY (rep_matricula)
        REFERENCES tb_propagandistas (rep_matricula)
);

COMMENT ON TABLE  tb_perfil_portal                     IS 'Perfil do propagandista no portal — hoje só o limite personalizado do painel (Sprint 6). Chaveada por e-mail (minúsculo), como no schema real.';
COMMENT ON COLUMN tb_perfil_portal.rep_email           IS 'E-mail corporativo, sempre gravado em minúsculas (mesmo padrão de LOWER(rep_email) já usado em auth/context.py).';
COMMENT ON COLUMN tb_perfil_portal.rep_matricula       IS 'Matrícula do propagandista, para join direto com tb_recomendacoes_painel sem precisar resolver e-mail de novo.';
COMMENT ON COLUMN tb_perfil_portal.limite_painel       IS 'Limite personalizado do painel. NULL = sem personalização, quem consome aplica COALESCE(limite_painel, 318) — o mesmo COALESCE que o notebook de geração usa na fonte real.';
COMMENT ON COLUMN tb_perfil_portal.limite_alterado_por IS 'Matrícula de quem alterou o limite pela última vez (auditoria).';
COMMENT ON COLUMN tb_perfil_portal.limite_dt_alteracao IS 'Timestamp da última alteração do limite (auditoria).';

CREATE INDEX IF NOT EXISTS idx_perfil_portal_matricula ON tb_perfil_portal (rep_matricula);


-- =============================================================
-- Cenários de teste — usam REP_MATRICULA já existentes em
-- 02_populate_propagandistas.sql (REP001..REP010).
-- =============================================================

INSERT INTO tb_perfil_portal (rep_email, rep_matricula, limite_painel, limite_alterado_por, limite_dt_alteracao) VALUES
    -- REP001 (ana.lima@ache.com.br): limite customizado ABAIXO do padrão —
    -- painel menor, guarda de revisão dispara com painel menor que 318 já
    -- teria disparado com 318.
    ('ana.lima@ache.com.br',    'REP001', 250, 'REP001', '2026-08-01 09:00:00'),

    -- REP002 (bruno.melo@ache.com.br): limite customizado ACIMA de 400 —
    -- cobre o cenário em que um painel que violaria o corte antigo fixo
    -- (400) passa a ser aceito com o limite novo por propagandista.
    ('bruno.melo@ache.com.br',  'REP002', 450, 'REP002', '2026-08-05 14:30:00'),

    -- REP003 (carla.souza@ache.com.br): limite explicitamente NULL —
    -- sem personalização, cai no default 318 via COALESCE.
    ('carla.souza@ache.com.br', 'REP003', NULL, NULL, NULL)
ON CONFLICT (rep_email) DO NOTHING;

-- REP004..REP010 propositalmente SEM linha em tb_perfil_portal — cobre o
-- cenário mais comum na fonte real hoje (ninguém personalizou ainda): o
-- LEFT JOIN não casa, e quem consome cai no mesmo default 318 via
-- COALESCE(limite_painel, 318), igual ao caso de limite explicitamente NULL.
