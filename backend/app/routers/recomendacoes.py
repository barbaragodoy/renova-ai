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
    AceitarResponse,
    DesconsideradaItem,
    DesconsiderarRequest,
    DesconsiderarResponse,
    ListaDesconsideradasResponse,
    ListaRecomendacoesResponse,
    RecomendacaoItem,
    ReverterResponse,
)

router = APIRouter()

# Mesma página do Ranking. A lista deixou de ser cortada em 5 por decisão de
# George em 04/09/2026, e sem paginação a tela receberia até 629 cards de uma
# vez, que é o máximo medido por pessoa e tipo no ciclo atual.
_LIMITE_PAGINA = 50

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
        # Sprint 6 — limite por propagandista (substitui o corte fixo de
        # 400). tb_perfil_portal já existe na fonte real (usada por
        # auth/perfil.py para NOME_EXIBICAO/FOTO_PATH desde antes desta
        # task); aqui só o de-para das colunas de limite, mesmo padrão
        # LEFT JOIN ON REP_MATRICULA confirmado pelo Hugo.
        "tabela_perfil_portal": "tb_perfil_portal",
        "limite_painel": "LIMITE_PAINEL",
        # tb_renovai_parametros — criada pelo George em 26/08/2026, fonte
        # única do LIMITE_PAINEL_PADRAO (318 confirmado via DESCRIBE/SELECT
        # reais). Substitui o literal 318 hardcoded que existia aqui antes
        # (ver docs/context/decisions-log.md, entrada de 26/08/2026).
        "tabela_parametros": "tb_renovai_parametros",
        "limite_painel_padrao": "LIMITE_PAINEL_PADRAO",
        # Colunas de desconsideração (task 161830/163626). A pendência com o
        # Hugo foi resolvida: conferido por DESCRIBE em 04/09/2026 que as cinco
        # existem em acheinfo_dev.renovai.tb_recomendacoes_painel_historico.
        "motivo_desconsideracao": "MOTIVO_DESCONSIDERACAO",
        "desconsiderado_por": "DESCONSIDERADO_POR",
        "data_desconsideracao": "DATA_DESCONSIDERACAO",
        "qtd_vezes_desconsiderado": "QTD_VEZES_DESCONSIDERADO",
        "bloquear_novas_recomendacoes": "BLOQUEAR_NOVAS_RECOMENDACOES",
        # Colunas do aceite, criadas em 04/09/2026 junto com o status ACEITA
        # (ALTER TABLE conferido: 20 colunas antes, 22 depois).
        "aceito_por": "ACEITO_POR",
        "data_aceite": "DATA_ACEITE",
        # LEFT JOIN com tb_dim_medicos (espelho local do Databricks, ver
        # known-issues.md — "RESOLVIDO POR VIA ALTERNATIVA").
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
        # (painel > limite) fica desativado nessa fonte, ver listar_revisao().
        "qtd_medicos_painel_ciclo": None,
        # Sprint 6 — tb_perfil_portal criada localmente em
        # data/scripts/13_create_tb_perfil_portal.sql, mesmo de-para de
        # nomes (minúsculo) usado no resto do schema local.
        "tabela_perfil_portal": "tb_perfil_portal",
        "limite_painel": "limite_painel",
        # tb_renovai_parametros criada localmente em
        # data/scripts/14_create_tabelas_chat_ranking_agente.sql, mesmo
        # de-para de nomes (minúsculo) usado no resto do schema local.
        "tabela_parametros": "tb_renovai_parametros",
        "limite_painel_padrao": "limite_painel_padrao",
        "motivo_desconsideracao": "motivo_desconsideracao",
        "desconsiderado_por": "desconsiderado_por",
        "data_desconsideracao": "data_desconsideracao",
        "qtd_vezes_desconsiderado": "qtd_vezes_desconsiderado",
        "bloquear_novas_recomendacoes": "bloquear_novas_recomendacoes",
        # Espelho local das colunas do aceite. A tabela local precisa delas
        # (`aceito_por text`, `data_aceite timestamptz`) para POST /aceitar
        # funcionar fora do Databricks.
        "aceito_por": "aceito_por",
        "data_aceite": "data_aceite",
        # tb_dim_medicos faz parte do espelho local criado pelo script 14.
        # DATA_ULTIMA_VISITA_CONSIDERADA ainda não existe na recomendação
        # local, então apenas meses_sem_visita continua indisponível.
        "tabela_dim_medicos": "tb_dim_medicos",
        "especialidade": "dm.especialidade",
        "cidade": "dm.cidade",
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


def _limite_painel(matricula: str, col: dict) -> int:
    """Resolve o limite de painel em vigor para o propagandista (Sprint 6:
    substitui o corte fixo de 400 médicos no painel pelo limite
    personalizável por propagandista).

    COALESCE(LIMITE_PAINEL, (SELECT LIMITE_PAINEL_PADRAO FROM
    tb_renovai_parametros WHERE ID=1)) — o literal 318 que vivia direto no
    SQL foi substituído pela tabela de parâmetros que o George criou em
    26/08/2026 (fonte única, confirmada com o mesmo valor 318 via
    DESCRIBE/SELECT reais — ver docs/context/decisions-log.md). Não é
    settings.limite_painel_padrao (config local do portal): é dado, muda
    sem deploy, igual ao notebook de geração que lê a mesma tabela.

    Nota de hardening registrada em docs/context/known-issues.md: esta
    fórmula falha de verdade (exceção) se tb_renovai_parametros estiver
    inacessível, mas devolve NULL em silêncio se a tabela existir sem a
    linha ID=1 — o comentário real da coluna sinaliza intenção de erro
    declarado nesse segundo caso, não implementada aqui por decisão
    explícita (fórmula mantida exatamente como especificada)."""
    with _engine().connect() as conn:
        row = conn.execute(
            text(f"""
                SELECT COALESCE(
                    {col['limite_painel']},
                    (SELECT {col['limite_painel_padrao']} FROM {col['tabela_parametros']} WHERE id = 1)
                ) AS limite
                FROM {col['tabela_perfil_portal']}
                WHERE {col['rep_matricula']} = :mat
            """),
            {"mat": matricula},
        ).fetchone()
        if row is not None:
            return row.limite
        # Ninguém personalizou (sem linha em tb_perfil_portal, caso mais
        # comum hoje) — mesmo default, buscado da mesma fonte única.
        return conn.execute(
            text(f"SELECT {col['limite_painel_padrao']} FROM {col['tabela_parametros']} WHERE id = 1")
        ).scalar()


def _fragmentos_dim_medicos(col: dict) -> dict:
    """Monta os fragmentos SQL condicionais do LEFT JOIN com
    tb_dim_medicos, disponível nas duas fontes. No Postgres ela é criada por
    data/scripts/14_create_tabelas_chat_ranking_agente.sql.

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
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))
    settings = get_settings()
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
        -- Melhor colocado primeiro: na entrada, prioridade é quem está mais
        -- alto no ranking do setor. Decisão de George em 04/09/2026, no lugar
        -- da ordenação por pontuação. Os dois quase coincidem, porque a
        -- posição vem da pontuação, mas divergem para quem atende mais de um
        -- setor: por pontuação, os setores se intercalam; por posição, o
        -- primeiro de cada setor aparece junto, que é como a pessoa lê.
        -- O identificador desempata, e não é detalhe: a posição repete entre
        -- setores e é nula em parte das linhas, e sem um critério único o
        -- banco pode devolver os empatados em ordem diferente a cada consulta.
        -- Na fronteira das páginas isso repete ou some com item. Achado da
        -- revisão independente de 04/09/2026.
        ORDER BY posicao_ranking ASC NULLS LAST, id_recomendacao ASC
        LIMIT :limite OFFSET :offset
    """)

    with _engine().connect() as conn:
        rows = conn.execute(
            query,
            {"mat": ctx.matricula, "ciclo": ciclo,
             "limite": _LIMITE_PAGINA, "offset": offset},
        ).mappings().fetchall()
        total = _total_pendentes(conn, col, ctx.matricula, ciclo, "ENTRADA_PAINEL")

    items = [RecomendacaoItem(**_aplicar_fallback_nome_medico(r)) for r in rows]
    return ListaRecomendacoesResponse(
        tipo="ENTRADA_PAINEL",
        total=total,
        recomendacoes=items,
        destaques=settings.limite_sugestoes,
    )


@router.get("/revisao", response_model=ListaRecomendacoesResponse)
def listar_revisao(
    email: Optional[str] = Query(None),
    ciclo: str = Query(None),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))
    settings = get_settings()
    col = _schema(settings.data_source)
    ciclo = ciclo or _ciclo_mais_recente(col)
    dm = _fragmentos_dim_medicos(col)
    meses_sem_visita = _fragmento_meses_sem_visita(col, condicional=False)
    limite_painel = _limite_painel(ctx.matricula, col)

    # Defesa em profundidade (known-issues.md): só aplicável na fonte que tem
    # a coluna. Continua no backend mesmo com a fonte já corrigida, como
    # proteção contra regressão futura. Sprint 6: o corte fixo (400) virou o
    # limite por propagandista (:limite_painel, resolvido acima via
    # _limite_painel — COALESCE(LIMITE_PAINEL, 318) em tb_perfil_portal).
    filtro_painel_limite = (
        f"AND {col['qtd_medicos_painel_ciclo']} > :limite_painel"
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
          {filtro_painel_limite}
        -- Pior colocado primeiro: na exclusão, prioridade é quem está mais no
        -- fundo do ranking do setor. Já era assim antes de 04/09/2026 e foi
        -- confirmado por George nessa data.
        -- Mesmo desempate da entrada, pelo mesmo motivo.
        ORDER BY posicao_ranking DESC NULLS LAST, id_recomendacao ASC
        LIMIT :limite OFFSET :offset
    """)

    with _engine().connect() as conn:
        rows = conn.execute(
            query,
            {"mat": ctx.matricula, "ciclo": ciclo,
             "limite": _LIMITE_PAGINA, "offset": offset,
             "limite_painel": limite_painel},
        ).mappings().fetchall()
        total = _total_pendentes(
            conn, col, ctx.matricula, ciclo, "REVISAO_PAINEL",
            filtro_extra=filtro_painel_limite,
            params_extra={"limite_painel": limite_painel},
        )

    items = [RecomendacaoItem(**_aplicar_fallback_nome_medico(r)) for r in rows]
    return ListaRecomendacoesResponse(
        tipo="REVISAO_PAINEL",
        total=total,
        recomendacoes=items,
        destaques=settings.limite_sugestoes,
    )


def _total_pendentes(conn, col: dict, matricula: str, ciclo: str, tipo: str,
                     filtro_extra: str = "", params_extra: Optional[dict] = None) -> int:
    """Quantas recomendações pendentes existem no ciclo, e não quantas vieram
    na página.

    Existe porque a lista deixou de ser cortada em 5: sem a contagem, a tela
    não teria como dizer "50 de 132" nem saber que há mais para carregar. O
    `filtro_extra` recebe o mesmo recorte de painel que a exclusão aplica, para
    o total bater com o que a lista realmente devolve.
    """
    consulta = text(f"""
        SELECT COUNT(*) AS total
        FROM {col['tabela']}
        WHERE {col['rep_matricula']} = :mat
          AND {col['tipo_recomendacao']} = :tipo
          AND {col['status_recomendacao']} = 'PENDENTE'
          AND {col['ciclo_referencia']} = :ciclo
          {filtro_extra}
    """)
    params = {"mat": matricula, "ciclo": ciclo, "tipo": tipo}
    params.update(params_extra or {})
    return int(conn.execute(consulta, params).scalar() or 0)


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


@router.post("/{id_recomendacao}/aceitar", response_model=AceitarResponse)
def aceitar(
    id_recomendacao: UUID,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """POST /recomendacoes/{id_recomendacao}/aceitar.

    O propagandista declara que vai cumprir a recomendação. **Isto é intenção,
    não é fato:** quem confirma que o médico entrou ou saiu do painel continua
    sendo o `JOB_ATUALIZACAO_RECOMENDACOES_PAINEL`, que compara contra o painel
    real e marca `APLICADA`. Por isso o aceite não pula para `APLICADA`: entre
    os dois vai existir a exportação por CSV, e afirmar o fato antes dele
    acontecer seria o portal mentindo sobre o painel.

    Espelha o desconsiderar em tudo que é regra de segurança: identidade só do
    token, ID só do path, data gerada aqui, `UPDATE` atômico com o status
    esperado repetido no `WHERE`.

    Sem corpo: aceitar não tem parâmetro nenhum.

    Só recomendação `PENDENTE` pode ser aceita. `INELEGIVEL` fica de fora de
    propósito: é o médico que deixou de ser recomendado no ranking, e aceitar
    uma recomendação que o próprio sistema já retirou não faz sentido.
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
        raise HTTPException(status_code=403, detail="Não autorizado a aceitar esta recomendação.")

    status_atual = row["status_recomendacao"]
    if status_atual == "ACEITA":
        raise HTTPException(status_code=409, detail="Recomendação já foi aceita.")
    if status_atual != "PENDENTE":
        raise HTTPException(
            status_code=400,
            detail=f"Recomendação em estado incompatível para aceite: '{status_atual}'.",
        )

    agora = datetime.now(timezone.utc)

    # Mesmo padrão do desconsiderar: o WHERE repete o status já conferido acima,
    # então dois cliques simultâneos gravam uma vez só e o segundo recebe
    # rowcount == 0, tratado como 409 abaixo, sem lock explícito.
    with _engine().connect() as conn:
        resultado = conn.execute(
            text(f"""
                UPDATE {col['tabela']}
                SET {col['status_recomendacao']} = 'ACEITA',
                    {col['aceito_por']}          = :mat,
                    {col['data_aceite']}         = :agora
                WHERE {col['id_recomendacao']} = :id
                  AND {col['status_recomendacao']} = 'PENDENTE'
            """),
            {"mat": ctx.matricula, "agora": agora, "id": id_str},
        )
        conn.commit()

    if resultado.rowcount == 0:
        # Diferente do 409 acima, que sabe que o status era ACEITA. Aqui o
        # SELECT viu PENDENTE e o UPDATE não pegou linha: outra requisição
        # mudou o estado no meio, e ela pode ter aceitado, desconsiderado ou
        # a virada de ciclo pode ter expirado. Afirmar "já foi aceita" seria
        # inventar qual das três. Achado da revisão independente de 04/09/2026.
        raise HTTPException(
            status_code=409,
            detail="A recomendação não está mais pendente.",
        )

    return AceitarResponse(
        success=True,
        message="Recomendação aceita com sucesso.",
        id_recomendacao=id_str,
        status_recomendacao="ACEITA",
        data_aceite=agora.isoformat(),
    )


@router.get("/desconsideradas", response_model=ListaDesconsideradasResponse)
def listar_desconsideradas(
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """GET /recomendacoes/desconsideradas — aba Histórico.

    Histórico completo, sem LIMIT, das recomendações que o propagandista
    autenticado já **resolveu**, mais recente primeiro.

    Até 04/09/2026 trazia só as desconsideradas, porque desconsiderar era a
    única decisão possível. Com o aceite, a aba passou a se chamar Histórico e
    a mostrar as duas, por decisão de George: quem quer conferir o que decidiu
    no ciclo não separa mentalmente "o que recusei" de "o que aceitei".

    `data_decisao` unifica as duas datas, e `status_recomendacao` diz qual foi
    a decisão. O nome da rota fica como está: renomear quebraria o contrato
    publicado no OpenAPI sem ganho para quem consome.
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
               {col['status_recomendacao']}              AS status_recomendacao,
               {col['data_desconsideracao']}             AS data_desconsideracao,
               COALESCE({col['data_desconsideracao']},
                        {col['data_aceite']})            AS data_decisao,
               {col['ciclo_referencia']}                 AS ciclo_recomendacao,
               LEFT({col['tabela']}.{col['ufcrm']}, 2) AS uf
               {dm['especialidade']}
               {dm['cidade']}
               {meses_sem_visita}
        FROM {col['tabela']}
        {dm['join']}
        WHERE {col['rep_matricula']} = :mat
          AND {col['status_recomendacao']} IN ('DESCONSIDERADA', 'ACEITA')
        -- `id_recomendacao` desempata: sem ele, decisões com a mesma data
        -- alternariam de ordem entre consultas.
        ORDER BY COALESCE({col['data_desconsideracao']},
                          {col['data_aceite']}) DESC,
                 {col['id_recomendacao']} DESC
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
