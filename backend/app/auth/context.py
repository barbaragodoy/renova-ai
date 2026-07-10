from enum import Enum
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from backend.app.config import get_settings

auth_router = APIRouter()


class StatusContexto(str, Enum):
    SETOR_RESOLVIDO = "SETOR_RESOLVIDO"
    PROPAGANDISTA_NAO_ENCONTRADO = "PROPAGANDISTA_NAO_ENCONTRADO"
    IDENTIDADE_AMBIGUA = "IDENTIDADE_AMBIGUA"


class ContextoResponse(BaseModel):
    status: StatusContexto
    matricula: Optional[str] = None
    setor: Optional[str] = None
    cod_linha: Optional[str] = None
    nome: Optional[str] = None
    mensagem: Optional[str] = None


def _get_engine():
    return create_engine(get_settings().database_url)


def resolver_contexto(email: str) -> ContextoResponse:
    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rep_matricula, setor, cod_linha, rep_nome "
                "FROM tb_propagandistas "
                "WHERE rep_email = :email AND ativo = TRUE"
            ),
            {"email": email},
        ).fetchall()

    if len(rows) == 0:
        return ContextoResponse(
            status=StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO,
            mensagem=(
                "Nenhum propagandista ativo encontrado para este e-mail. "
                "Verifique seu cadastro ou contate o administrador."
            ),
        )

    if len(rows) > 1:
        return ContextoResponse(
            status=StatusContexto.IDENTIDADE_AMBIGUA,
            mensagem=(
                "Mais de um cadastro ativo encontrado para este e-mail. "
                "Contate o administrador para regularizar o cadastro."
            ),
        )

    row = rows[0]
    return ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO,
        matricula=row.rep_matricula,
        setor=row.setor,
        cod_linha=row.cod_linha,
        nome=row.rep_nome,
    )


@auth_router.get("/contexto", response_model=ContextoResponse)
def get_contexto(email: str = Query(..., description="E-mail do usuário autenticado via Auth0")):
    return resolver_contexto(email)
