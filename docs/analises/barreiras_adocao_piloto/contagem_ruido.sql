-- Passada S somente. Executada em 18/09/2026: 9.940 visitas, 85 ocorrências.
-- Esta é uma contagem conservadora dos padrões literais observados, não uma
-- revisão semântica exaustiva de todos os comentários.
WITH a AS (
  SELECT upper(trim(regexp_replace(regexp_replace(COMENTARIOS, '[[:punct:]]+', ' '), ' +', ' '))) AS t
  FROM dmn_produtividade_dev.pfv_tb.propagandistas_visitacao_medica
  WHERE VISITA_EFETIVA = 'S'
    AND CICLO IN ('202607', '202608')
    AND pmod(xxhash64(ID), 100000) < 800
)
SELECT COUNT(*) AS visitas,
       SUM(CASE WHEN t IN (
         '', 'RELEMBREI', 'RELEMBREI MARCAS', 'VISITA REMOTA', 'VISITA REMOTO',
         'SEM COMENTÁRIOS', 'SEM COMENTARIOS', 'NÃO FEZ COMENTÁRIOS',
         'NAO FEZ COMENTARIOS', 'FOCO PRODUTO ALVO', 'REFORÇO DE MARCAS',
         'REFORCO DE MARCAS', 'REFORÇO MARCAS', 'REFORCO MARCAS',
         'PEÇA PROMOCIONAL', 'PECA PROMOCIONAL', 'VISITA EXPOSITIVA',
         'RECALL DAS MARCAS', 'REUNIÃO MÉDICA', 'REUNIAO MEDICA',
         'ENTREGA DE MATERIAL SOLICITADO', 'VISITA RESTRITA',
         'FALEI DE NOSSA LINHA', 'FALEI DE TODA A LINHA', 'FOCO NOVAMOX',
         'FOCO NAUTEX E PROVANCE', 'TRABALHADO PACIENTE COM TDM',
         'REFORÇO DAS MARCAS PRESCRITAS', 'REFORCO DAS MARCAS PRESCRITAS',
         'EDISTRIDE E TREZOR', 'ANALGESIA TORMIV ODG', 'AQUARELA AXONIUM',
         'EXODUS E TOLREST', 'OPT COM TD GRADE', 'FOCO AUDIT',
         'FOCO ANTIBIÓTICOS', 'FOCO ANTIBIOTICOS', 'FOCO EM NAUTEX',
         'FOCO BUSONID', 'FOCO ATBS NO CPV', 'REUNIÃO NO SERVIÇO',
         'REUNIAO NO SERVICO', 'REUNIÃO FUNDAÇÃO IDEIA FERTIL'
       ) THEN 1 ELSE 0 END) AS sem_conteudo_regras
FROM a;
