"""
Job: gerar_recomendacoes
Gera sugestões ENTRADA_PAINEL e REVISAO_PAINEL para todos os propagandistas ativos.

Execução manual:
    python -m backend.app.jobs.gerar_recomendacoes [--ciclo 202507] [--dry-run]

Configurável via variáveis de ambiente (config.py):
    CICLO_REFERENCIA, SEM_VISITA_MESES, LIMITE_SUGESTOES

Sprint 6 — o corte fixo de ranking (CORTE_RANKING, 400 prod / 100 local) foi
substituído pelo limite de painel por propagandista (LIMITE_PAINEL em
tb_perfil_portal, COALESCE(..., LIMITE_PAINEL_PADRAO de tb_renovai_parametros)
— mesmo padrão confirmado pelo Hugo no notebook real, ver
docs/context/decisions-log.md; 318 deixou de ser literal no código em
26/08/2026, quando o George criou tb_renovai_parametros como fonte única).
Este job é a simulação
LOCAL do que o notebook do Hugo já calcula pronto no Databricks — aqui
recalculamos porque o Postgres local não tem um pipeline equivalente
gerando tb_recomendacoes_painel; o endpoint REST (routers/recomendacoes.py)
contra o Databricks real só CONSOME TIPO_RECOMENDACAO/MOTIVO_RECOMENDACAO
já prontos, sem recalcular nada disso.
"""
import argparse
import logging
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from backend.app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renovai.job.recomendacoes")

# Ciclos consecutivos mínimos no painel para um médico entrar na regra de
# sem-visita (Sprint 6: era >= 5, agora >= 3 — mesma mudança aplicada à
# janela de meses sem visita). Evita marcar para revisão um médico
# recém-incluído no painel que ainda não teve tempo/oportunidade de ser
# visitado (regra de negócio confirmada por George em 2026-08-06, ver
# docs/context/known-issues.md).
#
# PROXY, NÃO CONTAGEM REAL — PRECISA DE REVISÃO HUMANA: a seed local
# (data/scripts/03_populate_ranking.sql e 04_populate_painel.sql) só tem UM
# ciclo (202507) populado; tb_painel_medico não guarda histórico
# multi-ciclo aqui, então não há como contar "ciclos consecutivos" de
# verdade nesta simulação. Usamos DATA_INCLUSAO (já existente na tabela,
# preenchida com 2025-01-01 na seed) como proxy de tempo de permanência no
# painel — mesma direção da regra real (proteger quem entrou há pouco), mas
# não é a mesma métrica. Se a seed ganhar múltiplos ciclos no futuro, trocar
# por uma contagem real de linhas consecutivas em tb_painel_medico.
_CICLOS_PAINEL_MIN = 3

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_Q_PROPAGANDISTAS = """
SELECT rep_matricula, setor, cod_linha
FROM tb_propagandistas
WHERE ativo = TRUE
"""

_Q_LIMITE_PAINEL = """
SELECT COALESCE(limite_painel, :limite_padrao) AS limite
FROM tb_perfil_portal
WHERE rep_matricula = :rep_matricula
"""

# Fonte única do default (318 confirmado real) — substitui o literal 318
# hardcoded que existia aqui antes de tb_renovai_parametros existir (criada
# pelo George em 26/08/2026, ver docs/context/decisions-log.md).
_Q_LIMITE_PAINEL_PADRAO = """
SELECT limite_painel_padrao FROM tb_renovai_parametros WHERE id = 1
"""

_Q_PAINEL_SIZE = """
SELECT COUNT(*) AS qtd
FROM tb_painel_medico
WHERE setor = :setor AND ciclo_referencia = :ciclo AND ativo = TRUE
"""

# Candidatos a ENTRADA_PAINEL:
# - ranking dentro do limite do propagandista (:limite_painel) no ciclo
# - fora do painel do mesmo setor no ciclo
_Q_ENTRADA = """
SELECT r.ufcrm, r.nome_medico, r.posicao_ranking, r.soma_pontuacao
FROM tb_ranking_medicos r
LEFT JOIN tb_painel_medico p
       ON p.ufcrm = r.ufcrm
      AND p.setor = r.setor
      AND p.ciclo_referencia = r.ciclo_referencia
WHERE r.setor            = :setor
  AND r.cod_linha        = :cod_linha
  AND r.ciclo_referencia = :ciclo
  AND r.posicao_ranking  <= :limite_painel
  AND p.ufcrm IS NULL
ORDER BY r.soma_pontuacao DESC
LIMIT :limite_sugestoes
"""

# Candidatos a REVISAO_PAINEL. Só é consultada quando o painel do
# propagandista já está acima do próprio limite (guarda em Python, ver
# gerar_recomendacoes() — "painel do propagandista acima do próprio limite"
# é precondição para qualquer revisão, comparação estrita > confirmada pelo
# Hugo: painel exatamente no limite não gera revisão).
#
# ranking_acima_limite: ranking do médico acima do limite do propagandista
#   (substitui o corte fixo 400/ABAIXO_CORTE).
# sem_visita_elegivel: sem visita efetiva há >= SEM_VISITA_MESES E há pelo
#   menos _CICLOS_PAINEL_MIN "ciclos" no painel (proxy via DATA_INCLUSAO,
#   ver comentário de _CICLOS_PAINEL_MIN acima).
_Q_REVISAO = """
WITH candidatos AS (
    SELECT
        p.ufcrm,
        p.nome_medico,
        r.posicao_ranking,
        r.soma_pontuacao,
        (r.posicao_ranking > :limite_painel) AS ranking_acima_limite,
        (
            NOT EXISTS (
                SELECT 1 FROM tb_visitacao_medica v
                WHERE v.ufcrm        = p.ufcrm
                  AND v.setor        = p.setor
                  AND v.visita_efetiva = TRUE
                  AND v.data_visita  >= :data_corte_visita
            )
            AND p.data_inclusao <= :data_corte_ciclos_painel
        ) AS sem_visita_elegivel
    FROM tb_painel_medico p
    LEFT JOIN tb_ranking_medicos r
           ON r.ufcrm             = p.ufcrm
          AND r.setor             = p.setor
          AND r.ciclo_referencia  = :ciclo
    WHERE p.setor            = :setor
      AND p.ciclo_referencia = :ciclo
      AND p.ativo            = TRUE
)
SELECT
    ufcrm, nome_medico, posicao_ranking, soma_pontuacao,
    CASE
        WHEN ranking_acima_limite AND sem_visita_elegivel
            THEN 'REVISAO_RANKING_SETOR_ACIMA_LIMITE_E_SEM_VISITA_3_MESES'
        WHEN ranking_acima_limite
            THEN 'REVISAO_RANKING_SETOR_ACIMA_LIMITE'
        ELSE 'REVISAO_SEM_VISITA_3_MESES'
    END AS motivo_revisao
FROM candidatos
WHERE ranking_acima_limite OR sem_visita_elegivel
ORDER BY posicao_ranking DESC NULLS LAST
LIMIT :limite_sugestoes
"""

_Q_EXISTE = """
SELECT id_recomendacao, qtd_vezes_recomendado
FROM tb_recomendacoes_painel
WHERE rep_matricula      = :rep_matricula
  AND ufcrm              = :ufcrm
  AND tipo_recomendacao  = :tipo
  AND ciclo_referencia   = :ciclo
LIMIT 1
"""

_Q_INSERT = """
INSERT INTO tb_recomendacoes_painel (
    rep_matricula, setor, cod_linha, ufcrm, nome_medico,
    tipo_recomendacao, status_recomendacao,
    posicao_ranking, soma_pontuacao,
    motivo_revisao, justificativa_texto,
    ciclo_referencia, qtd_vezes_recomendado
) VALUES (
    :rep_matricula, :setor, :cod_linha, :ufcrm, :nome_medico,
    :tipo, 'PENDENTE',
    :posicao_ranking, :soma_pontuacao,
    :motivo_revisao, :justificativa_texto,
    :ciclo, 1
)
"""

_Q_UPDATE_CONTADOR = """
UPDATE tb_recomendacoes_painel
SET qtd_vezes_recomendado    = qtd_vezes_recomendado + 1,
    data_ultima_verificacao  = NOW()
WHERE id_recomendacao = :id
"""

# ---------------------------------------------------------------------------
# Justificativa consultiva
#
# Diretriz de tom (Sprint 6): lembrete preventivo de rotina, não aviso de
# falha/abandono — o ciclo de SEM_VISITA_MESES (3) antecede a exclusão
# automática da Aché (5 meses, podendo passar a 4), então o objetivo é dar
# tempo do propagandista agir, não repreender. Evita "abandono",
# "negligência", "não visitado". TEXTO ESCOLHIDO SEM REVISÃO DE REDAÇÃO —
# ver relatório da execução, "PRECISA DE REVISÃO HUMANA DE REDAÇÃO".
# ---------------------------------------------------------------------------

def _justificativa_entrada(nome_medico: str, posicao: int, pontuacao: float) -> str:
    return (
        f"{nome_medico} ocupa a posição #{posicao} no ranking com pontuação {pontuacao:.2f}, "
        f"indicando alto potencial de prescrição. Recomenda-se incluir este médico no painel "
        f"para ampliar o alcance da linha no ciclo vigente."
    )


def _justificativa_revisao(nome_medico: str, motivo: str, posicao: int | None, sem_visita_meses: int) -> str:
    if motivo == "REVISAO_RANKING_SETOR_ACIMA_LIMITE":
        return (
            f"{nome_medico} está no painel, mas a posição atual no ranking do setor (#{posicao}) "
            f"já passou do limite ideal do seu painel. Recomenda-se revisar a manutenção deste "
            f"médico no painel para o próximo ciclo."
        )
    if motivo == "REVISAO_SEM_VISITA_3_MESES":
        return (
            f"Este médico está há {sem_visita_meses} meses sem registro de visita. "
            f"Recomendamos priorizá-lo nas próximas visitas do ciclo."
        )
    # REVISAO_RANKING_SETOR_ACIMA_LIMITE_E_SEM_VISITA_3_MESES
    return (
        f"{nome_medico} está no painel, mas já passou do limite ideal do seu painel no ranking "
        f"do setor e está há {sem_visita_meses} meses sem registro de visita. Recomendamos "
        f"priorizá-lo nas próximas visitas e revisar a manutenção no painel."
    )


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def gerar_recomendacoes(ciclo: str | None = None, dry_run: bool = False) -> dict:
    settings = get_settings()
    ciclo = ciclo or settings.ciclo_referencia
    limite_sugestoes = settings.limite_sugestoes
    sem_visita_meses = settings.sem_visita_meses
    data_corte_visita = date.today() - timedelta(days=sem_visita_meses * 30)
    data_corte_ciclos_painel = date.today() - timedelta(days=_CICLOS_PAINEL_MIN * 30)

    engine = create_engine(settings.database_url)
    contadores = {"entrada_inseridos": 0, "entrada_incrementados": 0,
                  "revisao_inseridos": 0, "revisao_incrementados": 0}

    with engine.connect() as conn:
        propagandistas = conn.execute(text(_Q_PROPAGANDISTAS)).mappings().fetchall()
        logger.info("Propagandistas ativos: %d | ciclo=%s", len(propagandistas), ciclo)

        # Buscado uma vez fora do loop: mesmo valor para todo propagandista
        # sem personalização, sem repetir a consulta a cada iteração.
        limite_painel_padrao = conn.execute(text(_Q_LIMITE_PAINEL_PADRAO)).scalar()

        for rep in propagandistas:
            mat = rep["rep_matricula"]
            setor = rep["setor"]
            cod_linha = rep["cod_linha"]

            limite_row = conn.execute(
                text(_Q_LIMITE_PAINEL),
                {"rep_matricula": mat, "limite_padrao": limite_painel_padrao},
            ).mappings().fetchone()
            limite_painel = limite_row["limite"] if limite_row else limite_painel_padrao

            # --- ENTRADA_PAINEL ---
            candidatos_entrada = conn.execute(
                text(_Q_ENTRADA),
                {"setor": setor, "cod_linha": cod_linha, "ciclo": ciclo,
                 "limite_painel": limite_painel, "limite_sugestoes": limite_sugestoes},
            ).mappings().fetchall()

            for c in candidatos_entrada:
                existing = conn.execute(
                    text(_Q_EXISTE),
                    {"rep_matricula": mat, "ufcrm": c["ufcrm"], "tipo": "ENTRADA_PAINEL", "ciclo": ciclo},
                ).mappings().fetchone()

                if existing:
                    if not dry_run:
                        conn.execute(text(_Q_UPDATE_CONTADOR), {"id": existing["id_recomendacao"]})
                    contadores["entrada_incrementados"] += 1
                    logger.debug("ENTRADA increment | rep=%s ufcrm=%s", mat, c["ufcrm"])
                else:
                    if not dry_run:
                        conn.execute(text(_Q_INSERT), {
                            "rep_matricula": mat, "setor": setor, "cod_linha": cod_linha,
                            "ufcrm": c["ufcrm"], "nome_medico": c["nome_medico"],
                            "tipo": "ENTRADA_PAINEL",
                            "posicao_ranking": c["posicao_ranking"],
                            "soma_pontuacao": float(c["soma_pontuacao"]),
                            "motivo_revisao": None,
                            "justificativa_texto": _justificativa_entrada(
                                c["nome_medico"], c["posicao_ranking"], float(c["soma_pontuacao"])
                            ),
                            "ciclo": ciclo,
                        })
                    contadores["entrada_inseridos"] += 1
                    logger.debug("ENTRADA insert | rep=%s ufcrm=%s pos=%s", mat, c["ufcrm"], c["posicao_ranking"])

            # --- REVISAO_PAINEL ---
            # Precondição confirmada pelo Hugo: só há revisão quando o painel
            # do propagandista já está ACIMA do próprio limite (comparação
            # estrita > — painel exatamente no limite não gera revisão).
            qtd_painel = conn.execute(text(_Q_PAINEL_SIZE), {"setor": setor, "ciclo": ciclo}).scalar() or 0
            candidatos_revisao = []
            if qtd_painel > limite_painel:
                candidatos_revisao = conn.execute(
                    text(_Q_REVISAO),
                    {"setor": setor, "ciclo": ciclo, "limite_painel": limite_painel,
                     "limite_sugestoes": limite_sugestoes, "data_corte_visita": data_corte_visita,
                     "data_corte_ciclos_painel": data_corte_ciclos_painel},
                ).mappings().fetchall()

            for c in candidatos_revisao:
                existing = conn.execute(
                    text(_Q_EXISTE),
                    {"rep_matricula": mat, "ufcrm": c["ufcrm"], "tipo": "REVISAO_PAINEL", "ciclo": ciclo},
                ).mappings().fetchone()

                motivo = c["motivo_revisao"]
                if existing:
                    if not dry_run:
                        conn.execute(text(_Q_UPDATE_CONTADOR), {"id": existing["id_recomendacao"]})
                    contadores["revisao_incrementados"] += 1
                    logger.debug("REVISAO increment | rep=%s ufcrm=%s motivo=%s", mat, c["ufcrm"], motivo)
                else:
                    if not dry_run:
                        conn.execute(text(_Q_INSERT), {
                            "rep_matricula": mat, "setor": setor, "cod_linha": cod_linha,
                            "ufcrm": c["ufcrm"], "nome_medico": c["nome_medico"],
                            "tipo": "REVISAO_PAINEL",
                            "posicao_ranking": c["posicao_ranking"],
                            "soma_pontuacao": float(c["soma_pontuacao"]) if c["soma_pontuacao"] else None,
                            "motivo_revisao": motivo,
                            "justificativa_texto": _justificativa_revisao(
                                c["nome_medico"], motivo, c["posicao_ranking"], sem_visita_meses
                            ),
                            "ciclo": ciclo,
                        })
                    contadores["revisao_inseridos"] += 1
                    logger.debug("REVISAO insert | rep=%s ufcrm=%s motivo=%s", mat, c["ufcrm"], motivo)

        if not dry_run:
            conn.commit()

    logger.info(
        "Concluído%s | entrada: +%d novos / %d incrementados | revisão: +%d novos / %d incrementados",
        " [DRY-RUN]" if dry_run else "",
        contadores["entrada_inseridos"], contadores["entrada_incrementados"],
        contadores["revisao_inseridos"], contadores["revisao_incrementados"],
    )
    return {"ciclo": ciclo, "dry_run": dry_run, **contadores}


# ---------------------------------------------------------------------------
# Entrypoint CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera recomendações RenovAI para o ciclo informado.")
    parser.add_argument("--ciclo", default=None, help="Ciclo de referência (ex: 202507). Default: config.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar no banco.")
    args = parser.parse_args()
    resultado = gerar_recomendacoes(ciclo=args.ciclo, dry_run=args.dry_run)
    print(resultado)
