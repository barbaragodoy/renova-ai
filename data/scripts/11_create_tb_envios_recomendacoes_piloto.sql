-- =============================================================
-- tb_envios_recomendacoes_piloto
-- Histórico de envio de recomendações aos propagandistas durante o
-- piloto (Sprint 5) — permite comparar WhatsApp, E-mail e Controle.
--
-- Tabela nova, sem dependência de correção externa (diferente de
-- tb_recomendacoes_painel*): propriedade e criação da própria Bárbara,
-- não do Hugo. Ainda não existe equivalente no Databricks real — será
-- criada lá em sessão separada (ver docs/context/databricks-schema-real.md).
--
-- Grão: uma linha por combinação (envio, recomendação). Um envio agrupa
-- várias recomendações mandadas juntas ao mesmo propagandista, no mesmo
-- canal, no mesmo momento — todas compartilham ID_ENVIO.
--
-- Decisão de design: o grupo CONTROLE também gera registro de envio, com
-- CANAL_ENVIO = 'NENHUM' — representa "recomendação estava disponível
-- para este propagandista, sem push ativo". Garante que esta tabela,
-- sozinha, permita comparar timing entre os três grupos sem depender de
-- outra fonte.
-- =============================================================

CREATE TABLE IF NOT EXISTS tb_envios_recomendacoes_piloto (
    id_envio             UUID         NOT NULL,  -- agrupa recomendações do mesmo disparo
    -- FK lógica (não enforced) para tb_recomendacoes_painel/tb_recomendacoes_painel_historico.
    -- Sem FK física: tipo UUID aqui reflete o schema local; no Databricks real
    -- (STRING) a mesma coluna não teria FK de catálogo cruzado de qualquer forma.
    id_recomendacao      UUID         NOT NULL,
    rep_matricula        VARCHAR(20)  NOT NULL,
    grupo_piloto         VARCHAR(20)  NOT NULL
        CHECK (grupo_piloto IN ('WHATSAPP', 'EMAIL', 'CONTROLE')),
    canal_envio          VARCHAR(20)  NOT NULL
        CHECK (canal_envio IN ('WHATSAPP', 'EMAIL', 'NENHUM')),
    data_hora_envio       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),  -- gerado pelo backend, nunca aceito do chamador
    ciclo_recomendacao    CHAR(6),     -- denormalizado, evita join com tb_recomendacoes_painel*
    tipo_recomendacao      VARCHAR(20), -- denormalizado (ENTRADA_PAINEL/REVISAO_PAINEL)

    CONSTRAINT pk_envios_recomendacoes_piloto PRIMARY KEY (id_envio, id_recomendacao),
    CONSTRAINT fk_envios_propagandista FOREIGN KEY (rep_matricula)
        REFERENCES tb_propagandistas (rep_matricula)
);

COMMENT ON TABLE  tb_envios_recomendacoes_piloto                    IS 'Histórico de envio de recomendações aos propagandistas durante o piloto (WhatsApp/E-mail/Controle) — Sprint 5.';
COMMENT ON COLUMN tb_envios_recomendacoes_piloto.id_envio           IS 'Agrupa todas as recomendações mandadas juntas no mesmo disparo.';
COMMENT ON COLUMN tb_envios_recomendacoes_piloto.id_recomendacao    IS 'FK lógica (não enforced) para tb_recomendacoes_painel/tb_recomendacoes_painel_historico.';
COMMENT ON COLUMN tb_envios_recomendacoes_piloto.grupo_piloto       IS 'Grupo do piloto do propagandista no momento do envio: WHATSAPP | EMAIL | CONTROLE.';
COMMENT ON COLUMN tb_envios_recomendacoes_piloto.canal_envio        IS 'Canal efetivamente usado: WHATSAPP | EMAIL | NENHUM (CONTROLE sempre gera NENHUM).';
COMMENT ON COLUMN tb_envios_recomendacoes_piloto.data_hora_envio    IS 'Timestamp do envio, gerado pelo backend no momento do registro — nunca aceito do chamador.';
COMMENT ON COLUMN tb_envios_recomendacoes_piloto.ciclo_recomendacao IS 'Ciclo da recomendação enviada, denormalizado para evitar join em análises.';
COMMENT ON COLUMN tb_envios_recomendacoes_piloto.tipo_recomendacao  IS 'Tipo da recomendação enviada (ENTRADA_PAINEL/REVISAO_PAINEL), denormalizado.';

-- Consultas de análise do piloto: histórico por rep ao longo do tempo, e
-- recuperação de todas as recomendações de um mesmo disparo.
CREATE INDEX IF NOT EXISTS idx_envios_rep_data ON tb_envios_recomendacoes_piloto (rep_matricula, data_hora_envio);
CREATE INDEX IF NOT EXISTS idx_envios_id_envio ON tb_envios_recomendacoes_piloto (id_envio);
