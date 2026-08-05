from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.app.auth.context import resolver_contexto, StatusContexto
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.genie import nl_to_sql

router = APIRouter()


class ConsultaRequest(BaseModel):
    pergunta: str
    email: Optional[str] = None
    periodo: Optional[str] = None
    perfil_tecnico: bool = False


class ConsultaResponse(BaseModel):
    resposta_texto: str
    sql_gerado: Optional[str] = None
    status: str


_ERRO_HTTP = {
    "GENIE_TIMEOUT": (504, "Timeout na consulta ao motor de análise (GENIE_TIMEOUT)."),
    "GENIE_ERROR": (502, "Erro no motor de análise (GENIE_ERROR)."),
    "EMPTY_RESPONSE": (502, "Motor de análise retornou resposta vazia (EMPTY_RESPONSE)."),
    "CONTEXT_ERROR": (422, "Erro de contexto ao processar a consulta (CONTEXT_ERROR)."),
}


@router.post("/consultar", response_model=ConsultaResponse)
async def consultar_prescricoes(body: ConsultaRequest, authorization: Optional[str] = Header(None)):
    email_autenticado = resolver_email_autenticado(authorization, body.email)
    contexto = resolver_contexto(email_autenticado)
    if contexto.status != StatusContexto.SETOR_RESOLVIDO:
        raise HTTPException(
            status_code=403,
            detail={"status": contexto.status, "mensagem": contexto.mensagem},
        )

    resultado = await nl_to_sql.consultar(
        pergunta=body.pergunta,
        setor=contexto.setor,
        matricula=contexto.matricula,
        periodo=body.periodo,
    )

    status = resultado.get("status", "GENIE_ERROR")
    if status != "OK":
        code, msg = _ERRO_HTTP.get(status, (502, status))
        raise HTTPException(status_code=code, detail={"status": status, "mensagem": msg})

    return ConsultaResponse(
        resposta_texto=resultado["resposta_texto"],
        sql_gerado=resultado["sql_gerado"] if body.perfil_tecnico else None,
        status=status,
    )
