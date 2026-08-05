from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from backend.app.auth.context import resolver_contexto, StatusContexto
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.config import get_settings
from backend.app.db.databricks_connection import get_engine
from backend.app.schemas.recomendacoes import (
    DesconsiderarRequest,
    DesconsiderarResponse,
    ListaRecomendacoesResponse,
    RecomendacaoItem,
)

router = APIRouter()

# Mapeamento tabela/coluna por fonte de dados — ver de-para completo em
# docs/context/databricks-schema-real.md. As chaves de _COLUNAS_POR_FONTE
# são constantes fixas (nunca vêm de input do usuário/request), então
# interpolá-las como identificador SQL via f-string é seguro — os únicos
# valores vindos de fora (matrícula, ciclo, limite) continuam via bind
# param (:mat, :ciclo, :limite).
#
# Nomes de coluna confirmados via execução real (test_recomendacoes_integration.py,
# 2026-07-29): ID_RECOMENDACAO e NOME_MEDICO resolvem sem erro contra
# tb_recomendacoes_painel_historico.
_COLUNAS_POR_FONTE = {
    "databricks": {
        "tabela": "tb_recomendacoes_painel_historico",
        "id_recomendacao": "ID_RECOMENDACAO",
        "rep_matricula": "REP_MATRICULA",
        "nome_medico": "NOME_MEDICO",
        "ufcrm": "UFCRM",
        "tipo_recomendacao": "TIPO_RECOMENDACAO",
        "status_recomendacao": "STATUS_RECOMENDACAO",
        "posicao_ranking": "RANKING_POSICAO_CICLO",
        "soma_pontuacao": "PONTUACAO_CICLO",
        "ciclo_referencia": "CICLO_RECOMENDACAO",
        "motivo_revisao": "MOTIVO_RECOMENDACAO",
        "qtd_medicos_painel_ciclo": "QTD_MEDICOS_PAINEL_CICLO",
    },
    "local": {
        "tabela": "tb_recomendacoes_painel",
        "id_recomendacao": "id_recomendacao",
        "rep_matricula": "rep_matricula",
        "nome_medico": "nome_medico",
        "ufcrm": "ufcrm",
        "tipo_recomendacao": "tipo_recomendacao",
        "status_recomendacao": "status_recomendacao",
        "posicao_ranking": "posicao_ranking",
        "soma_pontuacao": "soma_pontuacao",
        "ciclo_referencia": "ciclo_referencia",
        "motivo_revisao": "motivo_revisao",
        # Não existe no schema local — filtro de defesa em profundidade
        # (painel > 400) fica desativado nessa fonte, ver listar_revisao().
        "qtd_medicos_painel_ciclo": None,
    },
}


def _schema(data_source: str) -> dict:
    return _COLUNAS_POR_FONTE.get(data_source.lower(), _COLUNAS_POR_FONTE["local"])


def _engine():
    return get_engine()


def _aplicar_fallback_nome_medico(row) -> dict:
    """NOME_MEDICO vem nulo da fonte para 100% dos candidatos a ENTRADA_PAINEL
    hoje — médico ainda fora do painel não tem cadastro em nenhuma fonte usada
    pelo pipeline (ver docs/context/known-issues.md, mitigação de backend,
    aguardando fonte de dado da equipe de dados). Aplicado nos dois endpoints
    como defesa em profundidade, mesmo REVISAO_PAINEL não tendo o problema
    hoje. Nunca deixa None chegar ao payload — RecomendacaoItem.nome_medico
    é Optional apenas para refletir a realidade da fonte, não para o cliente
    precisar tratar null."""
    dados = dict(row)
    if not dados.get("nome_medico"):
        dados["nome_medico"] = f"Médico ainda não identificado (UFCRM {dados['ufcrm']})"
    return dados


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
    email: Optional[str] = Query(None),
    ciclo: str = Query(None),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))
    settings = get_settings()
    ciclo = ciclo or settings.ciclo_referencia
    limite = settings.limite_sugestoes
    col = _schema(settings.data_source)

    query = text(f"""
        SELECT {col['id_recomendacao']}  AS id_recomendacao,
               {col['nome_medico']}       AS nome_medico,
               {col['ufcrm']}             AS ufcrm,
               {col['posicao_ranking']}   AS posicao_ranking,
               {col['soma_pontuacao']}    AS soma_pontuacao,
               {col['ciclo_referencia']}  AS ciclo_referencia
        FROM {col['tabela']}
        WHERE {col['rep_matricula']} = :mat
          AND {col['tipo_recomendacao']} = 'ENTRADA_PAINEL'
          AND {col['status_recomendacao']} = 'PENDENTE'
          AND {col['ciclo_referencia']} = :ciclo
        ORDER BY soma_pontuacao DESC NULLS LAST
        LIMIT :limite
    """)

    with _engine().connect() as conn:
        rows = conn.execute(
            query, {"mat": ctx.matricula, "ciclo": ciclo, "limite": limite}
        ).mappings().fetchall()

    items = [RecomendacaoItem(**_aplicar_fallback_nome_medico(r)) for r in rows]
    return ListaRecomendacoesResponse(tipo="ENTRADA_PAINEL", total=len(items), recomendacoes=items)


@router.get("/revisao", response_model=ListaRecomendacoesResponse)
def listar_revisao(
    email: Optional[str] = Query(None),
    ciclo: str = Query(None),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))
    settings = get_settings()
    ciclo = ciclo or settings.ciclo_referencia
    limite = settings.limite_sugestoes
    col = _schema(settings.data_source)

    # Defesa em profundidade (known-issues.md): só aplicável na fonte que tem
    # a coluna. Continua no backend mesmo com a fonte já corrigida, como
    # proteção contra regressão futura.
    filtro_painel_400 = (
        f"AND {col['qtd_medicos_painel_ciclo']} > 400"
        if col["qtd_medicos_painel_ciclo"]
        else ""
    )

    query = text(f"""
        SELECT {col['id_recomendacao']}  AS id_recomendacao,
               {col['nome_medico']}       AS nome_medico,
               {col['ufcrm']}             AS ufcrm,
               {col['posicao_ranking']}   AS posicao_ranking,
               {col['soma_pontuacao']}    AS soma_pontuacao,
               {col['ciclo_referencia']}  AS ciclo_referencia,
               {col['motivo_revisao']}    AS motivo_revisao
        FROM {col['tabela']}
        WHERE {col['rep_matricula']} = :mat
          AND {col['tipo_recomendacao']} = 'REVISAO_PAINEL'
          AND {col['status_recomendacao']} = 'PENDENTE'
          AND {col['ciclo_referencia']} = :ciclo
          {filtro_painel_400}
        ORDER BY posicao_ranking DESC NULLS LAST
        LIMIT :limite
    """)

    with _engine().connect() as conn:
        rows = conn.execute(
            query, {"mat": ctx.matricula, "ciclo": ciclo, "limite": limite}
        ).mappings().fetchall()

    items = [RecomendacaoItem(**_aplicar_fallback_nome_medico(r)) for r in rows]
    return ListaRecomendacoesResponse(tipo="REVISAO_PAINEL", total=len(items), recomendacoes=items)


@router.post("/desconsiderar", response_model=DesconsiderarResponse)
def desconsiderar(
    body: DesconsiderarRequest,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))

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
