"""
Job: gerar_recomendacoes
Gera sugestões ENTRADA_PAINEL e REVISAO_PAINEL para todos os propagandistas ativos.

Execução manual:
    python -m backend.app.jobs.gerar_recomendacoes [--ciclo 202507] [--dry-run]

Configurável via variáveis de ambiente (config.py):
    CICLO_REFERENCIA, CORTE_RANKING, SEM_VISITA_MESES, LIMITE_SUGESTOES
"""
import argparse
import logging
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from backend.app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renovai.job.recomendacoes")

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_Q_PROPAGANDISTAS = """
SELECT rep_matricula, setor, cod_linha
FROM tb_propagandistas
WHERE ativo = TRUE
"""

# Candidatos a ENTRADA_PAINEL:
# - no ranking (corte <= :corte) do ciclo
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
  AND r.posicao_ranking  <= :corte
  AND p.ufcrm IS NULL
ORDER BY r.soma_pontuacao DESC
LIMIT :limite
"""

# Candidatos a REVISAO_PAINEL — dois motivos:
#   1. posicao_ranking > corte  → ABAIXO_CORTE
#   2. sem visita efetiva há > N meses → SEM_VISITA_5_MESES
_Q_REVISAO = """
SELECT
    p.ufcrm,
    p.nome_medico,
    r.posicao_ranking,
    r.soma_pontuacao,
    CASE
        WHEN r.posicao_ranking > :corte THEN 'ABAIXO_CORTE'
        ELSE 'SEM_VISITA_5_MESES'
    END AS motivo_revisao
FROM tb_painel_medico p
LEFT JOIN tb_ranking_medicos r
       ON r.ufcrm             = p.ufcrm
      AND r.setor             = p.setor
      AND r.ciclo_referencia  = :ciclo
WHERE p.setor            = :setor
  AND p.ciclo_referencia = :ciclo
  AND p.ativo            = TRUE
  AND (
      r.posicao_ranking > :corte
      OR NOT EXISTS (
          SELECT 1 FROM tb_visitacao_medica v
          WHERE v.ufcrm        = p.ufcrm
            AND v.setor        = p.setor
            AND v.visita_efetiva = TRUE
            AND v.data_visita  >= :data_corte_visita
      )
  )
ORDER BY r.posicao_ranking DESC NULLS LAST
LIMIT :limite
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
# ---------------------------------------------------------------------------

def _justificativa_entrada(nome_medico: str, posicao: int, pontuacao: float) -> str:
    return (
        f"{nome_medico} ocupa a posição #{posicao} no ranking com pontuação {pontuacao:.2f}, "
        f"indicando alto potencial de prescrição. Recomenda-se incluir este médico no painel "
        f"para ampliar o alcance da linha no ciclo vigente."
    )


def _justificativa_revisao(nome_medico: str, motivo: str, posicao: int | None) -> str:
    if motivo == "ABAIXO_CORTE":
        return (
            f"{nome_medico} está no painel, porém ocupa a posição #{posicao} no ranking, "
            f"abaixo do corte de elegibilidade. Recomenda-se revisar a manutenção deste médico "
            f"no painel para o próximo ciclo."
        )
    return (
        f"{nome_medico} está no painel, mas não registrou visita efetiva nos últimos 5 meses. "
        f"Recomenda-se verificar o relacionamento com este médico e avaliar a continuidade no painel."
    )


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def gerar_recomendacoes(ciclo: str | None = None, dry_run: bool = False) -> dict:
    settings = get_settings()
    ciclo = ciclo or settings.ciclo_referencia
    corte = settings.corte_ranking
    limite = settings.limite_sugestoes
    data_corte_visita = date.today() - timedelta(days=settings.sem_visita_meses * 30)

    engine = create_engine(settings.database_url)
    contadores = {"entrada_inseridos": 0, "entrada_incrementados": 0,
                  "revisao_inseridos": 0, "revisao_incrementados": 0}

    with engine.connect() as conn:
        propagandistas = conn.execute(text(_Q_PROPAGANDISTAS)).mappings().fetchall()
        logger.info("Propagandistas ativos: %d | ciclo=%s | corte=%d", len(propagandistas), ciclo, corte)

        for rep in propagandistas:
            mat = rep["rep_matricula"]
            setor = rep["setor"]
            cod_linha = rep["cod_linha"]

            # --- ENTRADA_PAINEL ---
            candidatos_entrada = conn.execute(
                text(_Q_ENTRADA),
                {"setor": setor, "cod_linha": cod_linha, "ciclo": ciclo,
                 "corte": corte, "limite": limite},
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
            candidatos_revisao = conn.execute(
                text(_Q_REVISAO),
                {"setor": setor, "ciclo": ciclo, "corte": corte,
                 "limite": limite, "data_corte_visita": data_corte_visita},
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
                                c["nome_medico"], motivo, c["posicao_ranking"]
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
