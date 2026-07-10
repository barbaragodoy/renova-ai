-- =============================================================
-- RenovAI — DDL completo
-- Simulação local do PED 2.0 / Aché Farma
-- =============================================================

-- Extensão para UUID
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================
-- tb_propagandistas
-- Cadastro de propagandistas (representantes). Backend nunca
-- expõe esta tabela diretamente ao usuário final.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_propagandistas (
    rep_matricula   VARCHAR(20)  NOT NULL,
    rep_email       VARCHAR(120) NOT NULL,
    setor           VARCHAR(50)  NOT NULL,  -- setor de atuação do rep
    cod_linha       VARCHAR(20)  NOT NULL,  -- linha de produto
    rep_nome        VARCHAR(120) NOT NULL,
    ativo           BOOLEAN      NOT NULL DEFAULT TRUE,

    CONSTRAINT pk_propagandistas PRIMARY KEY (rep_matricula)
);

COMMENT ON TABLE  tb_propagandistas                IS 'Cadastro de propagandistas (representantes). Nunca exposta ao usuário via API.';
COMMENT ON COLUMN tb_propagandistas.rep_matricula  IS 'Matrícula única do propagandista.';
COMMENT ON COLUMN tb_propagandistas.rep_email      IS 'E-mail corporativo usado na autenticação Auth0 / Entra ID.';
COMMENT ON COLUMN tb_propagandistas.setor          IS 'Setor de atuação do propagandista.';
COMMENT ON COLUMN tb_propagandistas.cod_linha      IS 'Código da linha de produto do propagandista.';
COMMENT ON COLUMN tb_propagandistas.ativo          IS 'FALSE quando o propagandista está inativo/desligado.';

CREATE INDEX IF NOT EXISTS idx_prop_setor     ON tb_propagandistas (setor);
CREATE INDEX IF NOT EXISTS idx_prop_cod_linha ON tb_propagandistas (cod_linha);
CREATE INDEX IF NOT EXISTS idx_prop_email     ON tb_propagandistas (rep_email);


-- =============================================================
-- tb_ranking_medicos
-- Ranking mensal de médicos por setor/linha.
-- Corte de entrada: posicao_ranking <= 400
-- Corte de revisão: posicao_ranking > 400
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_ranking_medicos (
    setor               VARCHAR(50)  NOT NULL,
    cod_linha           VARCHAR(20)  NOT NULL,
    ufcrm               VARCHAR(20)  NOT NULL,  -- identificador único do médico
    nome_medico         VARCHAR(150) NOT NULL,
    soma_pontuacao      NUMERIC(12,4) NOT NULL DEFAULT 0,
    posicao_ranking     INTEGER      NOT NULL,
    ciclo_referencia    CHAR(6)      NOT NULL,  -- formato aaaamm

    CONSTRAINT pk_ranking PRIMARY KEY (setor, cod_linha, ufcrm, ciclo_referencia)
);

COMMENT ON TABLE  tb_ranking_medicos                 IS 'Ranking mensal de médicos por setor e linha de produto.';
COMMENT ON COLUMN tb_ranking_medicos.ufcrm           IS 'Identificador único do médico (UF + número CRM).';
COMMENT ON COLUMN tb_ranking_medicos.soma_pontuacao  IS 'Soma ponderada dos critérios de ranqueamento do ciclo.';
COMMENT ON COLUMN tb_ranking_medicos.posicao_ranking IS 'Posição no ranking. <= 400 = entrada; > 400 = revisão.';
COMMENT ON COLUMN tb_ranking_medicos.ciclo_referencia IS 'Ciclo de referência no formato aaaamm (ex: 202606).';

CREATE INDEX IF NOT EXISTS idx_rank_setor      ON tb_ranking_medicos (setor);
CREATE INDEX IF NOT EXISTS idx_rank_ufcrm      ON tb_ranking_medicos (ufcrm);
CREATE INDEX IF NOT EXISTS idx_rank_ciclo      ON tb_ranking_medicos (ciclo_referencia);
CREATE INDEX IF NOT EXISTS idx_rank_setor_ciclo ON tb_ranking_medicos (setor, ciclo_referencia);


-- =============================================================
-- tb_painel_medico
-- Painel atual de médicos visitados pelo propagandista.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_painel_medico (
    setor               VARCHAR(50)  NOT NULL,
    ufcrm               VARCHAR(20)  NOT NULL,
    nome_medico         VARCHAR(150) NOT NULL,
    especialidade       VARCHAR(100),
    data_inclusao       DATE         NOT NULL,
    ativo               BOOLEAN      NOT NULL DEFAULT TRUE,
    ciclo_referencia    CHAR(6)      NOT NULL,

    CONSTRAINT pk_painel PRIMARY KEY (setor, ufcrm, ciclo_referencia)
);

COMMENT ON TABLE  tb_painel_medico                  IS 'Painel de médicos em acompanhamento pelo setor no ciclo.';
COMMENT ON COLUMN tb_painel_medico.ufcrm            IS 'Identificador único do médico.';
COMMENT ON COLUMN tb_painel_medico.ativo            IS 'FALSE quando o médico foi removido do painel no ciclo.';
COMMENT ON COLUMN tb_painel_medico.ciclo_referencia IS 'Ciclo de referência no formato aaaamm.';

CREATE INDEX IF NOT EXISTS idx_painel_setor  ON tb_painel_medico (setor);
CREATE INDEX IF NOT EXISTS idx_painel_ufcrm  ON tb_painel_medico (ufcrm);
CREATE INDEX IF NOT EXISTS idx_painel_ciclo  ON tb_painel_medico (ciclo_referencia);


-- =============================================================
-- tb_prescricoes_geral
-- Prescrições capturadas por fonte externa (ex: IQVIA/Close-Up).
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_prescricoes_geral (
    codigo_medico       VARCHAR(30)  NOT NULL,
    ufcrm               VARCHAR(20)  NOT NULL,
    nome_medico         VARCHAR(150) NOT NULL,
    especialidade       VARCHAR(100),
    nome_medicacao      VARCHAR(150) NOT NULL,
    fabricante          VARCHAR(100),
    quantidade          INTEGER      NOT NULL DEFAULT 0,
    data_prescricao     DATE         NOT NULL,
    setor               VARCHAR(50)  NOT NULL,

    CONSTRAINT pk_prescricoes PRIMARY KEY (codigo_medico, nome_medicacao, data_prescricao)
);

COMMENT ON TABLE  tb_prescricoes_geral               IS 'Prescrições de mercado capturadas por fonte externa.';
COMMENT ON COLUMN tb_prescricoes_geral.codigo_medico IS 'Código interno do médico na fonte externa.';
COMMENT ON COLUMN tb_prescricoes_geral.ufcrm         IS 'Identificador único do médico (chave de join).';
COMMENT ON COLUMN tb_prescricoes_geral.quantidade    IS 'Número de prescrições da medicação no período.';

CREATE INDEX IF NOT EXISTS idx_presc_ufcrm  ON tb_prescricoes_geral (ufcrm);
CREATE INDEX IF NOT EXISTS idx_presc_setor  ON tb_prescricoes_geral (setor);
CREATE INDEX IF NOT EXISTS idx_presc_data   ON tb_prescricoes_geral (data_prescricao);


-- =============================================================
-- tb_recomendacoes_painel
-- Recomendações geradas pelo motor de IA para o painel do rep.
-- Máximo 5 sugestões por retorno, separadas por tipo.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_recomendacoes_painel (
    id_recomendacao             UUID         NOT NULL DEFAULT gen_random_uuid(),
    rep_matricula               VARCHAR(20)  NOT NULL,
    setor                       VARCHAR(50)  NOT NULL,
    cod_linha                   VARCHAR(20)  NOT NULL,
    ufcrm                       VARCHAR(20)  NOT NULL,
    nome_medico                 VARCHAR(150) NOT NULL,
    tipo_recomendacao           VARCHAR(20)  NOT NULL
        CHECK (tipo_recomendacao IN ('ENTRADA_PAINEL', 'REVISAO_PAINEL')),
    status_recomendacao         VARCHAR(20)  NOT NULL DEFAULT 'PENDENTE'
        CHECK (status_recomendacao IN ('PENDENTE', 'DESCONSIDERADA', 'APLICADA', 'EXPIRADA')),
    posicao_ranking             INTEGER,
    soma_pontuacao              NUMERIC(12,4),
    motivo_revisao              TEXT,           -- texto livre gerado pelo LLM
    justificativa_texto         TEXT,           -- justificativa narrativa
    ciclo_referencia            CHAR(6)      NOT NULL,
    data_geracao                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    motivo_desconsideracao      TEXT,
    timestamp_desconsideracao   TIMESTAMPTZ,
    rep_matricula_desconsiderou VARCHAR(20),    -- quem desconsiderou (pode ser GD)
    qtd_vezes_recomendado       INTEGER      NOT NULL DEFAULT 1,
    data_ultima_verificacao     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_recomendacoes PRIMARY KEY (id_recomendacao),
    CONSTRAINT fk_rec_propagandista FOREIGN KEY (rep_matricula)
        REFERENCES tb_propagandistas (rep_matricula)
);

COMMENT ON TABLE  tb_recomendacoes_painel                      IS 'Recomendações geradas pelo motor RenovAI por ciclo.';
COMMENT ON COLUMN tb_recomendacoes_painel.tipo_recomendacao    IS 'ENTRADA_PAINEL: médico fora do painel para incluir. REVISAO_PAINEL: médico no painel para revisar saída.';
COMMENT ON COLUMN tb_recomendacoes_painel.status_recomendacao  IS 'PENDENTE=aguardando ação; DESCONSIDERADA=ignorada pelo rep/GD; APLICADA=ação tomada; EXPIRADA=ciclo encerrado.';
COMMENT ON COLUMN tb_recomendacoes_painel.motivo_revisao       IS 'Texto gerado pelo LLM explicando o motivo da revisão (ex: médico sem visita há X meses).';
COMMENT ON COLUMN tb_recomendacoes_painel.qtd_vezes_recomendado IS 'Quantas vezes este médico foi recomendado ao rep no histórico.';
COMMENT ON COLUMN tb_recomendacoes_painel.rep_matricula_desconsiderou IS 'Matrícula de quem desconsiderou (pode ser o próprio rep ou o GD).';

CREATE INDEX IF NOT EXISTS idx_rec_rep_matricula  ON tb_recomendacoes_painel (rep_matricula);
CREATE INDEX IF NOT EXISTS idx_rec_setor          ON tb_recomendacoes_painel (setor);
CREATE INDEX IF NOT EXISTS idx_rec_ufcrm          ON tb_recomendacoes_painel (ufcrm);
CREATE INDEX IF NOT EXISTS idx_rec_ciclo          ON tb_recomendacoes_painel (ciclo_referencia);
CREATE INDEX IF NOT EXISTS idx_rec_status         ON tb_recomendacoes_painel (status_recomendacao);
CREATE INDEX IF NOT EXISTS idx_rec_rep_ciclo      ON tb_recomendacoes_painel (rep_matricula, ciclo_referencia);


-- =============================================================
-- tb_hierarquia_gd
-- Relacionamento entre Gerente Distrital (GD) e propagandistas.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_hierarquia_gd (
    gd_matricula    VARCHAR(20)  NOT NULL,
    gd_email        VARCHAR(120) NOT NULL,
    gd_nome         VARCHAR(120) NOT NULL,
    rep_matricula   VARCHAR(20)  NOT NULL,
    setor           VARCHAR(50)  NOT NULL,

    CONSTRAINT pk_hierarquia_gd PRIMARY KEY (gd_matricula, rep_matricula),
    CONSTRAINT fk_hier_propagandista FOREIGN KEY (rep_matricula)
        REFERENCES tb_propagandistas (rep_matricula)
);

COMMENT ON TABLE  tb_hierarquia_gd               IS 'Hierarquia entre Gerentes Distritais e propagandistas subordinados.';
COMMENT ON COLUMN tb_hierarquia_gd.gd_matricula  IS 'Matrícula do Gerente Distrital.';
COMMENT ON COLUMN tb_hierarquia_gd.rep_matricula IS 'Matrícula do propagandista subordinado ao GD.';
COMMENT ON COLUMN tb_hierarquia_gd.setor         IS 'Setor compartilhado GD-rep (fonte a confirmar com Hugo).';

CREATE INDEX IF NOT EXISTS idx_hier_rep    ON tb_hierarquia_gd (rep_matricula);
CREATE INDEX IF NOT EXISTS idx_hier_setor  ON tb_hierarquia_gd (setor);
CREATE INDEX IF NOT EXISTS idx_hier_email  ON tb_hierarquia_gd (gd_email);


-- =============================================================
-- tb_visitacao_medica
-- Registro de visitas ao médico por setor/ciclo.
-- Regra: médico sem visita efetiva há > 5 meses → critério de revisão.
-- =============================================================
CREATE TABLE IF NOT EXISTS tb_visitacao_medica (
    setor               VARCHAR(50) NOT NULL,
    ufcrm               VARCHAR(20) NOT NULL,
    data_visita         DATE        NOT NULL,
    visita_efetiva      BOOLEAN     NOT NULL DEFAULT TRUE,  -- FALSE = tentativa sem contato
    ciclo_referencia    CHAR(6)     NOT NULL,

    CONSTRAINT pk_visitacao PRIMARY KEY (setor, ufcrm, data_visita)
);

COMMENT ON TABLE  tb_visitacao_medica                IS 'Registro de visitas médicas realizadas ou tentadas.';
COMMENT ON COLUMN tb_visitacao_medica.ufcrm          IS 'Identificador único do médico visitado.';
COMMENT ON COLUMN tb_visitacao_medica.visita_efetiva IS 'TRUE = contato realizado; FALSE = tentativa sem contato com o médico.';
COMMENT ON COLUMN tb_visitacao_medica.ciclo_referencia IS 'Ciclo em que a visita ocorreu (aaaamm).';

CREATE INDEX IF NOT EXISTS idx_visit_ufcrm  ON tb_visitacao_medica (ufcrm);
CREATE INDEX IF NOT EXISTS idx_visit_setor  ON tb_visitacao_medica (setor);
CREATE INDEX IF NOT EXISTS idx_visit_ciclo  ON tb_visitacao_medica (ciclo_referencia);
CREATE INDEX IF NOT EXISTS idx_visit_data   ON tb_visitacao_medica (data_visita);
CREATE INDEX IF NOT EXISTS idx_visit_setor_ufcrm ON tb_visitacao_medica (setor, ufcrm);
