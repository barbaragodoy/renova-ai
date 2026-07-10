from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine, text

from backend.app.auth.context import resolver_contexto, StatusContexto
from backend.app.config import get_settings
from backend.app.schemas.recomendacoes import (
    DesconsiderarRequest,
    DesconsiderarResponse,
    ListaRecomendacoesResponse,
    RecomendacaoItem,
)

router = APIRouter()


def _engine():
    return create_engine(get_settings().database_url)


def _validar_contexto(email: str):
    ctx = resolver_contexto(email)
    if ctx.status != StatusContexto.SETOR_RESOLVIDO:
        raise HTTPException(
            status_code=403,
            detail={"status": ctx.status, "mensagem": ctx.mensagem},
        )
    return ctx


@router.get("/entrada", response_model=ListaRecomendacoesResponse)
def listar_entrada(
    email: str = Query(...),
    ciclo: str = Query(None),
):
    ctx = _validar_contexto(email)
    settings = get_settings()
    ciclo = ciclo or settings.ciclo_referencia
    limite = settings.limite_sugestoes

    with _engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id_recomendacao, nome_medico, ufcrm,
                       posicao_ranking, soma_pontuacao, ciclo_referencia
                FROM tb_recomendacoes_painel
                WHERE rep_matricula = :mat
                  AND tipo_recomendacao = 'ENTRADA_PAINEL'
                  AND status_recomendacao = 'PENDENTE'
                  AND ciclo_referencia = :ciclo
                ORDER BY soma_pontuacao DESC NULLS LAST
                LIMIT :limite
            """),
            {"mat": ctx.matricula, "ciclo": ciclo, "limite": limite},
        ).mappings().fetchall()

    items = [RecomendacaoItem(**dict(r)) for r in rows]
    return ListaRecomendacoesResponse(tipo="ENTRADA_PAINEL", total=len(items), recomendacoes=items)


@router.get("/revisao", response_model=ListaRecomendacoesResponse)
def listar_revisao(
    email: str = Query(...),
    ciclo: str = Query(None),
):
    ctx = _validar_contexto(email)
    settings = get_settings()
    ciclo = ciclo or settings.ciclo_referencia
    limite = settings.limite_sugestoes

    with _engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id_recomendacao, nome_medico, ufcrm,
                       posicao_ranking, soma_pontuacao, ciclo_referencia,
                       motivo_revisao
                FROM tb_recomendacoes_painel
                WHERE rep_matricula = :mat
                  AND tipo_recomendacao = 'REVISAO_PAINEL'
                  AND status_recomendacao = 'PENDENTE'
                  AND ciclo_referencia = :ciclo
                ORDER BY soma_pontuacao DESC NULLS LAST
                LIMIT :limite
            """),
            {"mat": ctx.matricula, "ciclo": ciclo, "limite": limite},
        ).mappings().fetchall()

    items = [RecomendacaoItem(**dict(r)) for r in rows]
    return ListaRecomendacoesResponse(tipo="REVISAO_PAINEL", total=len(items), recomendacoes=items)


@router.post("/desconsiderar", response_model=DesconsiderarResponse)
def desconsiderar(body: DesconsiderarRequest, email: str = Query(...)):
    ctx = _validar_contexto(email)

    with _engine().connect() as conn:
        row = conn.execute(
            text("""
                SELECT rep_matricula, status_recomendacao
                FROM tb_recomendacoes_painel
                WHERE id_recomendacao = :id
            """),
            {"id": str(body.id_recomendacao)},
        ).mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Recomendação não encontrada.")

    if row["rep_matricula"] != ctx.matricula:
        raise HTTPException(status_code=403, detail="Recomendação não pertence a este propagandista.")

    status_atual = row["status_recomendacao"]
    if status_atual == "DESCONSIDERADA":
        raise HTTPException(status_code=409, detail="Recomendação já foi desconsiderada.")
    if status_atual != "PENDENTE":
        raise HTTPException(
            status_code=409,
            detail=f"Não é possível desconsiderar uma recomendação com status '{status_atual}'.",
        )

    with _engine().connect() as conn:
        conn.execute(
            text("""
                UPDATE tb_recomendacoes_painel
                SET status_recomendacao        = 'DESCONSIDERADA',
                    motivo_desconsideracao     = :motivo,
                    timestamp_desconsideracao  = :ts,
                    rep_matricula_desconsiderou = :mat
                WHERE id_recomendacao = :id
            """),
            {
                "motivo": body.motivo,
                "ts": body.timestamp,
                "mat": ctx.matricula,
                "id": str(body.id_recomendacao),
            },
        )
        conn.commit()

    return DesconsiderarResponse(sucesso=True, mensagem="Recomendação desconsiderada com sucesso.")
