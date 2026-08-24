from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from backend.app.auth.context import resolver_contexto, StatusContexto
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.config import get_settings
from backend.app.db.databricks_connection import get_engine
from backend.app.schemas.recomendacoes import (
    DesconsideradaItem,
    DesconsiderarRequest,
    DesconsiderarResponse,
    ListaDesconsideradasResponse,
    ListaRecomendacoesResponse,
    RecomendacaoItem,
    ReverterResponse,
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
        # Colunas de desconsideração (task 161830/163626) — AINDA NÃO existem
        # na tabela real, pendência formal com o Hugo (ver
        # docs/context/known-issues.md). Mapeadas aqui como de-para de nomes
        # pronto para quando as colunas forem criadas, mesmo padrão já usado
        # nas colunas de leitura acima (BARBARA-04/05).
        "motivo_desconsideracao": "MOTIVO_DESCONSIDERACAO",
        "desconsiderado_por": "DESCONSIDERADO_POR",
        "data_desconsideracao": "DATA_DESCONSIDERACAO",
        "qtd_vezes_desconsiderado": "QTD_VEZES_DESCONSIDERADO",
        "bloquear_novas_recomendacoes": "BLOQUEAR_NOVAS_RECOMENDACOES",
        # LEFT JOIN com tb_dim_medicos (espelho local do Databricks, ver
        # known-issues.md — "RESOLVIDO POR VIA ALTERNATIVA") — só existe
        # nesta fonte, sem equivalente no Postgres local.
        "tabela_dim_medicos": "tb_dim_medicos",
        "especialidade": "dm.especialidade",
        "cidade": "dm.cidade",
        "data_ultima_visita_considerada": "DATA_ULTIMA_VISITA_CONSIDERADA",
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
        "motivo_desconsideracao": "motivo_desconsideracao",
        "desconsiderado_por": "desconsiderado_por",
        "data_desconsideracao": "data_desconsideracao",
        "qtd_vezes_desconsiderado": "qtd_vezes_desconsiderado",
        "bloquear_novas_recomendacoes": "bloquear_novas_recomendacoes",
        # Sem tabela equivalente a tb_dim_medicos nem coluna equivalente a
        # DATA_ULTIMA_VISITA_CONSIDERADA no Postgres local — especialidade,
        # cidade e meses_sem_visita ficam sempre None nessa fonte.
        "tabela_dim_medicos": None,
        "especialidade": None,
        "cidade": None,
        "data_ultima_visita_considerada": None,
    },
}


def _schema(data_source: str) -> dict:
    return _COLUNAS_POR_FONTE.get(data_source.lower(), _COLUNAS_POR_FONTE["local"])


def _engine():
    return get_engine()


def _ciclo_mais_recente(col: dict) -> str:
    """Resolve o ciclo mais recente disponível na própria tabela via
    MAX(ciclo_referencia), substituindo o default estático
    settings.ciclo_referencia — que fica obsoleto a cada rollover mensal de
    ciclo (ver docs/context/known-issues.md). Só é chamada quando o
    chamador não passa ?ciclo= explícito; a consulta a um ciclo específico
    (usada por test_recomendacoes_integration.py e documentada no README)
    continua funcionando normalmente."""
    with _engine().connect() as conn:
        row = conn.execute(
            text(f"SELECT MAX({col['ciclo_referencia']}) AS ciclo FROM {col['tabela']}")
        ).fetchone()
    return row.ciclo


def _fragmentos_dim_medicos(col: dict) -> dict:
    """Monta os fragmentos SQL condicionais do LEFT JOIN com
    tb_dim_medicos (só existe no Databricks — espelho local criado pelo
    George para contornar bloqueio de USE CATALOG cruzado, ver
    known-issues.md, "RESOLVIDO POR VIA ALTERNATIVA"). Retorna strings
    vazias quando a fonte não suporta (Postgres local), para o SQL
    continuar válido sem o JOIN nem as colunas.

    uf não faz parte daqui: é calculado como LEFT(ufcrm, 2) direto na
    query, funciona nas duas fontes sem depender do espelho.
    """
    return {
        "join": (
            f"LEFT JOIN {col['tabela_dim_medicos']} dm "
            f"ON {col['tabela']}.{col['ufcrm']} = dm.ufcrm"
            if col.get("tabela_dim_medicos")
            else ""
        ),
        "especialidade": (
            f", {col['especialidade']} AS especialidade"
            if col.get("especialidade")
            else ""
        ),
        "cidade": (
            f", {col['cidade']} AS cidade"
            if col.get("cidade")
            else ""
        ),
    }


def _fragmento_meses_sem_visita(col: dict, condicional: bool) -> str:
    """Fragmento SQL do cálculo de meses_sem_visita — só existe no
    Databricks, via DATA_ULTIMA_VISITA_CONSIDERADA (confirmada na tabela
    real). A forma muda conforme o endpoint, porque a regra de negócio é
    genuinamente diferente entre eles:

    - condicional=False (usado em /revisao): cálculo direto, sem CASE — o
      endpoint já filtra tipo_recomendacao = 'REVISAO_PAINEL' para a query
      inteira, então toda linha retornada já é elegível.
    - condicional=True (usado em /desconsideradas): envolve em
      CASE WHEN tipo_recomendacao = 'REVISAO_PAINEL', porque essa lista
      mistura ENTRADA_PAINEL e REVISAO_PAINEL na mesma consulta.

    Nunca chamado em /entrada: lá o tipo é sempre ENTRADA_PAINEL, para o
    qual meses_sem_visita não tem sentido semântico — médico que nunca
    esteve no painel não ter visita não é sinal de negligência, é o estado
    normal de quem nunca esteve lá.
    """
    if not col.get("data_ultima_visita_considerada"):
        return ""
    calculo = (
        f"CAST(months_between("
        f"to_date({col['ciclo_referencia']}, 'yyyyMM'), "
        f"trunc({col['data_ultima_visita_considerada']}, 'MM')"
        f") AS INT)"
    )
    if condicional:
        return (
            f", CASE WHEN {col['tipo_recomendacao']} = 'REVISAO_PAINEL' "
            f"THEN {calculo} ELSE NULL END AS meses_sem_visita"
        )
    return f", {calculo} AS meses_sem_visita"


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
    limite = settings.limite_sugestoes
    col = _schema(settings.data_source)
    ciclo = ciclo or _ciclo_mais_recente(col)
    dm = _fragmentos_dim_medicos(col)

    query = text(f"""
        SELECT {col['id_recomendacao']}  AS id_recomendacao,
               {col['nome_medico']}       AS nome_medico,
               {col['tabela']}.{col['ufcrm']} AS ufcrm,
               {col['posicao_ranking']}   AS posicao_ranking,
               {col['soma_pontuacao']}    AS soma_pontuacao,
               {col['ciclo_referencia']}  AS ciclo_referencia,
               LEFT({col['tabela']}.{col['ufcrm']}, 2) AS uf
               {dm['especialidade']}
               {dm['cidade']}
        FROM {col['tabela']}
        {dm['join']}
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
    limite = settings.limite_sugestoes
    col = _schema(settings.data_source)
    ciclo = ciclo or _ciclo_mais_recente(col)
    dm = _fragmentos_dim_medicos(col)
    meses_sem_visita = _fragmento_meses_sem_visita(col, condicional=False)

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
               {col['tabela']}.{col['ufcrm']} AS ufcrm,
               {col['posicao_ranking']}   AS posicao_ranking,
               {col['soma_pontuacao']}    AS soma_pontuacao,
               {col['ciclo_referencia']}  AS ciclo_referencia,
               {col['motivo_revisao']}    AS motivo_revisao,
               LEFT({col['tabela']}.{col['ufcrm']}, 2) AS uf
               {dm['especialidade']}
               {dm['cidade']}
               {meses_sem_visita}
        FROM {col['tabela']}
        {dm['join']}
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


def _formatar_motivo_desconsideracao(motivo: str, motivo_outros_texto: Optional[str]) -> str:
    if motivo == "OUTROS":
        return f"OUTROS: {motivo_outros_texto}"
    return motivo


@router.post("/{id_recomendacao}/desconsiderar", response_model=DesconsiderarResponse)
def desconsiderar(
    id_recomendacao: UUID,
    body: DesconsiderarRequest,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """POST /recomendacoes/{id_recomendacao}/desconsiderar — task 161830/163626.

    Identidade sempre via resolver_contexto() (nunca aceita matrícula do
    corpo). ID_RECOMENDACAO sempre do path, nunca do corpo. Data/hora de
    desconsideração sempre gerada aqui no backend, nunca aceita do cliente.
    """
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))
    settings = get_settings()
    col = _schema(settings.data_source)
    id_str = str(id_recomendacao)

    with _engine().connect() as conn:
        row = conn.execute(
            text(f"""
                SELECT {col['rep_matricula']}       AS rep_matricula,
                       {col['status_recomendacao']} AS status_recomendacao
                FROM {col['tabela']}
                WHERE {col['id_recomendacao']} = :id
            """),
            {"id": id_str},
        ).mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Recomendação não encontrada.")

    # Mensagem genérica: não revela status/detalhe de recomendação de terceiro.
    if row["rep_matricula"] != ctx.matricula:
        raise HTTPException(status_code=403, detail="Não autorizado a desconsiderar esta recomendação.")

    status_atual = row["status_recomendacao"]
    if status_atual == "DESCONSIDERADA":
        raise HTTPException(status_code=409, detail="Recomendação já foi desconsiderada.")
    if status_atual != "PENDENTE":
        raise HTTPException(
            status_code=400,
            detail=f"Recomendação em estado incompatível para desconsideração: '{status_atual}'.",
        )

    motivo_formatado = _formatar_motivo_desconsideracao(body.motivo, body.motivo_outros_texto)
    agora = datetime.now(timezone.utc)

    # UPDATE atômico: o WHERE repete status_recomendacao = 'PENDENTE' (mesma
    # condição já checada acima) para garantir que, sob concorrência, só uma
    # das requisições simultâneas efetivamente grava — a outra recebe
    # rowcount == 0 e é tratada como 409 abaixo, sem precisar de lock explícito.
    with _engine().connect() as conn:
        resultado = conn.execute(
            text(f"""
                UPDATE {col['tabela']}
                SET {col['status_recomendacao']}         = 'DESCONSIDERADA',
                    {col['motivo_desconsideracao']}       = :motivo,
                    {col['desconsiderado_por']}           = :mat,
                    {col['data_desconsideracao']}         = :agora,
                    {col['bloquear_novas_recomendacoes']} = :bloquear,
                    {col['qtd_vezes_desconsiderado']}     = COALESCE({col['qtd_vezes_desconsiderado']}, 0) + 1
                WHERE {col['id_recomendacao']} = :id
                  AND {col['status_recomendacao']} = 'PENDENTE'
            """),
            {
                "motivo": motivo_formatado,
                "mat": ctx.matricula,
                "agora": agora,
                "bloquear": body.bloquear_novas_recomendacoes,
                "id": id_str,
            },
        )
        conn.commit()

    if resultado.rowcount == 0:
        raise HTTPException(status_code=409, detail="Recomendação já foi desconsiderada.")

    return DesconsiderarResponse(
        success=True,
        message="Recomendação desconsiderada com sucesso.",
        id_recomendacao=id_str,
        status_recomendacao="DESCONSIDERADA",
        data_desconsideracao=agora.isoformat(),
    )


@router.get("/desconsideradas", response_model=ListaDesconsideradasResponse)
def listar_desconsideradas(
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """GET /recomendacoes/desconsideradas — aba Arquivadas (consulta).

    Histórico completo (sem LIMIT, diferente de /entrada e /revisao, que
    limitam a `settings.limite_sugestoes` por serem sugestões priorizadas)
    das recomendações que o propagandista autenticado já desconsiderou,
    mais recente primeiro.
    """
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))
    settings = get_settings()
    col = _schema(settings.data_source)
    dm = _fragmentos_dim_medicos(col)
    meses_sem_visita = _fragmento_meses_sem_visita(col, condicional=True)

    query = text(f"""
        SELECT {col['id_recomendacao']}              AS id_recomendacao,
               {col['nome_medico']}                   AS nome_medico,
               {col['tabela']}.{col['ufcrm']}          AS ufcrm,
               {col['tipo_recomendacao']}              AS tipo_recomendacao,
               {col['motivo_revisao']}                  AS motivo_recomendacao,
               {col['motivo_desconsideracao']}           AS motivo_desconsideracao,
               {col['bloquear_novas_recomendacoes']}     AS bloquear_novas_recomendacoes,
               {col['data_desconsideracao']}             AS data_desconsideracao,
               {col['ciclo_referencia']}                 AS ciclo_recomendacao,
               LEFT({col['tabela']}.{col['ufcrm']}, 2) AS uf
               {dm['especialidade']}
               {dm['cidade']}
               {meses_sem_visita}
        FROM {col['tabela']}
        {dm['join']}
        WHERE {col['rep_matricula']} = :mat
          AND {col['status_recomendacao']} = 'DESCONSIDERADA'
        ORDER BY {col['data_desconsideracao']} DESC
    """)

    with _engine().connect() as conn:
        rows = conn.execute(query, {"mat": ctx.matricula}).mappings().fetchall()

    items = [DesconsideradaItem(**_aplicar_fallback_nome_medico(r)) for r in rows]
    return ListaDesconsideradasResponse(total=len(items), recomendacoes=items)


@router.post("/{id_recomendacao}/reverter", response_model=ReverterResponse)
def reverter(
    id_recomendacao: UUID,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """POST /recomendacoes/{id_recomendacao}/reverter — aba Arquivadas (reversão).

    Sem payload no corpo. Reverte uma recomendação DESCONSIDERADA: volta a
    PENDENTE se o ciclo da recomendação ainda é o mais recente
    (_ciclo_mais_recente(), mesma lógica de /entrada e /revisao), ou EXPIRADA
    se já é de um ciclo anterior. Limpa motivo_desconsideracao,
    desconsiderado_por, bloquear_novas_recomendacoes e data_desconsideracao
    (voltam a NULL) — mas mantém qtd_vezes_desconsiderado como histórico
    acumulado, mesmo após a reversão.
    """
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))
    settings = get_settings()
    col = _schema(settings.data_source)
    id_str = str(id_recomendacao)

    with _engine().connect() as conn:
        row = conn.execute(
            text(f"""
                SELECT {col['rep_matricula']}       AS rep_matricula,
                       {col['status_recomendacao']} AS status_recomendacao,
                       {col['ciclo_referencia']}     AS ciclo_referencia
                FROM {col['tabela']}
                WHERE {col['id_recomendacao']} = :id
            """),
            {"id": id_str},
        ).mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Recomendação não encontrada.")

    # Mensagem genérica: não revela status/detalhe de recomendação de terceiro.
    if row["rep_matricula"] != ctx.matricula:
        raise HTTPException(status_code=403, detail="Não autorizado a reverter esta recomendação.")

    if row["status_recomendacao"] != "DESCONSIDERADA":
        raise HTTPException(
            status_code=400,
            detail=f"Recomendação em estado incompatível para reversão: '{row['status_recomendacao']}'.",
        )

    ciclo_atual = _ciclo_mais_recente(col)
    novo_status = "PENDENTE" if row["ciclo_referencia"] == ciclo_atual else "EXPIRADA"

    # UPDATE atômico: o WHERE repete status_recomendacao = 'DESCONSIDERADA'
    # (mesma condição já checada acima) para garantir que, sob concorrência,
    # só uma das requisições simultâneas efetivamente grava — a outra recebe
    # rowcount == 0 e é tratada como 400 abaixo, sem precisar de lock
    # explícito. qtd_vezes_desconsiderado propositalmente NÃO é tocado.
    with _engine().connect() as conn:
        resultado = conn.execute(
            text(f"""
                UPDATE {col['tabela']}
                SET {col['status_recomendacao']}         = :novo_status,
                    {col['motivo_desconsideracao']}       = NULL,
                    {col['desconsiderado_por']}           = NULL,
                    {col['bloquear_novas_recomendacoes']} = NULL,
                    {col['data_desconsideracao']}         = NULL
                WHERE {col['id_recomendacao']} = :id
                  AND {col['status_recomendacao']} = 'DESCONSIDERADA'
            """),
            {"novo_status": novo_status, "id": id_str},
        )
        conn.commit()

    if resultado.rowcount == 0:
        raise HTTPException(
            status_code=400,
            detail="Recomendação não está mais em estado 'DESCONSIDERADA' (alterada por outra requisição).",
        )

    return ReverterResponse(
        success=True,
        message=f"Recomendação {id_str} revertida com sucesso.",
        id_recomendacao=id_str,
        status_recomendacao=novo_status,
    )
