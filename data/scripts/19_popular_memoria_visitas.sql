-- =============================================================
-- Massa local para a Memória de Visitas
-- Preenche observações somente onde o simulador antigo deixou NULL.
-- =============================================================

WITH visitas AS (
    SELECT setor, ufcrm, data_visita,
           ROW_NUMBER() OVER (
               PARTITION BY setor, ufcrm ORDER BY data_visita DESC
           ) AS ordem
    FROM tb_visitacao_medica
    WHERE visita_efetiva = TRUE
)
UPDATE tb_visitacao_medica AS v
SET visita_tipo = COALESCE(v.visita_tipo, 'PRESENCIAL'),
    comentarios = CASE visitas.ordem
        WHEN 1 THEN 'Médico pediu material de apoio e combinou revisar a proposta na próxima visita.'
        WHEN 2 THEN 'Relatou boa experiência recente e solicitou acompanhamento dos resultados.'
        ELSE 'Visita de acompanhamento do relacionamento e atualização do perfil.'
    END
FROM visitas
WHERE v.setor = visitas.setor
  AND v.ufcrm = visitas.ufcrm
  AND v.data_visita = visitas.data_visita
  AND visitas.ordem <= 3
  AND v.comentarios IS NULL;
