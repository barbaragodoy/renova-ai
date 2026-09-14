-- =============================================================
-- Paridade local: aceite de recomendação e Memória de Visitas
-- Idempotente para bancos criados antes das entregas de 04/09/2026.
-- =============================================================

ALTER TABLE tb_recomendacoes_painel
    ADD COLUMN IF NOT EXISTS aceito_por VARCHAR(20),
    ADD COLUMN IF NOT EXISTS data_aceite TIMESTAMPTZ;

-- O CHECK original foi criado sem nome explícito. Removemos qualquer CHECK
-- que governe status_recomendacao antes de instalar o domínio atual.
DO $$
DECLARE
    restricao RECORD;
BEGIN
    FOR restricao IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'tb_recomendacoes_painel'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%status_recomendacao%'
    LOOP
        EXECUTE format(
            'ALTER TABLE tb_recomendacoes_painel DROP CONSTRAINT %I',
            restricao.conname
        );
    END LOOP;
END $$;

ALTER TABLE tb_recomendacoes_painel
    ADD CONSTRAINT ck_recomendacoes_status
    CHECK (status_recomendacao IN (
        'PENDENTE', 'DESCONSIDERADA', 'APLICADA', 'EXPIRADA', 'ACEITA', 'INELEGIVEL'
    ));

COMMENT ON COLUMN tb_recomendacoes_painel.aceito_por IS 'Matrícula de quem declarou intenção de cumprir a recomendação.';
COMMENT ON COLUMN tb_recomendacoes_painel.data_aceite IS 'Timestamp do aceite, gerado pelo backend no momento da gravação.';

ALTER TABLE tb_visitacao_medica
    ADD COLUMN IF NOT EXISTS visita_tipo VARCHAR(40),
    ADD COLUMN IF NOT EXISTS comentarios TEXT;

COMMENT ON COLUMN tb_visitacao_medica.visita_tipo IS 'Modalidade registrada para a visita.';
COMMENT ON COLUMN tb_visitacao_medica.comentarios IS 'Observações de campo usadas pela Memória de Visitas.';

CREATE OR REPLACE VIEW vw_visitacao_comentarios AS
SELECT setor, ufcrm, data_visita, visita_tipo, comentarios
FROM tb_visitacao_medica
WHERE visita_efetiva = TRUE;

COMMENT ON VIEW vw_visitacao_comentarios IS 'Visitas efetivas com comentários para a Memória de Visitas; equivalente local da view governada no Databricks.';
