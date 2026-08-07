"""
Schemas Pydantic para os endpoints de recomendações.
Este arquivo é o contrato oficial entre backend e frontend.
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator


class RecomendacaoItem(BaseModel):
    id_recomendacao: UUID
    # Optional: candidatos a ENTRADA_PAINEL ainda fora do painel podem não ter
    # cadastro em nenhuma fonte hoje usada pelo pipeline (ver
    # docs/context/known-issues.md). O router aplica um fallback textual antes
    # de construir este objeto, mas o schema reflete a realidade da fonte.
    nome_medico: Optional[str] = None
    ufcrm: str
    posicao_ranking: Optional[int]
    soma_pontuacao: Optional[float]
    ciclo_referencia: str
    motivo_revisao: Optional[str] = None


class ListaRecomendacoesResponse(BaseModel):
    tipo: str
    total: int
    recomendacoes: list[RecomendacaoItem]


# Lista fixa de motivos de desconsideração (task 161830 — especificação
# oficial do George). "OUTROS" exige motivo_outros_texto e é persistido no
# formato "OUTROS: <texto informado>" — ver _formatar_motivo_desconsideracao
# em routers/recomendacoes.py. Ajustável conforme negócio confirmar novos
# motivos, mas precisa sempre existir uma lista fechada (nunca texto livre
# direto do cliente, exceto dentro de OUTROS).
MOTIVOS_DESCONSIDERACAO = [
    "MEDICO_NAO_ATUA_MAIS",
    "MEDICO_APOSENTADO",
    "MEDICO_FALECIDO",
    "SEM_INTERESSE_COMERCIAL",
    "OUTROS",
]


class DesconsiderarRequest(BaseModel):
    # id_recomendacao vem do path (POST /recomendacoes/{id_recomendacao}/desconsiderar),
    # nunca do corpo. rep_matricula também não faz parte do contrato: a
    # identidade do propagandista vem exclusivamente de resolver_contexto()
    # via token autenticado (task 161830) — nunca aceita do cliente.
    motivo: str
    motivo_outros_texto: Optional[str] = None
    bloquear_novas_recomendacoes: bool

    @field_validator("motivo")
    @classmethod
    def _motivo_valido(cls, v: str) -> str:
        if v not in MOTIVOS_DESCONSIDERACAO:
            raise ValueError(
                f"motivo deve ser um dos valores: {', '.join(MOTIVOS_DESCONSIDERACAO)}"
            )
        return v

    @model_validator(mode="after")
    def _motivo_outros_exige_texto(self) -> "DesconsiderarRequest":
        if self.motivo == "OUTROS" and not (self.motivo_outros_texto and self.motivo_outros_texto.strip()):
            raise ValueError("motivo_outros_texto é obrigatório quando motivo == 'OUTROS'.")
        return self


class DesconsiderarResponse(BaseModel):
    success: bool
    message: str
    id_recomendacao: str
    status_recomendacao: str
    data_desconsideracao: str
