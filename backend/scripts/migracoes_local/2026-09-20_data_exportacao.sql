-- Postgres local (DATA_SOURCE=local). Idempotente: pode rodar mais de uma vez.
--
-- O Historico passou a ler `data_exportacao` em 20/09/2026, para saber se um
-- aceite ja foi enviado ao SalesFarma e, portanto, se ainda pode ser desfeito.
-- No Databricks a coluna existe desde 08/09/2026 (DATA_EXPORTACAO em
-- acheinfo_dev.renovai.tb_recomendacoes_painel_historico). Sem ela, o
-- GET /recomendacoes/desconsideradas falha na fonte local.
--
-- Uso:
--   docker exec -i renovai-postgres psql -U renovai -d renovai \
--     < backend/scripts/migracoes_local/2026-09-20_data_exportacao.sql

ALTER TABLE tb_recomendacoes_painel
    ADD COLUMN IF NOT EXISTS data_exportacao timestamptz;
