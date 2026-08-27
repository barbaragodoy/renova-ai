import json
import logging
import re
import unicodedata
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from backend.app.auth.context import resolver_contexto, StatusContexto
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.db.databricks_connection import get_engine
from backend.app.schemas.ranking import (
    ConcorrenteMercado,
    CondutaUpdateRequest,
    MercadoDetalhe,
    MercadoPrescrito,
    SegmentacaoUpdateRequest,
    CategoriaPrescrita,
    DetalheMedicoResponse,
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
    ctx = resolver_contexto(email)
    if ctx.status != StatusContexto.SETOR_RESOLVIDO:
        raise HTTPException(
            status_code=403,
            detail={"status": ctx.status, "mensagem": ctx.mensagem},
        )
    return ctx


@router.get("", response_model=ListaRankingResponse)
def listar_ranking(
    email: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=80),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    ctx = _validar_contexto(resolver_email_autenticado(authorization, email))

    filtro_busca = ""
    params = {"setor": ctx.setor, "limite": _LIMITE_PAGINA, "offset": offset}
    if q and q.strip():
        # Os nomes na tabela têm acento e cedilha; o propagandista digita sem.
        # O translate normaliza os dois lados para a busca não perder nomes
        # como JOÃO ou GONÇALVES.
        filtro_busca = (
            "  AND translate(r.nome_medico, 'ÁÂÃÀÄÉÊÈËÍÎÌÏÓÔÕÒÖÚÛÙÜÇ',"
            " 'AAAAAEEEEIIIIOOOOOUUUUC') LIKE :busca\n"
        )
        termo = q.strip().upper().translate(str.maketrans(
            "ÁÂÃÀÄÉÊÈËÍÎÌÏÓÔÕÒÖÚÛÙÜÇ", "AAAAAEEEEIIIIOOOOOUUUUC"))
        params["busca"] = f"%{termo}%"

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

        rows = conn.execute(
            text("""
                SELECT r.posicao_ranking_setor AS posicao,
                       r.nome_medico, r.ufcrm, r.pontos,
                       r.flag_no_painel,
                       dm.especialidade, dm.cidade,
                       LEFT(r.ufcrm, 2) AS uf
                FROM tb_ranking_medicos_validacao r
                LEFT JOIN tb_dim_medicos dm ON r.ufcrm = dm.ufcrm
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
            especialidade=r["especialidade"],
            cidade=r["cidade"],
            uf=r["uf"],
        )
        for r in rows
    ]
    return ListaRankingResponse(
        ciclo=cabecalho["ciclo"] or "",
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
                SELECT p.nome_medico, p.ufcrm,
                       dm.especialidade, dm.cidade, LEFT(p.ufcrm, 2) AS uf,
                       p.posicao_ranking_setor AS posicao, p.pontos,
                       p.flag_no_painel, p.qtd_medicos_painel_setor,
                       p.data_ultima_visita, p.meses_desde_ultima_visita,
                       p.ciclos_no_painel_janela,
                       p.recomendacao,
                       CASE WHEN p.motivo_recomendacao LIKE '%por ranking%'
                             AND p.motivo_recomendacao LIKE '%por visita%' THEN 'ranking e visita'
                            WHEN p.motivo_recomendacao LIKE '%por ranking%' THEN 'saiu do corte'
                            WHEN p.motivo_recomendacao LIKE '%nenhuma visita%' THEN 'sem visita registrada'
                            WHEN p.motivo_recomendacao LIKE '%por visita%' THEN 'dentro do corte sem visita'
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
                FROM tb_perfil_medico_setor p
                LEFT JOIN tb_dim_medicos dm ON p.ufcrm = dm.ufcrm
                -- A view resolve edicao > SalesFarma > a definir. Ela le a
                -- gold, que o service principal do portal nao alcanca, e
                -- funciona porque view do Unity Catalog roda com a permissao
                -- do dono. Mesmo mecanismo do vw_gold_auditpharma.
                LEFT JOIN vw_segmentacao_efetiva seg
                       ON seg.setor = p.setor AND seg.ufcrm = p.ufcrm
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
                ) cond ON cond.setor = p.setor AND cond.ufcrm = p.ufcrm
                CROSS JOIN (SELECT MAX(pontos) AS pontos_lider
                            FROM tb_ranking_medicos_validacao
                            WHERE setor = :setor) lider
                WHERE p.setor = :setor AND p.ufcrm = :ufcrm
            """),
            {"setor": ctx.setor, "ufcrm": ufcrm},
        ).mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Médico não encontrado no ranking do seu setor.")

    # Segunda ida ao warehouse, de propósito: juntar a AuditPharma na consulta
    # principal traria o grão de mercado mais produto e multiplicaria as linhas
    # do detalhe. Falha aqui não derruba a gaveta, só deixa a seção vazia.
    try:
        with get_engine().connect() as conn:
            mercados, mercados_referencia = _mercados_do_medico(conn, ctx.setor, ufcrm)
    except Exception:
        logger.exception("Falha ao ler os mercados da AuditPharma.")
        mercados, mercados_referencia = [], None

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
        mercados=mercados,
        mercados_referencia=mercados_referencia,
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


def _mercados_do_medico(conn, setor: str, ufcrm: str):
    """Top 3 mercados montados em que o médico prescreveu, da AuditPharma.

    Fonte separada do resto do detalhe por decisão de George em 20/08: é a
    mesma tabela que o propagandista confere na ferramenta dele, então o número
    bate por construção, sem depender de a nossa regra coincidir com a deles.

    A `vw_gold_auditpharma` já filtra pela referência mais recente na própria
    definição, então o recorte de um ciclo só sai de graça. A view lê a gold,
    catálogo em que o service principal do portal não tem privilégio nenhum, e
    funciona porque view do Unity Catalog roda com a permissão do dono.

    Agrupa por mercado porque o grão da tabela é mercado mais produto: sem o
    GROUP BY, um mercado com quatro concorrentes ocuparia as três posições.
    """
    linhas = conn.execute(
        text("""
            SELECT MERCADO, MAX(COD_LINHA) AS cod_linha,
                   SUM(RX_MERCADO_ATUAL) AS rx,
                   MAX(REFERENCIA) AS referencia
              FROM vw_gold_auditpharma
             WHERE SETOR = :setor AND UFCRM = :ufcrm
               AND RX_MERCADO_ATUAL > 0
             GROUP BY MERCADO
             ORDER BY rx DESC
             LIMIT 3
        """),
        {"setor": setor, "ufcrm": ufcrm},
    ).mappings().fetchall()

    mercados = [
        MercadoPrescrito(
            mercado=l["MERCADO"],
            rx=float(l["rx"]) if l["rx"] is not None else None,
            cod_linha=str(l["cod_linha"]) if l["cod_linha"] else None,
        )
        for l in linhas
    ]
    referencia = str(linhas[0]["referencia"]) if linhas else None
    return mercados, referencia


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
