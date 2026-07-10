"""
Schemas Pydantic para os endpoints de recomendações.
Este arquivo é o contrato oficial entre backend e frontend.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class RecomendacaoItem(BaseModel):
    id_recomendacao: UUID
    nome_medico: str
    ufcrm: str
    posicao_ranking: Optional[int]
    soma_pontuacao: Optional[float]
    ciclo_referencia: str
    motivo_revisao: Optional[str] = None


class ListaRecomendacoesResponse(BaseModel):
    tipo: str
    total: int
    recomendacoes: list[RecomendacaoItem]


class DesconsiderarRequest(BaseModel):
    id_recomendacao: UUID
    rep_matricula: str
    motivo: str
    timestamp: datetime


class DesconsiderarResponse(BaseModel):
    sucesso: bool
    mensagem: str
