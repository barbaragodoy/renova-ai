"""
Schemas Pydantic para endpoints gerenciais (visão GD).
Contrato oficial: GD consulta; nenhum endpoint gerencial aceita escrita.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class IndicadoresGD(BaseModel):
    gd_matricula: str
    gd_nome: str
    ciclo_referencia: str
    total_gerado: int
    total_pendente: int
    total_aplicado: int
    total_desconsiderado: int
    total_expirado: int
    taxa_aceite_pct: Optional[float]


class PropagandistaSummary(BaseModel):
    rep_matricula: str
    rep_nome: str
    setor: str
    cod_linha: str
    total_pendente: int
    total_aplicado: int
    total_desconsiderado: int


class RecomendacaoGerencial(BaseModel):
    id_recomendacao: UUID
    rep_matricula: str
    rep_nome: str
    ufcrm: str
    nome_medico: str
    tipo_recomendacao: str
    status_recomendacao: str
    posicao_ranking: Optional[int]
    soma_pontuacao: Optional[float]
    motivo_revisao: Optional[str]
    justificativa_texto: Optional[str]
    motivo_desconsideracao: Optional[str] = None
    ciclo_referencia: str
    data_geracao: datetime
    qtd_vezes_recomendado: int
