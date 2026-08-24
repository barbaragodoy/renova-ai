"""
Schemas Pydantic para os endpoints de recomendações.
Este arquivo é o contrato oficial entre backend e frontend.
"""
from datetime import datetime
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
    # Via LEFT JOIN com tb_dim_medicos (só existe no Databricks — sem
    # equivalente no Postgres local, ver known-issues.md). uf é calculado
    # nos dois lados (LEFT(ufcrm, 2)), sem depender do espelho. Optional
    # porque: no local sempre é None; mesmo no Databricks o LEFT JOIN pode
    # não casar para todo ufcrm.
    especialidade: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    # Só calculado quando tipo_recomendacao == REVISAO_PAINEL (não faz
    # sentido semântico para ENTRADA_PAINEL). None no Postgres local (sem
    # coluna equivalente a DATA_ULTIMA_VISITA_CONSIDERADA).
    meses_sem_visita: Optional[int] = None


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


class DesconsideradaItem(BaseModel):
    id_recomendacao: UUID
    # Mesmo fallback de /entrada e /revisao (_aplicar_fallback_nome_medico) —
    # ver known-issues.md.
    nome_medico: Optional[str] = None
    ufcrm: str
    tipo_recomendacao: str
    # Motivo original da recomendação (não o motivo da desconsideração) —
    # coluna `motivo_revisao` no mapeamento de schema, nula para
    # ENTRADA_PAINEL histórico.
    motivo_recomendacao: Optional[str] = None
    motivo_desconsideracao: str
    # Optional: a coluna real permite NULL de propósito ("NULL = sem
    # decisão", ver comentário da coluna em data/scripts/01_create_tables.sql
    # e databricks-schema-real.md) — confirmado em teste de ponta a ponta
    # (14/08/2026) que registros legados (anteriores à obrigatoriedade deste
    # campo no contrato de POST /desconsiderar) têm esse valor NULL, e
    # quebravam GET /desconsideradas com 500 quando o schema exigia bool.
    bloquear_novas_recomendacoes: Optional[bool] = None
    data_desconsideracao: datetime
    ciclo_recomendacao: str
    # Mesmo tratamento de RecomendacaoItem — ver comentário lá.
    especialidade: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    meses_sem_visita: Optional[int] = None


class ListaDesconsideradasResponse(BaseModel):
    total: int
    recomendacoes: list[DesconsideradaItem]


class ReverterResponse(BaseModel):
    success: bool
    message: str
    id_recomendacao: str
    status_recomendacao: str
