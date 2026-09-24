-- Descrição de OPV somente no recorte N; campo não usado na extração.
SELECT OPV, COUNT(*) AS visitas
FROM dmn_produtividade_dev.pfv_tb.propagandistas_visitacao_medica
WHERE VISITA_EFETIVA = 'N'
  AND DATA_VISITA >= DATE '2026-01-01'
  AND DATA_VISITA < DATE '2027-01-01'
  AND upper(trim(COMENTARIOS)) <> 'PROFISSIONAIS NÃO VISITADOS ATÉ O FECHAMENTO'
GROUP BY OPV
ORDER BY visitas DESC;
