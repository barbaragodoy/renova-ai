-- =============================================================
-- tb_perfil_portal — schema unificado (Sprint 6 + sincronização com
-- merge/portal-agente-e-recomendacoes do George, 26/08/2026).
--
-- Duas necessidades convergem nesta tabela, e este script passa a
-- cobrir as duas juntas:
--
-- 1. Sprint 6 (limite de painel por propagandista) — colunas
--    rep_email, rep_matricula, limite_painel, limite_alterado_por,
--    limite_dt_alteracao. Já existiam neste script antes desta
--    revisão, e já estavam aplicadas no Postgres local rodando
--    (3 linhas de seed) — as instruções abaixo são idempotentes de
--    propósito para não perder esse dado.
--
-- 2. `backend/app/auth/perfil.py` (nome de exibição editável, já
--    commitado localmente antes desta tarefa) e `backend/app/auth/
--    foto.py` (novo, trazido nesta sincronização) esperam a MESMA
--    tabela com nome_exibicao, nome_origem_na_edicao, foto_path,
--    dt_acesso_anterior, dt_acesso_atual, dt_atualizacao — que este
--    script nunca tinha criado. Sem essas colunas, GET/PUT
--    /auth/perfil e PUT/GET/DELETE /auth/perfil/foto quebravam contra
--    Postgres local (tabela existia, mas incompleta).
--
-- Schema real confirmado: a tabela real (`acheinfo_dev.renovai.
-- tb_perfil_portal`) tem as duas famílias de coluna juntas, mesma
-- tabela — não são dois objetos.
-- =============================================================

CREATE TABLE IF NOT EXISTS tb_perfil_portal (
    rep_email             VARCHAR(120) NOT NULL,
    rep_matricula         VARCHAR(20)  NOT NULL,

    -- Nome de exibição e foto (auth/perfil.py, auth/foto.py)
    nome_exibicao           VARCHAR(60),
    nome_origem_na_edicao    VARCHAR(120),
    foto_path                VARCHAR(300),
    dt_acesso_anterior        TIMESTAMP,
    dt_acesso_atual            TIMESTAMP,
    dt_atualizacao              TIMESTAMP,

    -- Limite de painel (Sprint 6)
    limite_painel           INTEGER,
    limite_alterado_por     VARCHAR(20),
    limite_dt_alteracao     TIMESTAMP,

    CONSTRAINT pk_perfil_portal PRIMARY KEY (rep_email),
    CONSTRAINT fk_perfil_portal_propagandista FOREIGN KEY (rep_matricula)
        REFERENCES tb_propagandistas (rep_matricula)
);

-- Idempotente para a tabela que já está rodando (5 colunas, 3 linhas de
-- seed) ganhar as 6 colunas novas sem perder dado. Em uma base nova, o
-- CREATE TABLE acima já cria tudo e estes ALTER viram no-op.
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS nome_exibicao        VARCHAR(60);
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS nome_origem_na_edicao VARCHAR(120);
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS foto_path             VARCHAR(300);
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS dt_acesso_anterior    TIMESTAMP;
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS dt_acesso_atual       TIMESTAMP;
ALTER TABLE tb_perfil_portal ADD COLUMN IF NOT EXISTS dt_atualizacao        TIMESTAMP;

COMMENT ON TABLE  tb_perfil_portal                       IS 'Perfil do propagandista no portal — nome de exibição, foto, últimos acessos e limite personalizado do painel. Chaveada por e-mail (minúsculo), como no schema real.';
COMMENT ON COLUMN tb_perfil_portal.rep_email             IS 'E-mail corporativo, sempre gravado em minúsculas (mesmo padrão de LOWER(rep_email) já usado em auth/context.py).';
COMMENT ON COLUMN tb_perfil_portal.rep_matricula         IS 'Matrícula do propagandista, para join direto com tabelas de recomendação sem precisar resolver e-mail de novo.';
COMMENT ON COLUMN tb_perfil_portal.nome_exibicao         IS 'Nome editado pela pessoa na aba Usuário. NULL = nunca editou, tela cai no nome de guerra da SIMV.';
COMMENT ON COLUMN tb_perfil_portal.nome_origem_na_edicao IS 'O que REP_NOME dizia no momento da edição do nome — permite detectar depois que o cadastro oficial mudou.';
COMMENT ON COLUMN tb_perfil_portal.foto_path             IS 'Caminho da foto no volume (Databricks) — sempre NULL no Postgres local, já que não há Unity Catalog Volume equivalente aqui (ver limitação de fidelidade documentada na sincronização de 26/08/2026).';
COMMENT ON COLUMN tb_perfil_portal.dt_acesso_anterior    IS 'Penúltimo login, exibido na aba Usuário. NULL no primeiro acesso.';
COMMENT ON COLUMN tb_perfil_portal.dt_acesso_atual       IS 'Login em curso — nunca exibido diretamente, só usado para calcular o próximo dt_acesso_anterior.';
COMMENT ON COLUMN tb_perfil_portal.dt_atualizacao        IS 'Timestamp da última gravação de nome_exibicao/foto_path (MERGE de auth/perfil.py e auth/foto.py).';
COMMENT ON COLUMN tb_perfil_portal.limite_painel         IS 'Limite personalizado do painel. NULL = sem personalização, quem consome aplica COALESCE(limite_painel, LIMITE_PAINEL_PADRAO) — ver tb_renovai_parametros (Fase 3.5).';
COMMENT ON COLUMN tb_perfil_portal.limite_alterado_por   IS 'Matrícula de quem alterou o limite pela última vez (auditoria).';
COMMENT ON COLUMN tb_perfil_portal.limite_dt_alteracao   IS 'Timestamp da última alteração do limite (auditoria).';

CREATE INDEX IF NOT EXISTS idx_perfil_portal_matricula ON tb_perfil_portal (rep_matricula);


-- =============================================================
-- Cenários de teste — usam REP_MATRICULA já existentes em
-- 02_populate_propagandistas.sql (REP001..REP010). Mantém exatamente
-- os 3 cenários de limite de painel já existentes (idempotente via
-- ON CONFLICT DO NOTHING — não duplica nem sobrescreve o que já roda).
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
    -- sem personalização, cai no default via COALESCE.
    ('carla.souza@ache.com.br', 'REP003', NULL, NULL, NULL)
ON CONFLICT (rep_email) DO NOTHING;

-- REP004..REP010 propositalmente SEM linha em tb_perfil_portal — cobre o
-- cenário mais comum na fonte real hoje (ninguém personalizou nada ainda):
-- o LEFT JOIN não casa, e quem consome cai no default via COALESCE.

-- =============================================================
-- Cenário extra para a aba Usuário: REP001 com nome editado, para
-- exercitar nome_editado=true / "voltar ao nome original" sem precisar
-- de uma chamada PUT manual. Não conflita com o cenário de limite
-- acima (mesma linha, colunas diferentes) — usa UPDATE, não INSERT
-- duplicado, para não colidir com o ON CONFLICT DO NOTHING de cima.
-- =============================================================
UPDATE tb_perfil_portal
   SET nome_exibicao = 'Ana P. Lima',
       nome_origem_na_edicao = 'ANA LIMA',
       dt_atualizacao = '2026-08-10 08:00:00'
 WHERE rep_email = 'ana.lima@ache.com.br'
   AND nome_exibicao IS NULL;
