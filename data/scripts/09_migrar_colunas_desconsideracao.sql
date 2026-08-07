-- =============================================================
-- Migração: colunas de desconsideração (task 161830/163626)
-- Renomeia as colunas antigas do endpoint descontinuado
-- (POST /recomendacoes/desconsiderar, ID no corpo) para os nomes da
-- especificação 161830, e adiciona as colunas novas. Idempotente: pode
-- ser rodado tanto contra um banco criado antes desta mudança (colunas
-- antigas) quanto contra um banco criado do zero com 01_create_tables.sql
-- já atualizado (colunas novas, nada a renomear).
-- =============================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tb_recomendacoes_painel' AND column_name = 'timestamp_desconsideracao'
    ) THEN
        ALTER TABLE tb_recomendacoes_painel RENAME COLUMN timestamp_desconsideracao TO data_desconsideracao;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tb_recomendacoes_painel' AND column_name = 'rep_matricula_desconsiderou'
    ) THEN
        ALTER TABLE tb_recomendacoes_painel RENAME COLUMN rep_matricula_desconsiderou TO desconsiderado_por;
    END IF;
END $$;

ALTER TABLE tb_recomendacoes_painel
    ADD COLUMN IF NOT EXISTS qtd_vezes_desconsiderado     INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS bloquear_novas_recomendacoes BOOLEAN;

COMMENT ON COLUMN tb_recomendacoes_painel.motivo_desconsideracao IS 'Motivo da desconsideração (lista fixa) ou "OUTROS: <texto informado>" — task 161830.';
COMMENT ON COLUMN tb_recomendacoes_painel.desconsiderado_por IS 'Matrícula de quem desconsiderou (pode ser o próprio rep ou o GD).';
COMMENT ON COLUMN tb_recomendacoes_painel.data_desconsideracao IS 'Timestamp da desconsideração, gerado pelo backend no momento da gravação.';
COMMENT ON COLUMN tb_recomendacoes_painel.qtd_vezes_desconsiderado IS 'Quantas vezes esta combinação já foi desconsiderada ao longo do histórico.';
COMMENT ON COLUMN tb_recomendacoes_painel.bloquear_novas_recomendacoes IS 'NULL = sem decisão. TRUE = não recomendar mais este médico a este rep; FALSE = pode voltar a ser recomendado em ciclo futuro se elegível.';
