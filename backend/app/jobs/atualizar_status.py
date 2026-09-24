"""
Job: atualizar_status

**ESTE ARQUIVO NÃO RODA EM PRODUÇÃO.** Conferido em 04/09/2026 nos jobs do
Databricks: quem marca `APLICADA` no ambiente real é o notebook **SQL**
`/Workspace/Users/3vlhugo@ache.com.br/nb_dev_atualiza_renovai_tb_recomendacoes_painel_hist`,
executado pelo `JOB_ATUALIZACAO_RECOMENDACOES_PAINEL` (835351173437850), diário
às 08:02. Este módulo é uma implementação paralela em Python, usada só pelos
testes de `test_ciclo.py`.

Consequência prática, e é a armadilha: **alterar este arquivo não muda o
comportamento de produção.** Quem precisar mexer na detecção de `APLICADA`
mexe no notebook. Foi o que aconteceu em 04/09/2026, quando o status `ACEITA`
entrou: a mudança foi feita lá, não aqui.

Duas diferenças conhecidas em relação ao notebook, mantidas de propósito para
não fingir paridade que não existe:

- o notebook considera `PENDENTE`, `INELEGIVEL` e `ACEITA`; aqui só `PENDENTE`;
- o notebook compara contra o painel real; aqui a lógica é mais simples.

Roda diariamente para verificar recomendações PENDENTE e atualizar status para APLICADA.

Execução manual:
    python -m backend.app.jobs.atualizar_status [--ciclo 202507] [--dry-run]

Lógica:
  ENTRADA_PAINEL PENDENTE → se médico entrou no painel → APLICADA
  REVISAO_PAINEL PENDENTE → se médico saiu do painel  → APLICADA
  Em ambos os casos: registra data_ultima_verificacao
"""
import argparse
import logging

from sqlalchemy import create_engine, text

from backend.app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("renovai.job.atualizar_status")

# Recomendações ENTRADA_PAINEL onde o médico já entrou no painel
_Q_ENTRADA_APLICADAS = """
SELECT rec.id_recomendacao
FROM tb_recomendacoes_painel rec
JOIN tb_painel_medico p
  ON p.ufcrm             = rec.ufcrm
 AND p.setor             = rec.setor
 AND p.ciclo_referencia  = rec.ciclo_referencia
 AND p.ativo             = TRUE
WHERE rec.tipo_recomendacao  = 'ENTRADA_PAINEL'
  AND rec.status_recomendacao = 'PENDENTE'
  AND rec.ciclo_referencia   = :ciclo
"""

# Recomendações REVISAO_PAINEL onde o médico saiu do painel (ativo=FALSE ou ausente)
_Q_REVISAO_APLICADAS = """
SELECT rec.id_recomendacao
FROM tb_recomendacoes_painel rec
LEFT JOIN tb_painel_medico p
  ON p.ufcrm             = rec.ufcrm
 AND p.setor             = rec.setor
 AND p.ciclo_referencia  = rec.ciclo_referencia
 AND p.ativo             = TRUE
WHERE rec.tipo_recomendacao  = 'REVISAO_PAINEL'
  AND rec.status_recomendacao = 'PENDENTE'
  AND rec.ciclo_referencia   = :ciclo
  AND p.ufcrm IS NULL
"""

_Q_MARCAR_APLICADA = """
UPDATE tb_recomendacoes_painel
SET status_recomendacao    = 'APLICADA',
    data_ultima_verificacao = NOW()
WHERE id_recomendacao = ANY(:ids)
"""

_Q_ATUALIZAR_VERIFICACAO = """
UPDATE tb_recomendacoes_painel
SET data_ultima_verificacao = NOW()
WHERE status_recomendacao   = 'PENDENTE'
  AND ciclo_referencia      = :ciclo
"""


def atualizar_status(ciclo: str | None = None, dry_run: bool = False) -> dict:
    settings = get_settings()
    ciclo = ciclo or settings.ciclo_referencia
    engine = create_engine(settings.database_url)

    with engine.connect() as conn:
        ids_entrada = [
            r["id_recomendacao"]
            for r in conn.execute(text(_Q_ENTRADA_APLICADAS), {"ciclo": ciclo}).mappings()
        ]
        ids_revisao = [
            r["id_recomendacao"]
            for r in conn.execute(text(_Q_REVISAO_APLICADAS), {"ciclo": ciclo}).mappings()
        ]

        logger.info(
            "ciclo=%s | ENTRADA→APLICADA: %d | REVISAO→APLICADA: %d",
            ciclo, len(ids_entrada), len(ids_revisao),
        )

        if not dry_run:
            todos_aplicados = ids_entrada + ids_revisao
            if todos_aplicados:
                conn.execute(text(_Q_MARCAR_APLICADA), {"ids": [str(i) for i in todos_aplicados]})
            conn.execute(text(_Q_ATUALIZAR_VERIFICACAO), {"ciclo": ciclo})
            conn.commit()

    return {
        "ciclo": ciclo,
        "dry_run": dry_run,
        "entrada_aplicadas": len(ids_entrada),
        "revisao_aplicadas": len(ids_revisao),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Atualiza status diário das recomendações Ped.AI.")
    parser.add_argument("--ciclo", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(atualizar_status(ciclo=args.ciclo, dry_run=args.dry_run))
