-- =============================================================
-- Tabelas físicas para Chat / Ranking / Agente (sincronização com
-- merge/portal-agente-e-recomendacoes do George).
--
-- Schema real confirmado em 26/08/2026 via DESCRIBE EXTENDED contra
-- acheinfo_dev.renovai (DATA_SOURCE=databricks). Nomes de coluna aqui
-- em minúsculas por convenção deste projeto (Postgres/Databricks são
-- case-insensitive para identificador não citado, então o código que
-- referencia SETOR/Setor/setor casa igual dos dois lados).
--
-- Desvio de tipo, achado em teste de fumaça real (26/08/2026): as colunas
-- *_PCT/*_PCT_ACHE de tb_perfil_medico_setor são `double` na fonte real,
-- mas chat/perfil_medico.py aplica ROUND(coluna, 1) nelas — Postgres não
-- tem ROUND(double precision, integer), só ROUND(numeric, integer)
-- (Databricks/Spark SQL aceita os dois). Declaradas aqui como NUMERIC(5,2)
-- em vez de DOUBLE PRECISION para a query de George rodar sem alteração;
-- é desvio de fidelidade da réplica local, não do código.
--
-- Duas tabelas desta lista (vw_gold_auditpharma, vw_agente_produtos)
-- têm nome de "vw_" mas são criadas como TABELA física aqui, de
-- propósito: a origem real é uma VIEW sobre catálogo externo que o
-- projeto não tem acesso (dmn_inteligencia_dados_prd), então a réplica
-- local vira um "banco de seed" simplificado, documentado inline em
-- cada bloco. O nome physical não muda porque o código novo (George)
-- consulta esses nomes direto, sem abstração de fonte — ver
-- docs/context/decisions-log.md, entrada de 26/08/2026.
-- =============================================================


-- =============================================================
-- tb_conduta_medico
-- "Como Trata" da gaveta do Ranking. Append-only: uma linha por
-- registro, nunca atualizada — o histórico é o próprio dado (mesma
-- semântica confirmada no comentário da tabela real). Grão de leitura
-- é "última linha por setor+ufcrm", resolvido na query, não aqui.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_conduta_medico (
    id_registro     VARCHAR(36)  NOT NULL,
    setor           VARCHAR(50)  NOT NULL,
    ufcrm           VARCHAR(20)  NOT NULL,
    texto           TEXT         NOT NULL,
    condicao        VARCHAR(200),
    origem_texto    VARCHAR(10)  NOT NULL,
    registrado_por  VARCHAR(20)  NOT NULL,
    registrado_em   TIMESTAMP    NOT NULL DEFAULT now(),
    versao_esquema  INTEGER      NOT NULL DEFAULT 1,

    CONSTRAINT pk_conduta_medico PRIMARY KEY (id_registro),
    CONSTRAINT ck_conduta_origem CHECK (origem_texto IN ('digitado', 'ditado'))
);

COMMENT ON TABLE tb_conduta_medico IS 'Registro de conduta do médico ("Como Trata"), append-only — nunca UPDATE, confirmado no comentário da tabela real. Espelho local de acheinfo_dev.renovai.tb_conduta_medico.';
COMMENT ON COLUMN tb_conduta_medico.condicao IS 'Condição tratada, quando o registro for estruturado. NULL enquanto o campo for texto livre (100% dos casos hoje na fonte real).';

CREATE INDEX IF NOT EXISTS idx_conduta_setor_ufcrm ON tb_conduta_medico (setor, ufcrm, registrado_em DESC);


-- =============================================================
-- tb_perfil_medico_setor
-- Retrato prescritivo do médico por SETOR+UFCRM. ~60 colunas na fonte
-- real — replicado quase por inteiro de propósito: mapeamento de uso
-- real em chat/perfil_medico.py confirma que a maior parte é lida (não
-- é excesso de fidelidade). Grão: 1 linha por SETOR+UFCRM (mesmo grão
-- de tb_ranking_medicos_validacao).
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_perfil_medico_setor (
    ciclo_referencia                CHAR(6)       NOT NULL,
    setor                           VARCHAR(50)   NOT NULL,
    linha_produto                   VARCHAR(10),
    ufcrm                           VARCHAR(20)   NOT NULL,
    nome_medico                     VARCHAR(150)  NOT NULL,
    posicao_ranking_setor           INTEGER,
    pontos                          NUMERIC(10,2),
    flag_no_painel                  INTEGER,
    qtd_medicos_painel_setor        BIGINT,
    recomendacao                    VARCHAR(50),
    motivo_recomendacao             VARCHAR(80),
    data_ultima_visita              DATE,
    meses_desde_ultima_visita       INTEGER,
    ciclos_no_painel_janela         BIGINT,

    -- Janela do ciclo corrente
    ciclo_top1_categoria            VARCHAR(100),
    ciclo_top1_pct                  NUMERIC(5,2),
    ciclo_top2_categoria            VARCHAR(100),
    ciclo_top2_pct                  NUMERIC(5,2),
    ciclo_top3_categoria            VARCHAR(100),
    ciclo_top3_pct                  NUMERIC(5,2),
    ciclo_top1_produto              VARCHAR(150),
    ciclo_top2_produto              VARCHAR(150),
    ciclo_top3_produto              VARCHAR(150),
    ciclo_qtd_categorias            BIGINT,
    ciclo_qtd_produtos              BIGINT,
    ciclo_rx_total                  DOUBLE PRECISION,
    ciclo_rx_ache                   DOUBLE PRECISION,
    ciclo_pct_ache                  NUMERIC(5,2),

    -- Janela do ano corrente (YTD)
    ytd_top1_categoria              VARCHAR(100),
    ytd_top1_pct                    NUMERIC(5,2),
    ytd_top2_categoria              VARCHAR(100),
    ytd_top3_categoria              VARCHAR(100),
    ytd_qtd_categorias               BIGINT,
    ytd_rx_total                    DOUBLE PRECISION,
    ytd_rx_ache                     DOUBLE PRECISION,
    ytd_pct_ache                    NUMERIC(5,2),

    -- Janela geral (histórico completo)
    geral_top1_categoria            VARCHAR(100),
    geral_top1_pct                  NUMERIC(5,2),
    geral_top2_categoria            VARCHAR(100),
    geral_top3_categoria            VARCHAR(100),
    geral_top1_produto              VARCHAR(150),
    geral_top2_produto              VARCHAR(150),
    geral_top3_produto              VARCHAR(150),
    geral_qtd_categorias            BIGINT,
    geral_qtd_produtos              BIGINT,
    geral_rx_total                  DOUBLE PRECISION,
    geral_rx_ache                   DOUBLE PRECISION,
    geral_pct_ache                  NUMERIC(5,2),

    -- Produto recomendado e critério de composição
    produto_recomendado_linha              VARCHAR(10),
    produto_recomendado_categoria          VARCHAR(100),
    categoria_esta_no_top3          INTEGER,
    ultimo_periodo_na_categoria     INTEGER,
    origem_da_recomendacao          VARCHAR(50),
    ja_prescreve_o_produto          INTEGER,
    prescreve_no_ciclo              INTEGER,
    prescreve_no_ano                INTEGER,
    rec_e_top1                      INTEGER,
    produto2_linha                  VARCHAR(10),
    produto2_categoria              VARCHAR(100),
    produto3_linha                  VARCHAR(10),
    produto3_categoria              VARCHAR(100),
    produto_recomendado_ache               VARCHAR(150),
    produto_recomendado_ache_linha         VARCHAR(10),
    produto_recomendado_ache_categoria     VARCHAR(100),
    periodo_prescricao_usado        INTEGER,
    dt_geracao                      DATE,

    CONSTRAINT pk_perfil_medico_setor PRIMARY KEY (setor, ufcrm)
);

COMMENT ON TABLE tb_perfil_medico_setor IS 'Retrato prescritivo do médico em cada território (SETOR+UFCRM). Espelho local de acheinfo_dev.renovai.tb_perfil_medico_setor — ~60 colunas replicadas por inteiro porque chat/perfil_medico.py lê a maior parte delas.';
COMMENT ON COLUMN tb_perfil_medico_setor.linha_produto IS 'Código numérico da linha ("1".."6"), mesmo domínio de FRANQUIAS_POR_LINHA em schemas/perfil.py — não nome terapêutico.';

CREATE INDEX IF NOT EXISTS idx_perfil_medico_ufcrm ON tb_perfil_medico_setor (ufcrm);
CREATE INDEX IF NOT EXISTS idx_perfil_medico_linha ON tb_perfil_medico_setor (linha_produto);


-- =============================================================
-- tb_ranking_medicos_validacao
-- POC Genie / validação de painel por SETOR+UFCRM. Mesmo grão de
-- tb_perfil_medico_setor. Só 8 das 16 colunas reais são lidas pelo
-- código novo (mapeamento de uso confirmado) — as 8 restantes entram
-- por fidelidade de schema, sem uso ativo hoje.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_ranking_medicos_validacao (
    ciclo_referencia                CHAR(6)      NOT NULL,
    setor                           VARCHAR(50)  NOT NULL,
    ufcrm                           VARCHAR(20)  NOT NULL,
    nome_medico                     VARCHAR(150) NOT NULL,
    pontos                          NUMERIC(10,2),
    posicao_ranking_setor           INTEGER,
    flag_no_painel                  INTEGER,
    qtd_medicos_painel_setor        BIGINT,
    data_ultima_visita              DATE,
    meses_desde_ultima_visita       INTEGER,
    flag_sem_visita_5_meses         INTEGER,
    flag_sem_visita_registrada      INTEGER,
    ciclos_no_painel_janela         BIGINT,
    flag_nunca_visitado_com_janela  INTEGER,
    limite_painel                   INTEGER,
    recomendacao                    VARCHAR(50),
    motivo_recomendacao             VARCHAR(80),

    CONSTRAINT pk_ranking_medicos_validacao PRIMARY KEY (setor, ufcrm)
);

COMMENT ON TABLE tb_ranking_medicos_validacao IS 'Validação de painel por SETOR+UFCRM, consumida por Ranking/Agente. Espelho local de acheinfo_dev.renovai.tb_ranking_medicos_validacao.';
COMMENT ON COLUMN tb_ranking_medicos_validacao.flag_sem_visita_5_meses IS 'Nome da coluna preservado da fonte real mesmo após a janela real ter mudado de 5 para 3 meses em 17/08/2026 (ver tb_renovai_parametros.janela_visita_meses) — resíduo de nome, não bug; não usado pelo código novo (mapeamento de uso confirmado 26/08/2026).';

CREATE INDEX IF NOT EXISTS idx_ranking_validacao_ufcrm ON tb_ranking_medicos_validacao (ufcrm);
CREATE INDEX IF NOT EXISTS idx_ranking_validacao_ciclo ON tb_ranking_medicos_validacao (ciclo_referencia);


-- =============================================================
-- tb_renovai_parametros
-- Parâmetros de negócio, fonte única, linha única (ID=1). Criada pelo
-- George em 26/08/2026 — substitui os literais 318 (limite de painel)
-- e as janelas de 5/3 meses hardcoded no código. Ver Fase 3.5.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_renovai_parametros (
    id                      INTEGER      NOT NULL,
    limite_painel_padrao    INTEGER      NOT NULL,
    janela_visita_meses     INTEGER      NOT NULL,
    janela_painel_ciclos    INTEGER      NOT NULL,
    alterado_por            VARCHAR(120),
    dt_alteracao            TIMESTAMP,

    CONSTRAINT pk_renovai_parametros PRIMARY KEY (id),
    CONSTRAINT ck_renovai_parametros_linha_unica CHECK (id = 1)
);

COMMENT ON TABLE tb_renovai_parametros IS 'Parâmetros de negócio do RenovAI, fonte única, linha única. Espelho local de acheinfo_dev.renovai.tb_renovai_parametros (criada 26/08/2026).';
COMMENT ON COLUMN tb_renovai_parametros.limite_painel_padrao IS 'Limite de médicos no painel para quem nunca teve o valor alterado pelo GD. O limite individual fica em tb_perfil_portal.limite_painel e tem precedência. Valor real confirmado: 318.';
COMMENT ON COLUMN tb_renovai_parametros.janela_visita_meses IS 'Meses sem visita que qualificam um médico para revisão de painel. Valor real confirmado: 3 (reduzido de 5 em 17/08/2026).';
COMMENT ON COLUMN tb_renovai_parametros.janela_painel_ciclos IS 'Ciclos consecutivos no painel exigidos para médico sem visita registrada entrar em revisão. Valor real confirmado: 3 (reduzido de 5 em 17/08/2026).';


-- =============================================================
-- tb_segmentacao_medico
-- Classificação de perfil de comunicação feita pelo propagandista,
-- sobrepondo o valor do SalesFarma. Sem PK: cada edição é uma linha
-- nova (histórico), igual à fonte real — perfil_anterior existe
-- justamente para reconstruir a evolução. A leitura "valor vigente"
-- é resolvida em vw_segmentacao_efetiva via ROW_NUMBER, não aqui.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_segmentacao_medico (
    setor            VARCHAR(50)  NOT NULL,
    ufcrm            VARCHAR(20)  NOT NULL,
    perfil           VARCHAR(20)  NOT NULL,
    alterado_por     VARCHAR(120) NOT NULL,
    alterado_em      TIMESTAMP    NOT NULL DEFAULT now(),
    perfil_anterior  VARCHAR(20),
    observacao       TEXT,
    versao_esquema   INTEGER      NOT NULL DEFAULT 1,

    CONSTRAINT ck_segmentacao_medico_perfil CHECK (perfil IN ('ANALITICO', 'PERFORMANCE', 'PESSOAL', 'RELACIONAL'))
);

COMMENT ON TABLE tb_segmentacao_medico IS 'Edição de perfil de comunicação pelo propagandista, histórico completo (sem PK, cada edição é linha nova). Espelho local de acheinfo_dev.renovai.tb_segmentacao_medico.';

CREATE INDEX IF NOT EXISTS idx_segmentacao_setor_ufcrm ON tb_segmentacao_medico (setor, ufcrm, alterado_em DESC);


-- =============================================================
-- tb_segmentacao_salesfarma_seed
-- NÃO EXISTE NA FONTE REAL. Simplificação local: substitui a CTE
-- "salesfarma" de vw_segmentacao_efetiva, que na fonte real lê
-- dmn_inteligencia_dados_prd.gold.vw__salesfarma_painel_medico — feed
-- externo fora do alcance deste projeto (mesmo catálogo vetado para o
-- SP, documentado em known-issues.md). Guarda só o perfil "de origem"
-- por SETOR+UFCRM, equivalente ao resultado já normalizado da fonte
-- real (ANALITICO/PERFORMANCE/PESSOAL/RELACIONAL), não o dado bruto.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_segmentacao_salesfarma_seed (
    setor   VARCHAR(50)  NOT NULL,
    ufcrm   VARCHAR(20)  NOT NULL,
    perfil  VARCHAR(20),

    CONSTRAINT pk_segmentacao_salesfarma_seed PRIMARY KEY (setor, ufcrm),
    CONSTRAINT ck_segmentacao_salesfarma_perfil CHECK (perfil IS NULL OR perfil IN ('ANALITICO', 'PERFORMANCE', 'PESSOAL', 'RELACIONAL'))
);

COMMENT ON TABLE tb_segmentacao_salesfarma_seed IS 'SIMPLIFICAÇÃO LOCAL — stand-in do baseline externo SalesFarma (vw__salesfarma_painel_medico), que este projeto não acessa. Usada só por vw_segmentacao_efetiva.';


-- =============================================================
-- tb_dim_medicos
-- Dependência de vw_agente_medico (LEFT JOIN por UFCRM). Já conhecida
-- de sincronizações anteriores (espelho de
-- dmn_inteligencia_dados_prd.gold.ranking_medicos_renovache_dim_medicos
-- no lado real) — não estava nos 7 objetos pedidos, mas é dependência
-- direta confirmada no mapeamento de código.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_dim_medicos (
    ufcrm          VARCHAR(20)   NOT NULL,
    medico         VARCHAR(150),
    especialidade  VARCHAR(100),
    cidade         VARCHAR(100),

    CONSTRAINT pk_dim_medicos PRIMARY KEY (ufcrm)
);

COMMENT ON TABLE tb_dim_medicos IS 'Espelho de dimensão de médico (UFCRM/nome/especialidade/cidade). Espelho local de acheinfo_dev.renovai.tb_dim_medicos.';


-- =============================================================
-- tb_agente_persona
-- As 4 respostas de perfil de comunicação, pré-calculadas (uma por
-- perfil). PK(perfil) é simplificação razoável: a fonte real tem 4
-- linhas hoje, uma por perfil, sem versionamento em paralelo ativo.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_agente_persona (
    perfil        VARCHAR(20)  NOT NULL,
    pergunta      TEXT         NOT NULL,
    texto         TEXT         NOT NULL,
    documentos    TEXT,
    kb_versao     VARCHAR(50),
    dt_geracao    TIMESTAMP    NOT NULL DEFAULT now(),
    fonte_hash    VARCHAR(64),

    CONSTRAINT pk_agente_persona PRIMARY KEY (perfil),
    CONSTRAINT ck_agente_persona_perfil CHECK (perfil IN ('ANALITICO', 'PERFORMANCE', 'PESSOAL', 'RELACIONAL'))
);

COMMENT ON TABLE tb_agente_persona IS 'Resposta pré-calculada de condução de visita por perfil de comunicação. Espelho local de acheinfo_dev.renovai.tb_agente_persona.';
COMMENT ON COLUMN tb_agente_persona.documentos IS 'JSON (texto) com os documentos citados, mesmo contrato de tb_agente_log.documentos_citados.';


-- =============================================================
-- tb_agente_log
-- Log de auditoria do agente do chat, write-only (INSERT via
-- agente/registro.py, nunca lido pelo código novo). 35 colunas reais
-- replicadas por inteiro — estrutura larga mas lógica simples (log).
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_agente_log (
    id_interacao           VARCHAR(64)  NOT NULL,
    id_conversa            VARCHAR(64),
    turno                  INTEGER,
    ts_inicio               TIMESTAMP,
    ts_fim                  TIMESTAMP,
    dt_referencia           DATE,
    origem                  VARCHAR(20),
    rep_matricula           VARCHAR(20),
    setor                   VARCHAR(50),
    cod_linha                VARCHAR(20),
    pergunta_original       TEXT,
    via                     VARCHAR(20),
    ferramentas             TEXT,
    sql_gerado               TEXT,
    sql_hash                VARCHAR(64),
    resultado_hash           VARCHAR(64),
    resultado_linhas         INTEGER,
    resposta_texto           TEXT,
    numeros_exibidos         TEXT,
    documentos_citados       TEXT,
    kb_versao                VARCHAR(50),
    modelo_endpoint           VARCHAR(120),
    tokens_entrada           INTEGER,
    tokens_saida             INTEGER,
    latencia_total_ms        INTEGER,
    latencia_modelo_ms       INTEGER,
    latencia_consulta_ms     INTEGER,
    sucesso                  BOOLEAN,
    erro_tipo                VARCHAR(50),
    erro_mensagem            TEXT,
    versao_esquema           INTEGER      NOT NULL DEFAULT 2,
    intencao_normalizada     TEXT,
    intencao_hash             VARCHAR(64),
    versao_normalizador       VARCHAR(20),
    verificacao_numeros       TEXT,
    verificacao_aprovada       BOOLEAN,
    chamadas_modelo           TEXT,
    custo_total                NUMERIC(12,6),
    custo_moeda                VARCHAR(10),

    CONSTRAINT pk_agente_log PRIMARY KEY (id_interacao),
    CONSTRAINT ck_agente_log_via CHECK (via IS NULL OR via IN ('via_1', 'via_2', 'conhecimento', 'recusa'))
);

COMMENT ON TABLE tb_agente_log IS 'Log unificado do agente do chat, write-only, uma linha por interação. Espelho local de acheinfo_dev.renovai.tb_agente_log. Campos *_json são gravados como TEXT (mesmo padrão da fonte real, que também grava JSON como string, já que quem escreve é o databricks-sql-connector).';

CREATE INDEX IF NOT EXISTS idx_agente_log_conversa ON tb_agente_log (id_conversa, turno);


-- =============================================================
-- vw_gold_auditpharma
-- SIMPLIFICAÇÃO LOCAL, tabela física (não view). Na fonte real é uma
-- VIEW sobre dmn_inteligencia_dados_prd.gold.tb__dashboard_audit_
-- propaganda_medica (21,8 milhões de linhas, catálogo externo que o
-- SP deste projeto não acessa — mesma razão de tb_dim_medicos). Aqui
-- vira uma tabela com poucas linhas fictícias realistas: mantém as 28
-- colunas da fonte real por fidelidade de schema, mas só popula de
-- fato as 5 colunas que o código novo lê (MERCADO, RX_MERCADO_ATUAL,
-- ESP_AUDIT, SETOR, UFCRM) — mapeamento de uso confirmado 26/08/2026.
-- O nome "vw_" é mantido porque o código consulta esse nome direto,
-- sem abstração de fonte.
-- =============================================================
CREATE TABLE IF NOT EXISTS vw_gold_auditpharma (
    referencia            VARCHAR(10),
    visitacao             INTEGER,
    indice_referencia     INTEGER,
    mercado               VARCHAR(100),
    indice_mercado        INTEGER,
    fcc                   VARCHAR(30),
    indice_fcc            INTEGER,
    produto               VARCHAR(150),
    cat_mat                VARCHAR(50),
    cat_tri                VARCHAR(50),
    setor                 VARCHAR(50),
    indice_setor           INTEGER,
    cod_linha              VARCHAR(20),
    perfil_setor            VARCHAR(50),
    flag                   INTEGER,
    ufcrm                  VARCHAR(20),
    indice_crm              INTEGER,
    indice_crm_linha        INTEGER,
    esp                    VARCHAR(100),
    divisao                 VARCHAR(50),
    esp_audit               VARCHAR(100),
    flag_esp_foco            VARCHAR(10),
    flag_esp_foco_audit      VARCHAR(10),
    rx_mercado_atual         NUMERIC(12,2),
    rx_mercado_anterior      NUMERIC(12,2),
    flag_painel              VARCHAR(10),
    ordem_produto_foco        VARCHAR(10),
    produto_foco             VARCHAR(150)
);

COMMENT ON TABLE vw_gold_auditpharma IS 'SIMPLIFICAÇÃO LOCAL, tabela física (a fonte real é view sobre catálogo externo dmn_inteligencia_dados_prd, fora do alcance deste projeto). Seed fictício de poucos mercados/produtos, suficiente para exercitar KB do chat e ranking de mercado.';

CREATE INDEX IF NOT EXISTS idx_gold_auditpharma_setor_mercado ON vw_gold_auditpharma (setor, mercado);


-- =============================================================
-- vw_agente_produtos
-- SIMPLIFICAÇÃO LOCAL, tabela física (não view). Na fonte real deriva
-- de tb_atc4_produto_ache (portfólio, ~405 milhões de linhas na
-- origem) cruzado com tb_dim_medicos.especialidade — fora de escopo
-- replicar a lógica completa (mapeamento ATC4->área terapêutica,
-- CROSS JOIN linha x especialidade, ROW_NUMBER de desempate por
-- volume de prescrição). Aqui, ORDEM_SUGERIDA já vem pré-calculada no
-- seed, sem derivar de nenhuma outra tabela local.
-- =============================================================
CREATE TABLE IF NOT EXISTS vw_agente_produtos (
    linha_produto      VARCHAR(10),
    especialidade      VARCHAR(100),
    produto            VARCHAR(150),
    categoria_atc      VARCHAR(100),
    area_terapeutica   VARCHAR(50),
    prioridade         INTEGER,
    motivo             TEXT,
    ordem_sugerida     INTEGER
);

COMMENT ON TABLE vw_agente_produtos IS 'SIMPLIFICAÇÃO LOCAL, tabela física (a fonte real deriva de tb_atc4_produto_ache, portfólio de ~405M linhas, fora do alcance deste projeto). ORDEM_SUGERIDA vem pré-calculada no seed, não derivada.';

CREATE INDEX IF NOT EXISTS idx_agente_produtos_linha_esp ON vw_agente_produtos (linha_produto, especialidade);
