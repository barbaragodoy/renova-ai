"""
Job: novo_ciclo
Roda no último dia útil do mês para encerrar o ciclo vigente e iniciar o próximo.

Execução manual:
    python -m backend.app.jobs.novo_ciclo --ciclo-atual 202507 --ciclo-novo 202508 [--dry-run]

Sequência:
  1. Expira todas as recomendações PENDENTE do ciclo anterior
  2. Chama gerar_recomendacoes para o novo ciclo
     (recomendações recorrentes incrementam qtd_vezes_recomendado automaticamente)
"""
import argparse
import logging

from sqlalchemy import create_engine, text

from backend.app.config import get_settings
from backend.app.jobs.gerar_recomendacoes import gerar_recomendacoes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renovai.job.novo_ciclo")

_Q_EXPIRAR = """
UPDATE tb_recomendacoes_painel
SET status_recomendacao    = 'EXPIRADA',
    data_ultima_verificacao = NOW()
WHERE ciclo_referencia      = :ciclo_anterior
  AND status_recomendacao   = 'PENDENTE'
RETURNING id_recomendacao
"""


def transicionar_ciclo(
    ciclo_atual: str | None = None,
    ciclo_novo: str | None = None,
    dry_run: bool = False,
) -> dict:
    settings = get_settings()
    ciclo_atual = ciclo_atual or settings.ciclo_referencia

    if ciclo_novo is None:
        # Incrementa mês: 202507 → 202508, 202512 → 202601
        ano = int(ciclo_atual[:4])
        mes = int(ciclo_atual[4:])
        if mes == 12:
            ano += 1
            mes = 1
        else:
            mes += 1
        ciclo_novo = f"{ano}{mes:02d}"

    engine = create_engine(settings.database_url)

    # Etapa 1: expirar PENDENTE do ciclo atual
    expiradas = 0
    with engine.connect() as conn:
        logger.info("Expirando recomendações PENDENTE do ciclo %s...", ciclo_atual)
        if not dry_run:
            rows = conn.execute(text(_Q_EXPIRAR), {"ciclo_anterior": ciclo_atual}).fetchall()
            expiradas = len(rows)
            conn.commit()
        else:
            from sqlalchemy import select
            count_row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM tb_recomendacoes_painel "
                    "WHERE ciclo_referencia = :c AND status_recomendacao = 'PENDENTE'"
                ),
                {"c": ciclo_atual},
            ).scalar()
            expiradas = count_row or 0

    logger.info("Expiradas: %d | ciclo=%s", expiradas, ciclo_atual)

    # Etapa 2: gerar recomendações para o novo ciclo
    logger.info("Gerando recomendações para o ciclo %s...", ciclo_novo)
    resultado_geracao = gerar_recomendacoes(ciclo=ciclo_novo, dry_run=dry_run)

    return {
        "ciclo_encerrado": ciclo_atual,
        "ciclo_novo": ciclo_novo,
        "dry_run": dry_run,
        "expiradas": expiradas,
        **{f"novo_{k}": v for k, v in resultado_geracao.items() if k not in ("ciclo", "dry_run")},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Encerra ciclo vigente e abre novo ciclo RenovAI.")
    parser.add_argument("--ciclo-atual", default=None, help="Ciclo a encerrar (ex: 202507).")
    parser.add_argument("--ciclo-novo", default=None, help="Novo ciclo a abrir (ex: 202508). Calculado se omitido.")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar no banco.")
    args = parser.parse_args()
    resultado = transicionar_ciclo(
        ciclo_atual=args.ciclo_atual,
        ciclo_novo=args.ciclo_novo,
        dry_run=args.dry_run,
    )
    print(resultado)
