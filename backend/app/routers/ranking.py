import json
import logging
import re
import unicodedata
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from backend.app.auth.context import (
    StatusContexto,
    coluna_identidade_para_auth_mode,
    resolver_contexto,
)
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.config import get_settings
from backend.app.db.databricks_connection import get_engine
from backend.app.schemas.ranking import (
    ConcorrenteMercado,
    CondutaUpdateRequest,
    MercadoDetalhe,
    SegmentacaoUpdateRequest,
    CategoriaPrescrita,
    DetalheMedicoResponse,
    EnderecoAtendimento,
    EnderecoUpdateRequest,
    ListaRankingResponse,
    MedicoRanking,
    OpcaoProduto,
)

logger = logging.getLogger("renovai")

router = APIRouter()

# O ranking de um setor mediano tem cerca de mil médicos e o maior passa de
# doze mil, então a lista sai paginada e a busca roda no warehouse, não na
# tela.
_LIMITE_PAGINA = 50


def _validar_contexto(email: str):
    ctx = resolver_contexto(
        email,
        coluna_identidade=coluna_identidade_para_auth_mode(),
    )
    if ctx.status != StatusContexto.SETOR_RESOLVIDO:
        raise HTTPException(
            status_code=403,
            detail={"status": ctx.status, "mensagem": ctx.mensagem},
        )
    return ctx


def _fragmentos_recomendacao(data_source: str) -> dict:
    """Junção da lista do ranking com a recomendação do médico no ciclo.

    O Databricks usa a tabela histórica; o Postgres local usa
    `tb_recomendacoes_painel`. Os fragmentos preservam o mesmo contrato para
    a tela e a mesma garantia de uma única recomendação por médico e ciclo.

    Mesmo espírito do `_fragmentos_dim_medicos` em `routers/recomendacoes.py`.

    **A subconsulta com `ROW_NUMBER` não é enfeite.** Medido em 04/09/2026, a
    tabela tem 580.911 grupos de matrícula, médico e ciclo com mais de uma
    linha, quase todos com três, todas `EXPIRADA`. Uma junção direta
    multiplicaria a linha do médico e a paginação passaria a devolver menos de
    50 por página, em silêncio. A janela garante uma linha por médico por
    construção, e não por invariante que o banco não impõe.

    A ordem do desempate é de leitura: pendente primeiro, porque é sobre ela
    que se age; depois a de atividade mais recente, que é o que o propagandista
    lembra de ter feito; e por último o identificador, para não haver empate
    sem critério. Sem esse terceiro nível, duas linhas com a mesma data
    alternariam entre uma carga e outra.

    `GREATEST` e não `COALESCE` nas datas: `COALESCE` devolve a primeira não
    nula, que não é a mais recente quando a linha tem aceite e aplicação
    preenchidos ao mesmo tempo. `GREATEST` ignora nulo no Spark e devolve a
    data real de última atividade. Achado da revisão independente.

    `SETOR` entra na partição, e não só na junção: uma matrícula pode ter mais
    de um setor, e sem ele a janela poderia eleger a recomendação do outro
    setor da mesma pessoa. Essa linha não casaria no `ON`, e o médico apareceria
    sem selo mesmo tendo recomendação pendente no setor certo. Achado da mesma
    revisão.

    O `WHERE` da subconsulta corta pela matrícula antes da janela, então ela
    roda sobre as linhas de uma pessoa e não sobre a tabela inteira.

    Custo medido em 04/09/2026, no maior setor, com `use_cached_result = false`
    para não medir cache: 0,9 a 1,0 segundo sem esta junção, 1,4 a 1,8 segundo
    com ela. A conta é a mesma ordem de grandeza de uma ida ao warehouse, que
    já custa perto de 0,7 segundo mesmo com a engine aberta.
    """
    fonte = (data_source or "").lower()
    if fonte == "local":
        return {
            "select": (
                ",\n                       rec.id_recomendacao     AS id_recomendacao"
                ",\n                       rec.tipo_recomendacao   AS tipo_recomendacao"
                ",\n                       rec.status_recomendacao AS status_recomendacao"
            ),
            "join": (
                "\n                LEFT JOIN ("
                "\n                    SELECT setor, ufcrm, ciclo_referencia,"
                "\n                           id_recomendacao, tipo_recomendacao, status_recomendacao,"
                "\n                           ROW_NUMBER() OVER ("
                "\n                               PARTITION BY setor, ufcrm, ciclo_referencia"
                "\n                               ORDER BY CASE WHEN status_recomendacao = 'PENDENTE'"
                "\n                                             THEN 0 ELSE 1 END,"
                "\n                                        GREATEST(data_aceite,"
                "\n                                                 data_desconsideracao,"
                "\n                                                 data_ultima_verificacao) DESC,"
                "\n                                        id_recomendacao DESC"
                "\n                           ) AS ordem"
                "\n                    FROM tb_recomendacoes_painel"
                "\n                    WHERE rep_matricula = :mat"
                "\n                ) rec"
                "\n                       ON rec.setor = r.setor"
                "\n                      AND rec.ufcrm = r.ufcrm"
                "\n                      AND rec.ciclo_referencia = r.ciclo_referencia"
                "\n                      AND rec.ordem = 1"
            ),
        }
    if fonte != "databricks":
        return {"select": "", "join": ""}
    return {
        "select": (
            ",\n                       rec.ID_RECOMENDACAO     AS id_recomendacao"
            ",\n                       rec.TIPO_RECOMENDACAO   AS tipo_recomendacao"
            ",\n                       rec.STATUS_RECOMENDACAO AS status_recomendacao"
        ),
        # O ciclo entra na junção porque a mesma dupla setor e médico se repete
        # a cada ciclo: sem ele, a linha de um ciclo anterior apareceria como
        # se fosse do atual.
        #
        # A matrícula entra porque setor não é chave de pessoa: medido em
        # 04/09/2026, 5 setores da base têm mais de um propagandista. Sem ela,
        # a tela ofereceria a recomendação do colega, que o endpoint recusaria
        # com 403 depois do clique. Achado da revisão independente.
        "join": (
            "\n                LEFT JOIN ("
            "\n                    SELECT SETOR, UFCRM, CICLO_RECOMENDACAO,"
            "\n                           ID_RECOMENDACAO, TIPO_RECOMENDACAO, STATUS_RECOMENDACAO,"
            "\n                           ROW_NUMBER() OVER ("
            "\n                               PARTITION BY SETOR, UFCRM, CICLO_RECOMENDACAO"
            "\n                               ORDER BY CASE WHEN STATUS_RECOMENDACAO = 'PENDENTE'"
            "\n                                             THEN 0 ELSE 1 END,"
            "\n                                        GREATEST(DATA_ACEITE,"
            "\n                                                 DATA_DESCONSIDERACAO,"
            "\n                                                 DATA_APLICACAO_DETECTADA) DESC,"
            "\n                                        ID_RECOMENDACAO DESC"
            "\n                           ) AS ordem"
            "\n                    FROM tb_recomendacoes_painel_historico"
            "\n                    WHERE REP_MATRICULA = :mat"
            "\n                ) rec"
            "\n                       ON rec.SETOR = r.setor"
            "\n                      AND rec.UFCRM = r.ufcrm"
            "\n                      AND rec.CICLO_RECOMENDACAO = r.ciclo_referencia"
            "\n                      AND rec.ordem = 1"
        ),
    }


@router.get("", response_model=ListaRankingResponse)
def listar_ranking(
    email: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=80),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))

    filtro_busca = ""
    # `mat` só é usada pela junção com as recomendações, que existe apenas no
    # Databricks. Passar sempre é inofensivo: parâmetro não citado no SQL é
    # ignorado pelo driver, e vale mais que duplicar a montagem do dicionário.
    params = {
        "setor": ctx.setor,
        "mat": ctx.matricula,
        "limite": _LIMITE_PAGINA,
        "offset": offset,
    }
    if q and q.strip():
        # Os nomes na tabela têm acento e cedilha; o propagandista digita sem.
        # O translate normaliza os dois lados para a busca não perder nomes
        # como JOÃO ou GONÇALVES.
        # Ou pelo UFCRM: o "Pesquisar médico" do protótipo aceita nome ou CRM,
        # e o CRM digitado sem a UF ("994499") também precisa achar.
        filtro_busca = (
            "  AND (translate(r.nome_medico, 'ÁÂÃÀÄÉÊÈËÍÎÌÏÓÔÕÒÖÚÛÙÜÇ',"
            " 'AAAAAEEEEIIIIOOOOOUUUUC') LIKE :busca"
            "       OR r.ufcrm LIKE :busca)\n"
        )
        termo = q.strip().upper().translate(str.maketrans(
            "ÁÂÃÀÄÉÊÈËÍÎÌÏÓÔÕÒÖÚÛÙÜÇ", "AAAAAEEEEIIIIOOOOOUUUUC"))
        params["busca"] = f"%{termo}%"

    frag = _fragmentos_recomendacao(get_settings().data_source)

    with get_engine().connect() as conn:
        cabecalho = conn.execute(
            text("""
                SELECT MAX(ciclo_referencia) AS ciclo,
                       COUNT(*) AS total_medicos,
                       MAX(pontos) AS pontos_lider,
                       MAX(qtd_medicos_painel_setor) AS qtd_painel_setor
                FROM tb_ranking_medicos_validacao
                WHERE setor = :setor
            """),
            {"setor": ctx.setor},
        ).mappings().fetchone()

        # A data de carga vem do histórico de recomendações, e não da tabela
        # do ranking, que só tem o ciclo. Consulta separada: falha aqui não
        # derruba a lista, só deixa o cabeçalho sem a data.
        try:
            atualizado_em = conn.execute(
                text("SELECT MAX(data_exportacao) AS dt FROM tb_recomendacoes_painel_historico")
            ).scalar()
        except Exception:
            logger.exception("Falha ao ler a data de carga do histórico.")
            atualizado_em = None

        rows = conn.execute(
            text("""
                SELECT r.posicao_ranking_setor AS posicao,
                       r.nome_medico, r.ufcrm, r.pontos,
                       r.flag_no_painel, r.data_ultima_visita,
                       dm.especialidade, dm.cidade,
                       LEFT(r.ufcrm, 2) AS uf""" + frag["select"] + """
                FROM tb_ranking_medicos_validacao r
                LEFT JOIN tb_dim_medicos dm ON r.ufcrm = dm.ufcrm""" + frag["join"] + """
                WHERE r.setor = :setor
            """ + filtro_busca + """
                ORDER BY r.posicao_ranking_setor
                LIMIT :limite OFFSET :offset
            """),
            params,
        ).mappings().fetchall()

    medicos = [
        MedicoRanking(
            posicao=r["posicao"],
            nome_medico=r["nome_medico"],
            ufcrm=r["ufcrm"],
            pontos=r["pontos"],
            no_painel=bool(r["flag_no_painel"]),
            data_ultima_visita=str(r["data_ultima_visita"]) if r.get("data_ultima_visita") else None,
            especialidade=r["especialidade"],
            cidade=r["cidade"],
            uf=r["uf"],
            # O id e o tipo só saem quando há o que fazer. O status sai
            # sempre: é ele que diz à tela se mostra ação, se mostra o que já
            # foi decidido, ou se mostra o selo de painel.
            id_recomendacao_pendente=(
                str(r["id_recomendacao"])
                if r.get("status_recomendacao") == "PENDENTE" and r.get("id_recomendacao")
                else None
            ),
            tipo_recomendacao_pendente=(
                r.get("tipo_recomendacao")
                if r.get("status_recomendacao") == "PENDENTE" else None
            ),
            status_recomendacao=r.get("status_recomendacao"),
        )
        for r in rows
    ]
    return ListaRankingResponse(
        ciclo=cabecalho["ciclo"] or "",
        atualizado_em=str(atualizado_em) if atualizado_em else None,
        total_medicos=cabecalho["total_medicos"] or 0,
        pontos_lider=cabecalho["pontos_lider"],
        qtd_painel_setor=cabecalho["qtd_painel_setor"],
        offset=offset,
        limite=_LIMITE_PAGINA,
        medicos=medicos,
    )


def _janela_e_prescricao(d) -> tuple[Optional[str], list[CategoriaPrescrita], list[str], Optional[float]]:
    """Escolhe a janela de prescrição na mesma ordem do chat: ciclo, depois
    ano, depois histórico completo. O ano não guarda produtos, então nessa
    janela a lista de produtos sai vazia em vez de misturar períodos."""
    if d["ciclo_top1_categoria"]:
        categorias = [
            CategoriaPrescrita(nome=d[f"ciclo_top{i}_categoria"], pct=d[f"ciclo_top{i}_pct"])
            for i in (1, 2, 3) if d.get(f"ciclo_top{i}_categoria")
        ]
        produtos = [d[f"ciclo_top{i}_produto"] for i in (1, 2, 3) if d.get(f"ciclo_top{i}_produto")]
        return "no último ciclo", categorias, produtos, d["ciclo_pct_ache"]
    if d["ytd_top1_categoria"]:
        categorias = [
            CategoriaPrescrita(nome=d[f"ytd_top{i}_categoria"], pct=d.get(f"ytd_top{i}_pct"))
            for i in (1, 2, 3) if d.get(f"ytd_top{i}_categoria")
        ]
        return "no ano", categorias, [], d["ytd_pct_ache"]
    if d["geral_top1_categoria"]:
        categorias = [
            CategoriaPrescrita(nome=d[f"geral_top{i}_categoria"], pct=d.get(f"geral_top{i}_pct"))
            for i in (1, 2, 3) if d.get(f"geral_top{i}_categoria")
        ]
        produtos = [d[f"geral_top{i}_produto"] for i in (1, 2, 3) if d.get(f"geral_top{i}_produto")]
        return "em todo o histórico", categorias, produtos, d["geral_pct_ache"]
    return None, [], [], None


_SQL_SALESFARMA = """
    SELECT DISTINCT ds__profiss_local_trabalho AS local,
           ds__profiss_endereco AS logradouro,
           ds__profiss_bairro AS bairro,
           ds__profiss_cidade AS cidade,
           ds__profiss_estado AS uf,
           cd__profiss_cep AS cep
    FROM dmn_inteligencia_dados_prd.gold.vw__salesfarma_painel_medico
    WHERE cd__profiss_ufcrm = :ufcrm
      AND ds__profiss_endereco IS NOT NULL AND ds__profiss_endereco <> ''
      AND dt__periodo = (
          SELECT MAX(dt__periodo)
          FROM dmn_inteligencia_dados_prd.gold.vw__salesfarma_painel_medico
          WHERE cd__profiss_ufcrm = :ufcrm)
    ORDER BY local, logradouro
"""

_SQL_AUDITORIA = """
    SELECT ENDERECO AS logradouro, CIDADE AS cidade, UF AS uf, CEP AS cep
    FROM dmn_inteligencia_dados_prd.gold.audit_gerencial_dim_medicos_corp
    WHERE UFCRM = :ufcrm AND ENDERECO IS NOT NULL AND TRIM(ENDERECO) <> ''
    LIMIT 1
"""

_SQL_CNES = """
    SELECT nome_fantasia, razao_social, logradouro, numero, complemento, bairro,
           cep, municipio, uf, telefone
    FROM tb_cnes_local_atendimento
    WHERE ufcrm = :ufcrm
    ORDER BY nome_fantasia
"""

_SQL_CIDADES_SETOR = """
    SELECT cidades_setor FROM tb_propagandistas WHERE setor = :setor LIMIT 1
"""

# A correção mais recente do médico, de qualquer setor. Insere, nunca
# atualiza, mesmo padrão de tb_conduta_medico; a mais recente vale.
_SQL_CORRIGIDO = """
    SELECT logradouro, numero, complemento, bairro, cidade, uf, cep,
           registrado_por, registrado_em
    FROM tb_endereco_medico
    WHERE ufcrm = :ufcrm
    ORDER BY registrado_em DESC
    LIMIT 1
"""


def _enderecos_do_medico(ufcrm: str, setor: str):
    """Endereço 1, endereço 2 e a divergência entre eles.

    Quatro consultas curtas, cada uma protegida: a que falhar contribui com
    vazio e as outras seguem. As fontes e a regra estão documentadas em
    backend/app/enderecos.py.
    """
    from backend.app import enderecos as regra

    def _ler(sql: str, params: dict, um: bool = False):
        try:
            with get_engine().connect() as conn:
                res = conn.execute(text(sql), params).mappings()
                return dict(res.fetchone() or {}) if um else [dict(r) for r in res.fetchall()]
        except Exception:
            logger.exception("Falha ao ler fonte de endereço: %s", sql.strip().splitlines()[1].strip())
            return {} if um else []

    corrigido = _ler(_SQL_CORRIGIDO, {"ufcrm": ufcrm}, um=True) or None
    salesfarma = _ler(_SQL_SALESFARMA, {"ufcrm": ufcrm})
    auditoria = _ler(_SQL_AUDITORIA, {"ufcrm": ufcrm}, um=True) or None
    cnes = _ler(_SQL_CNES, {"ufcrm": ufcrm})
    cidades = _ler(_SQL_CIDADES_SETOR, {"setor": setor}, um=True)

    visita = regra.endereco_da_visita(salesfarma, auditoria, corrigido)
    local = regra.escolher_local_cnes(cnes, visita, regra.cidades_do_setor(cidades.get("cidades_setor")))
    return visita, ([local] if local else []), regra.divergem(visita, local)


@router.get("/medico/{ufcrm}", response_model=DetalheMedicoResponse)
def detalhar_medico(
    ufcrm: str,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))

    with get_engine().connect() as conn:
        row = conn.execute(
            text("""
                SELECT rk.nome_medico, rk.ufcrm,
                       dm.especialidade, dm.cidade, LEFT(rk.ufcrm, 2) AS uf,
                       rk.posicao_ranking_setor AS posicao, rk.pontos,
                       rk.flag_no_painel, rk.qtd_medicos_painel_setor,
                       rk.data_ultima_visita, rk.meses_desde_ultima_visita,
                       rk.ciclos_no_painel_janela,
                       rk.flag_nunca_visitado_com_janela,
                       rk.recomendacao,
                       CASE WHEN rk.motivo_recomendacao LIKE '%por ranking%'
                             AND rk.motivo_recomendacao LIKE '%por visita%' THEN 'ranking e visita'
                            WHEN rk.motivo_recomendacao LIKE '%por ranking%' THEN 'saiu do corte'
                            WHEN rk.motivo_recomendacao LIKE '%nenhuma visita%' THEN 'sem visita registrada'
                            WHEN rk.motivo_recomendacao LIKE '%por visita%' THEN 'dentro do corte sem visita'
                       END AS criterio_saida,
                       p.ciclo_top1_categoria, p.ciclo_top1_pct,
                       p.ciclo_top2_categoria, p.ciclo_top2_pct,
                       p.ciclo_top3_categoria, p.ciclo_top3_pct,
                       p.ciclo_top1_produto, p.ciclo_top2_produto, p.ciclo_top3_produto,
                       p.ciclo_pct_ache,
                       p.ytd_top1_categoria, p.ytd_top1_pct,
                       p.ytd_top2_categoria, p.ytd_top3_categoria, p.ytd_pct_ache,
                       p.geral_top1_categoria, p.geral_top1_pct,
                       p.geral_top2_categoria, p.geral_top3_categoria,
                       p.geral_top1_produto, p.geral_top2_produto, p.geral_top3_produto,
                       p.geral_pct_ache,
                       p.produto_recomendado_linha, p.produto_recomendado_categoria,
                       p.rec_e_top1, p.ja_prescreve_o_produto,
                       p.produto2_linha, p.produto2_categoria,
                       p.produto3_linha, p.produto3_categoria,
                       lider.pontos_lider,
                       seg.perfil_efetivo, seg.origem_do_valor,
                       cond.texto AS conduta_texto,
                       cond.registrado_em AS conduta_em,
                       cond.registrado_por AS conduta_por
                -- O ranking e a base, e o perfil e complemento. Ate 20/09/2026
                -- era o contrario, e o card dava 404 para quem estava no
                -- ranking sem linha no perfil: o ranking e reconstruido todo
                -- dia as 05:00 e a tb_perfil_medico_setor nao acompanha
                -- (203.697 linhas do ranking sem perfil, 11%, medido em
                -- 20/09/2026, incluindo a primeira colocada de um setor).
                -- Tudo que o card mostra vem do ranking; o perfil so traz
                -- prescricao e produto, que ficam nulos quando faltar.
                FROM tb_ranking_medicos_validacao rk
                LEFT JOIN tb_perfil_medico_setor p
                       ON p.setor = rk.setor AND p.ufcrm = rk.ufcrm
                LEFT JOIN tb_dim_medicos dm ON rk.ufcrm = dm.ufcrm
                -- A view resolve edicao > SalesFarma > a definir. Ela le a
                -- gold, que o service principal do portal nao alcanca, e
                -- funciona porque view do Unity Catalog roda com a permissao
                -- do dono. Mesmo mecanismo do vw_gold_auditpharma.
                LEFT JOIN vw_segmentacao_efetiva seg
                       ON seg.setor = rk.setor AND seg.ufcrm = rk.ufcrm
                -- A tb_conduta_medico nunca e atualizada: cada registro e uma
                -- linha nova, e o historico e o proprio dado. O vigente e o
                -- mais recente do par setor+ufcrm, resolvido aqui em vez de
                -- exigir uma view so para isso.
                LEFT JOIN (
                    SELECT setor, ufcrm, texto, registrado_em, registrado_por
                    FROM (
                        SELECT c.*, ROW_NUMBER() OVER (
                                 PARTITION BY c.setor, c.ufcrm
                                 ORDER BY c.registrado_em DESC) AS rn
                        FROM tb_conduta_medico c
                    ) x WHERE rn = 1
                ) cond ON cond.setor = rk.setor AND cond.ufcrm = rk.ufcrm
                CROSS JOIN (SELECT MAX(pontos) AS pontos_lider
                            FROM tb_ranking_medicos_validacao
                            WHERE setor = :setor) lider
                WHERE rk.setor = :setor AND rk.ufcrm = :ufcrm
                  AND rk.ciclo_referencia = (
                      SELECT MAX(ciclo_referencia)
                      FROM tb_ranking_medicos_validacao
                      WHERE setor = :setor)
            """),
            {"setor": ctx.setor, "ufcrm": ufcrm},
        ).mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Médico não encontrado no ranking do seu setor.")

    # Terceira ida, de propósito: endereços vêm de três fontes, duas em outro
    # catálogo, e o médico pode ter vários. Falha em qualquer uma deixa a
    # respectiva lista vazia; a gaveta mostra "não cadastrado" em vez de cair.
    # A regra de escolha está em backend/app/enderecos.py.
    enderecos, outros_locais, divergente = _enderecos_do_medico(ufcrm, ctx.setor)

    d = dict(row)
    ytd_pcts = {"ytd_top2_pct": None, "ytd_top3_pct": None,
                "geral_top2_pct": None, "geral_top3_pct": None}
    janela, categorias, produtos, pct_ache = _janela_e_prescricao({**ytd_pcts, **d})

    opcoes = [
        OpcaoProduto(nome=d[f"produto{i}_linha"], categoria=d[f"produto{i}_categoria"])
        for i in (2, 3) if d.get(f"produto{i}_linha")
    ]

    return DetalheMedicoResponse(
        nome_medico=d["nome_medico"],
        ufcrm=d["ufcrm"],
        perfil_comunicacao=d.get("perfil_efetivo") or "A DEFINIR",
        perfil_origem=d.get("origem_do_valor") or "a definir",
        conduta_texto=d.get("conduta_texto"),
        conduta_em=str(d["conduta_em"]) if d.get("conduta_em") else None,
        conduta_por=d.get("conduta_por"),
        especialidade=d["especialidade"],
        cidade=d["cidade"],
        uf=d["uf"],
        posicao=d["posicao"],
        pontos=d["pontos"],
        pontos_lider=d["pontos_lider"],
        no_painel=bool(d["flag_no_painel"]),
        qtd_painel_setor=d["qtd_medicos_painel_setor"],
        data_ultima_visita=str(d["data_ultima_visita"]) if d["data_ultima_visita"] else None,
        meses_sem_visita=d["meses_desde_ultima_visita"],
        ciclos_no_painel_janela=d["ciclos_no_painel_janela"],
        nunca_visitado_na_janela=(
            bool(d["flag_nunca_visitado_com_janela"])
            if d.get("flag_nunca_visitado_com_janela") is not None else None
        ),
        enderecos=[EnderecoAtendimento(**e.para_resposta()) for e in enderecos],
        outros_locais=[EnderecoAtendimento(**e.para_resposta()) for e in outros_locais],
        endereco_divergente=divergente,
        recomendacao=d["recomendacao"],
        criterio_saida=d["criterio_saida"],
        janela=janela,
        categorias=categorias,
        produtos=produtos,
        pct_ache=pct_ache,
        produto_recomendado=d["produto_recomendado_linha"],
        produto_recomendado_categoria=d["produto_recomendado_categoria"],
        rec_e_top1=bool(d["rec_e_top1"]),
        ja_prescreve_o_produto=bool(d["ja_prescreve_o_produto"]),
        opcoes_produto=opcoes,
    )


@router.put("/medico/{ufcrm}/segmentacao", response_model=DetalheMedicoResponse)
def classificar_medico(
    ufcrm: str,
    body: SegmentacaoUpdateRequest,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Grava a leitura do propagandista sobre o perfil do médico.

    Escreve em `tb_segmentacao_medico`, nunca na `tb_ranking_medicos_validacao`:
    aquela é reconstruída inteira por `CREATE OR REPLACE TABLE AS SELECT`, e uma
    edição gravada lá seria apagada na carga seguinte. O propagandista
    classificaria hoje e veria voltar para "a definir" amanhã, sem explicação.
    Desenho registrado em DESENHO_SEGMENTACAO_EDITAVEL_2026-08-19.

    `perfil_anterior` guarda o valor em vigor antes desta gravação, seja de
    edição anterior ou do SalesFarma. É o que permite reconstruir depois como a
    leitura do propagandista sobre aquele médico mudou ao longo dos ciclos.

    Setor e matrícula saem da sessão, nunca do corpo, pelo mesmo princípio já
    aplicado no resto do portal.
    """
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))

    with get_engine().connect() as conn:
        atual = conn.execute(
            text("""
                SELECT perfil_efetivo FROM vw_segmentacao_efetiva
                 WHERE setor = :setor AND ufcrm = :ufcrm
            """),
            {"setor": ctx.setor, "ufcrm": ufcrm},
        ).mappings().fetchone()

        conn.execute(
            text("""
                MERGE INTO tb_segmentacao_medico AS destino
                USING (SELECT :setor AS setor, :ufcrm AS ufcrm) AS origem
                   ON destino.setor = origem.setor
                  AND destino.ufcrm = origem.ufcrm
                WHEN MATCHED THEN UPDATE SET
                    perfil = :perfil,
                    perfil_anterior = :anterior,
                    alterado_por = :matricula,
                    alterado_em = current_timestamp,
                    observacao = :observacao
                WHEN NOT MATCHED THEN INSERT
                    (setor, ufcrm, perfil, alterado_por, alterado_em,
                     perfil_anterior, observacao, versao_esquema)
                    VALUES (:setor, :ufcrm, :perfil, :matricula,
                            current_timestamp, :anterior, :observacao, 1)
            """),
            {
                "setor": ctx.setor,
                "ufcrm": ufcrm,
                "perfil": body.perfil,
                "anterior": atual["perfil_efetivo"] if atual else None,
                "matricula": ctx.matricula,
                "observacao": body.observacao,
            },
        )
        conn.commit()

    # Relê pelo mesmo caminho da tela, para a resposta refletir a view e não o
    # que o cliente mandou.
    return detalhar_medico(ufcrm, email, authorization)


@router.put("/medico/{ufcrm}/conduta", response_model=DetalheMedicoResponse)
def registrar_conduta(
    ufcrm: str,
    body: CondutaUpdateRequest,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Registra como o médico vem tratando os pacientes, o campo "Como Trata".

    **Insere, nunca atualiza.** Cada registro é uma linha nova, e o histórico é
    o próprio dado: dá para reconstruir depois como a leitura do propagandista
    sobre aquele médico mudou ao longo dos ciclos. Sobrescrever jogaria fora
    exatamente o que torna este corpus valioso, já que ele é o único da KB que
    gera dado próprio.

    A chave é setor mais UFCRM, decisão de George em 18/08: o mesmo médico
    pertence a mais de um setor, cada propagandista mantém a própria leitura, e
    isso já entrega a segregação sem regra extra de visibilidade.

    Setor e matrícula saem da sessão, nunca do corpo.
    """
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))

    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO tb_conduta_medico
                    (id_registro, setor, ufcrm, texto, condicao, origem_texto,
                     registrado_por, registrado_em, versao_esquema)
                -- SELECT e nao VALUES: o Databricks recusa chamada de funcao
                -- dentro de tabela inline, entao current_timestamp() nao
                -- funciona num VALUES. Verificado em producao em 20/08 com
                -- INVALID_INLINE_TABLE.CANNOT_EVALUATE_EXPRESSION. id_registro
                -- deixou de vir de uuid() (so existe no Databricks) e passou a
                -- ser gerado em Python — funciona igual nas duas fontes, sem
                -- precisar de chamada de funcao SQL nenhuma para o id.
                SELECT :id_registro, :setor, :ufcrm, :texto, NULL, :origem,
                       :matricula, current_timestamp, 1
            """),
            {
                "id_registro": str(uuid.uuid4()),
                "setor": ctx.setor,
                "ufcrm": ufcrm,
                "texto": body.texto,
                "origem": body.origem,
                "matricula": ctx.matricula,
            },
        )
        conn.commit()

    return detalhar_medico(ufcrm, email, authorization)


@router.put("/medico/{ufcrm}/endereco", response_model=DetalheMedicoResponse)
def corrigir_endereco(
    ufcrm: str,
    body: EnderecoUpdateRequest,
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Registra a correção do endereço de atendimento feita pelo propagandista.

    **Insere, nunca atualiza**, como a conduta: cada correção é uma linha, e
    a mais recente por médico é a que vale na leitura. O histórico é o que vai
    permitir a sincronização com o SalesFarma quando a integração existir,
    e é também a auditoria de quem mudou o quê.

    Vale para o médico, não para o setor. Endereço é fato físico: se um
    propagandista foi lá e corrigiu, quem visita o mesmo médico por outra
    linha se beneficia. Decisão de George em 18/09/2026, junto com a de não
    ter carga mensal do CNES e deixar a manutenção com o propagandista.

    Setor e matrícula saem da sessão, nunca do corpo.
    """
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))

    with get_engine().connect() as conn:
        conn.execute(
            text("""
                INSERT INTO tb_endereco_medico
                    (id_registro, ufcrm, setor, logradouro, numero, complemento,
                     bairro, cidade, uf, cep, observacao,
                     registrado_por, registrado_em, versao_esquema)
                SELECT :id_registro, :ufcrm, :setor, :logradouro, :numero, :complemento,
                       :bairro, :cidade, :uf, :cep, :observacao,
                       :matricula, current_timestamp, 1
            """),
            {
                "id_registro": str(uuid.uuid4()),
                "ufcrm": ufcrm,
                "setor": ctx.setor,
                "logradouro": body.logradouro,
                "numero": body.numero,
                "complemento": body.complemento,
                "bairro": body.bairro,
                "cidade": body.cidade,
                "uf": body.uf,
                "cep": body.cep,
                "observacao": body.observacao,
                "matricula": ctx.matricula,
            },
        )
        conn.commit()

    return detalhar_medico(ufcrm, email, authorization)


# Nome de mercado para nome de arquivo na KB. Espaço vira hífen: o mercado
# "ADINOS GEN" mora em "ADINOS-GEN.md". Regra confirmada em 20/08 contra os
# 147 documentos publicados em kb-mercados.
def _arquivo_da_kb(mercado: str) -> str:
    return mercado.strip().upper().replace(" ", "-").replace("/", "-") + ".md"


def _interpretar_kb(mercado: str, texto: str) -> MercadoDetalhe:
    """Transforma o markdown da KB nos campos que a tela usa.

    Fica no servidor, e não no navegador, por dois motivos: o formato do
    documento é contrato da KB e muda com o gerador, então o lugar de
    acompanhar essa mudança é aqui; e evita mandar para o celular um texto
    inteiro do qual só um terço vai aparecer.

    Descartado de propósito: cabeçalho, produto Aché, referência dos dados,
    data de geração e a nota metodológica sobre o dicionário da auditoria.
    Nada disso ajuda quem está na porta do consultório.
    """
    detalhe = MercadoDetalhe(mercado=mercado)
    secao = None

    for linha in texto.split("\n"):
        crua, l = linha, linha.strip()
        if not l:
            continue

        if l.startswith("**Área terapêutica:**"):
            # "Dermomed (ATC: ...)" -> "Dermomed". A sigla do ATC é vocabulário
            # interno e não vai para a tela.
            valor = l.split("**", 2)[-1].strip()
            detalhe.area_terapeutica = valor.split("(")[0].strip() or None
            continue

        if l.startswith("## "):
            titulo = l[3:].lower()
            secao = ("concorrentes" if "concorre" in titulo
                     else "especialidades" if "prescreve" in titulo
                     else "usos" if "usado" in titulo else None)
            continue

        if secao == "concorrentes" and l.startswith("|"):
            celulas = [c.strip() for c in l.strip("|").split("|")]
            if len(celulas) < 3 or celulas[0].lower() in ("produto",) or set(celulas[0]) <= {"-"}:
                continue
            nome = celulas[0].replace("**", "").strip()
            lab = celulas[1].strip()
            detalhe.concorrentes.append(
                ConcorrenteMercado(
                    produto=nome,
                    laboratorio=lab.replace("(Aché)", "").strip() or None,
                    participacao=celulas[2] or None,
                    # O documento marca o produto Aché em negrito e escreve
                    # "(Aché)" no laboratório.
                    eh_ache="Aché" in celulas[1] or "**" in celulas[0],
                )
            )
            continue

        if secao == "especialidades" and l.startswith("- "):
            detalhe.especialidades.append(l[2:].strip())
            continue

        if secao == "usos":
            if l.startswith("Efeito terapêutico observado:"):
                detalhe.efeito = l.split(":", 1)[1].strip().rstrip(".") or None
                continue
            if l.startswith("- "):
                item = l[2:].strip()
                # Rótulo que não passou na revisão volta cru da auditoria, em
                # caixa alta, como "OUTR DERMATITE". Medido em 20/08: 150 itens
                # assim, espalhados por 103 dos 150 mercados. Mostrar isso ao
                # propagandista parece defeito. Some da tela; a correção
                # definitiva é no gerador da KB.
                if item.isupper():
                    continue
                detalhe.usos.append(item)

    return detalhe


@router.get("/mercado/{mercado}/kb", response_model=MercadoDetalhe)
def texto_do_mercado(
    mercado: str,
    cod_linha: str = Query(..., description="Código da linha, de 51 a 56"),
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Devolve o documento da KB daquele mercado montado.

    A KB é a fonte única desse texto. Verificado em 20/08 que os documentos de
    `kb-mercados`, gerados em 19/08, já usam a `tb_dim_rotulo_clinico`: não há
    dois textos a mesclar, e não é preciso tabela nem view nova. Ganho
    adicional: a gaveta e o chat passam a ler o mesmo corpus, então não há como
    um dizer uma coisa e o outro dizer outra.

    O caminho é montado a partir do código da linha e do nome do mercado, nunca
    de caminho vindo do cliente, e o nome é normalizado antes de virar arquivo.
    Sem isso, um pedido com `../` sairia da pasta da KB.
    """
    resolver_email_autenticado(authorization, email)

    if not cod_linha.isdigit() or not (51 <= int(cod_linha) <= 56):
        raise HTTPException(status_code=400, detail="Linha inválida.")

    from backend.app.auth.foto import _cliente, _raiz_do_volume

    caminho = (
        f"{_raiz_do_volume()}/kb-mercados/"
        f"Linha-{int(cod_linha) - 50}/{_arquivo_da_kb(mercado)}"
    )

    try:
        conteudo = _cliente().files.download(caminho).contents.read()
    except Exception:
        # Mercado sem documento é caso normal, não erro: a KB cobre os
        # mercados montados, e a AuditPharma tem 147 mercados no total.
        logger.info("Sem documento de KB para %s.", caminho)
        raise HTTPException(status_code=404, detail="Sem material para este mercado.")

    detalhe = _interpretar_kb(mercado, conteudo.decode("utf-8"))
    _juntar_estrategia_ciclo(detalhe, mercado, int(cod_linha) - 50)
    return detalhe


def _chave_produto(nome: str) -> str:
    """Nome comparável, sem acento, espaço, hífen nem sublinhado.

    A mesma marca muda de grafia conforme a fonte: `VITAE` no portfólio,
    `VITA-E` na KB, `VITA E` no material da Aché, `Vita_E.json` no arquivo.
    """
    limpo = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]", "", limpo).upper()


def _juntar_estrategia_ciclo(detalhe: MercadoDetalhe, mercado: str, linha: int) -> None:
    """Acrescenta ao detalhe o que a estratégia de ciclo diz do produto Aché.

    O mercado montado leva o nome do produto âncora, então mercado e produto
    casam por nome. Um mercado sem material simplesmente não recebe os campos,
    em vez de receber texto inventado.

    Falha aqui não derruba o resto: a ficha do mercado continua aparecendo.
    """
    from backend.app.auth.foto import _cliente, _raiz_do_volume

    pasta = f"{_raiz_do_volume()}/estrategia-ciclo/Linha-{linha}"
    cliente = _cliente()

    # O nome do arquivo segue a grafia do portfólio, `Adinos_GEN.json`, e o do
    # mercado vem em caixa alta da AuditPharma, `ADINOS GEN`. Montar o caminho
    # por concatenação erra a caixa, então a busca é por comparação normalizada
    # contra o que existe na pasta.
    alvo = _chave_produto(mercado)
    try:
        arquivos = list(cliente.files.list_directory_contents(pasta))
    except Exception:
        logger.info("Sem pasta de estratégia de ciclo em %s.", pasta)
        return

    caminho = next(
        (a.path for a in arquivos
         if a.name and a.name.endswith(".json")
         and _chave_produto(a.name[:-5]) == alvo),
        None,
    )
    if caminho is None:
        logger.info("Sem estratégia de ciclo para o mercado %s.", mercado)
        return

    try:
        bruto = cliente.files.download(caminho).contents.read()
    except Exception:
        logger.warning("Falha ao ler %s.", caminho)
        return

    try:
        dados = json.loads(bruto.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning("Estratégia de ciclo ilegível em %s.", caminho)
        return

    def texto(campo: str) -> Optional[str]:
        valor = dados.get(campo)
        if not valor or valor == "nao_informado":
            return None
        return valor if isinstance(valor, str) else None

    def lista(campo: str) -> list[str]:
        valor = dados.get(campo)
        if not isinstance(valor, list):
            return []
        return [v for v in valor if isinstance(v, str) and v != "nao_informado"]

    detalhe.indicacao = texto("indicacao_principal")
    detalhe.beneficio_clinico = texto("beneficio_clinico")
    detalhe.perfil_paciente = texto("perfil_paciente")
    detalhe.beneficios = lista("beneficios_chave")
    detalhe.vantagens = lista("vantagens_comerciais")
    ciclos = dados.get("ciclos_origem")
    detalhe.ciclos_origem = [c for c in ciclos if isinstance(c, int)] if isinstance(ciclos, list) else []
