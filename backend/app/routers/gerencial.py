"""
Router gerencial — acesso exclusivo de GDs ao painel de indicadores.
Regras de acesso (BARBARA-10):
  - GD acessa apenas propagandistas do seu escopo via tb_hierarquia_gd
  - Tentativa de acessar fora do escopo retorna 403
  - Nenhum endpoint aceita POST, PUT ou PATCH
  - motivo_desconsideracao retornado apenas para GD autenticado
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine, text

from backend.app.config import get_settings
from backend.app.schemas.gerencial import (
    IndicadoresGD,
    PropagandistaSummary,
    RecomendacaoGerencial,
)

router = APIRouter()


def _engine():
    return create_engine(get_settings().database_url)


def _resolver_gd(gd_email: str) -> dict:
    """Retorna dados do GD ou lança 403 se não encontrado."""
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT DISTINCT gd_matricula, gd_nome "
                "FROM tb_hierarquia_gd WHERE gd_email = :email LIMIT 1"
            ),
            {"email": gd_email},
        ).mappings().fetchone()
    if row is None:
        raise HTTPException(status_code=403, detail="GD não encontrado ou sem escopo cadastrado.")
    return dict(row)


def _validar_rep_no_escopo(gd_matricula: str, rep_matricula: str):
    with _engine().connect() as conn:
        existe = conn.execute(
            text(
                "SELECT 1 FROM tb_hierarquia_gd "
                "WHERE gd_matricula = :gd AND rep_matricula = :rep LIMIT 1"
            ),
            {"gd": gd_matricula, "rep": rep_matricula},
        ).scalar()
    if not existe:
        raise HTTPException(
            status_code=403,
            detail="Propagandista fora do escopo deste GD.",
        )


@router.get("/indicadores", response_model=list[IndicadoresGD])
def indicadores(
    gd_email: str = Query(..., description="E-mail do GD autenticado"),
    ciclo: str = Query(None),
):
    gd = _resolver_gd(gd_email)
    ciclo = ciclo or get_settings().ciclo_referencia

    with _engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    :gd_matricula                                              AS gd_matricula,
                    :gd_nome                                                   AS gd_nome,
                    rec.ciclo_referencia,
                    COUNT(*)                                                   AS total_gerado,
                    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'PENDENTE')       AS total_pendente,
                    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'APLICADA')       AS total_aplicado,
                    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'DESCONSIDERADA') AS total_desconsiderado,
                    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'EXPIRADA')       AS total_expirado,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE rec.status_recomendacao = 'APLICADA')
                        / NULLIF(COUNT(*), 0), 1
                    )                                                          AS taxa_aceite_pct
                FROM tb_recomendacoes_painel rec
                WHERE rec.rep_matricula IN (
                    SELECT rep_matricula FROM tb_hierarquia_gd WHERE gd_matricula = :gd_matricula
                )
                  AND rec.ciclo_referencia = :ciclo
                GROUP BY rec.ciclo_referencia
            """),
            {"gd_matricula": gd["gd_matricula"], "gd_nome": gd["gd_nome"], "ciclo": ciclo},
        ).mappings().fetchall()

    return [IndicadoresGD(**dict(r)) for r in rows]


@router.get("/propagandistas", response_model=list[PropagandistaSummary])
def propagandistas(
    gd_email: str = Query(...),
    ciclo: str = Query(None),
):
    gd = _resolver_gd(gd_email)
    ciclo = ciclo or get_settings().ciclo_referencia

    with _engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    p.rep_matricula,
                    p.rep_nome,
                    p.setor,
                    p.cod_linha,
                    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'PENDENTE')       AS total_pendente,
                    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'APLICADA')       AS total_aplicado,
                    COUNT(*) FILTER (WHERE rec.status_recomendacao = 'DESCONSIDERADA') AS total_desconsiderado
                FROM tb_propagandistas p
                JOIN tb_hierarquia_gd h ON h.rep_matricula = p.rep_matricula
                LEFT JOIN tb_recomendacoes_painel rec
                       ON rec.rep_matricula    = p.rep_matricula
                      AND rec.ciclo_referencia = :ciclo
                WHERE h.gd_matricula = :gd_matricula
                  AND p.ativo = TRUE
                GROUP BY p.rep_matricula, p.rep_nome, p.setor, p.cod_linha
                ORDER BY total_pendente DESC
            """),
            {"gd_matricula": gd["gd_matricula"], "ciclo": ciclo},
        ).mappings().fetchall()

    return [PropagandistaSummary(**dict(r)) for r in rows]


@router.get("/recomendacoes", response_model=list[RecomendacaoGerencial])
def recomendacoes_gerencial(
    gd_email: str = Query(...),
    matricula: str = Query(..., description="Matrícula do propagandista a consultar"),
    ciclo: str = Query(None),
    tipo: Optional[str] = Query(None, description="ENTRADA_PAINEL | REVISAO_PAINEL"),
    status: Optional[str] = Query(None, description="PENDENTE | APLICADA | DESCONSIDERADA | EXPIRADA"),
):
    gd = _resolver_gd(gd_email)
    _validar_rep_no_escopo(gd["gd_matricula"], matricula)
    ciclo = ciclo or get_settings().ciclo_referencia

    filtros = "WHERE rec.rep_matricula = :mat AND rec.ciclo_referencia = :ciclo"
    params: dict = {"mat": matricula, "ciclo": ciclo}
    if tipo:
        filtros += " AND rec.tipo_recomendacao = :tipo"
        params["tipo"] = tipo
    if status:
        filtros += " AND rec.status_recomendacao = :status"
        params["status"] = status

    with _engine().connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT
                    rec.id_recomendacao, rec.rep_matricula,
                    p.rep_nome,
                    rec.ufcrm, rec.nome_medico,
                    rec.tipo_recomendacao, rec.status_recomendacao,
                    rec.posicao_ranking, rec.soma_pontuacao,
                    rec.motivo_revisao, rec.justificativa_texto,
                    rec.motivo_desconsideracao,
                    rec.ciclo_referencia, rec.data_geracao,
                    rec.qtd_vezes_recomendado
                FROM tb_recomendacoes_painel rec
                JOIN tb_propagandistas p ON p.rep_matricula = rec.rep_matricula
                {filtros}
                ORDER BY rec.soma_pontuacao DESC NULLS LAST
            """),
            params,
        ).mappings().fetchall()

    return [RecomendacaoGerencial(**dict(r)) for r in rows]
