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
    # Quantas recomendações pendentes existem no ciclo, e não quantas vieram
    # nesta página. Até 04/09/2026 a lista era cortada em 5 e este campo
    # devolvia 5, então a tela não tinha como saber que existia mais.
    total: int
    recomendacoes: list[RecomendacaoItem]
    # Quantas devem aparecer destacadas como prioridade da semana. Vem do
    # backend para a tela não repetir a regra: se o número mudar, muda num
    # lugar só.
    destaques: int = 0


# Lista fixa de motivos de desconsideração. Origem: protótipo do Figma Make
# `cuZGbZpvR0aBJhixqBnYYB`, adotado por decisão de George em 04/09/2026 no lugar
# da lista da task 161830. "OUTROS" exige motivo_outros_texto e é persistido no
# formato "OUTROS: <texto informado>" — ver _formatar_motivo_desconsideracao
# em routers/recomendacoes.py. Precisa sempre existir uma lista fechada (nunca
# texto livre direto do cliente, exceto dentro de OUTROS).
MOTIVOS_DESCONSIDERACAO = [
    "SEM_PERFIL_PARA_O_PAINEL",
    "TRABALHADO_POR_OUTRO_CANAL",
    "AGUARDAR_PROXIMO_CICLO",
    "DADOS_DESATUALIZADOS",
    "FORA_DO_PLANEJAMENTO",
    "OUTROS",
]

# Motivos aceitos até 04/09/2026, quando a lista passou a ser a do protótipo do
# Figma Make por decisão de George. Não entram mais em gravação nova: falavam do
# médico (faleceu, aposentou) e não da decisão de quem desconsidera, que é o que
# o negócio quer medir. Continuam listados porque as linhas já gravadas guardam
# esses códigos e a aba Arquivadas precisa saber traduzi-los.
MOTIVOS_DESCONSIDERACAO_HISTORICOS = [
    "MEDICO_NAO_ATUA_MAIS",
    "MEDICO_APOSENTADO",
    "MEDICO_FALECIDO",
    "SEM_INTERESSE_COMERCIAL",
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


class AceitarResponse(BaseModel):
    """Resposta do aceite da recomendação.

    Sem corpo de requisição: aceitar não tem parâmetro. O que muda é só o
    estado, e a identidade de quem aceitou vem do token, nunca do cliente,
    pela mesma regra do desconsiderar.
    """
    success: bool
    message: str
    id_recomendacao: str
    status_recomendacao: str
    data_aceite: str


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
    # Optional desde 04/09/2026: a aba virou Histórico e mostra também as
    # aceitas, que não têm motivo de desconsideração. Sem isto o endpoint
    # devolvia 500 na primeira recomendação aceita do propagandista.
    motivo_desconsideracao: Optional[str] = None
    # Optional: a coluna real permite NULL de propósito ("NULL = sem
    # decisão", ver comentário da coluna em data/scripts/01_create_tables.sql
    # e databricks-schema-real.md) — confirmado em teste de ponta a ponta
    # (14/08/2026) que registros legados (anteriores à obrigatoriedade deste
    # campo no contrato de POST /desconsiderar) têm esse valor NULL, e
    # quebravam GET /desconsideradas com 500 quando o schema exigia bool.
    bloquear_novas_recomendacoes: Optional[bool] = None
    # Qual foi a decisão: DESCONSIDERADA ou ACEITA. A aba Histórico passou a
    # mostrar as duas em 04/09/2026.
    status_recomendacao: Optional[str] = None
    # Optional desde 04/09/2026: uma recomendação aceita não tem data de
    # desconsideração. Quem quiser a data da decisão usa `data_decisao`.
    data_desconsideracao: Optional[datetime] = None
    # A data da decisão, seja ela qual for. Existe para a tela ordenar e
    # exibir sem precisar saber de qual coluna veio.
    data_decisao: Optional[datetime] = None
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
