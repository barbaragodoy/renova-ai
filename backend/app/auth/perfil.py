"""
Perfil do propagandista autenticado, para a aba Usuário do portal.

Duas fontes. `tb_propagandistas` é a mesma que `/auth/contexto` usa para
resolver o setor, aqui lida de forma mais larga (cadeia de gestão e linha de
produto entram) e sem achatar em um setor único. `tb_perfil_portal` guarda o
que a pessoa edita no portal.

Por que a segunda tabela existe: `tb_propagandistas` é reconstruída por
`CREATE OR REPLACE TABLE` todo dia às 10h UTC pelo notebook
`objetos_renovai_ped`. Qualquer edição gravada nela some no rebuild seguinte.
`tb_perfil_portal` fica fora do job, chaveada por e-mail, e sobrevive.

E-mail como chave, e não matrícula: é o identificador que a sessão carrega e o
mesmo que `auth/context.py` usa para resolver o setor, então gravar por e-mail
dispensa uma consulta a mais só para descobrir a matrícula. Verificado em
07/08/2026 que os dois são equivalentes como identidade: 2.153 linhas, 2.148
matrículas distintas e 2.148 e-mails distintos, nenhum e-mail nulo ou vazio,
nenhuma matrícula com dois e-mails e nenhum e-mail com duas matrículas.
Decisão de George em 07/08/2026.

Diferença de comportamento em relação a `/auth/contexto`, e ela é deliberada:
o contexto trata mais de uma linha para o mesmo e-mail como IDENTIDADE_AMBIGUA
e bloqueia. O perfil não bloqueia: devolve as duas atribuições e deixa a
interface avisar. São responsabilidades diferentes. O contexto precisa de um
setor único para filtrar recomendação, e escolher um por conta própria seria
mostrar dado de outro setor. O perfil só descreve quem a pessoa é, e nesse
caso esconder a segunda atribuição é que seria errado.

Observação sobre uma nota desatualizada em `auth/context.py`: o comentário lá
afirma que a coluna de linha de produto não existe na tabela real. Isso valia
quando aquele código foi escrito. A coluna `LINHA_PRODUTO` existe hoje e é
lida aqui. O valor vem como código numérico da origem ("4", "5", "6"), não
como nome terapêutico. A planilha oficial de bricks recebida em 06/08/2026
confirma que esse código é o par de dígitos final do setor, mas o de-para para
nome terapêutico continua sem fonte, então o código é entregue cru e a
interface o rotula como código.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.db.databricks_connection import get_engine as _get_engine
from backend.app.schemas.perfil import (
    AtribuicaoSetor,
    FRANQUIAS_POR_LINHA,
    LimitePainelUpdateRequest,
    PerfilResponse,
    PerfilUpdateRequest,
)

perfil_router = APIRouter()

logger = logging.getLogger(__name__)

_PERFIL_NAO_ENCONTRADO = (
    "Nenhum propagandista encontrado para este e-mail. "
    "Verifique seu cadastro ou contate o administrador."
)


def _lista(valor: Optional[str]) -> List[str]:
    """Quebra `CIDADES_SETOR` e `ESPECIALIDADES_SETOR` em lista.

    As duas colunas guardam texto separado por vírgula e espaço, já ordenado
    por número de médicos decrescente na origem, com desempate alfabético. A
    ordem é preservada aqui porque é ela que define quais entram nas três
    primeiras que a tela mostra.

    Um setor fica sem correspondência no SalesFarma e tem as duas colunas
    nulas (medido em 06/08/2026, 2.152 de 2.153 com cobertura). Lista vazia é
    o resultado correto nesse caso, e a interface trata como não disponível.
    """
    if not valor:
        return []
    return [item.strip() for item in valor.split(",") if item.strip()]


_CAMPOS_PESSOA = """
    SELECT p.setor, p.linha_produto, p.rep_matricula, p.rep_nome,
           p.rep_email, p.rep_login, p.gd_nome, p.gd_email,
           p.gr_nome, p.gn_nome,
           p.cargo, p.regional, p.uf, p.linha_nome,
           p.cidades_setor, p.especialidades_setor,
           perfil.nome_exibicao, perfil.foto_path,
           perfil.dt_acesso_anterior, perfil.limite_painel,
           param.limite_painel_padrao
    FROM tb_propagandistas p
    LEFT JOIN tb_perfil_portal perfil
           ON LOWER(perfil.rep_email) = LOWER(p.rep_email)
    -- CROSS JOIN, não LEFT JOIN: tb_renovai_parametros é linha única (ID=1),
    -- sempre existe se a tabela existe — mesma ida ao banco que já resolve o
    -- resto, sem round-trip extra só para o default do limite de painel
    -- (substitui o literal 318 que vivia como fallback em Python, ver
    -- docs/context/decisions-log.md, 26/08/2026).
    CROSS JOIN tb_renovai_parametros param
    WHERE LOWER(p.rep_email) = LOWER(:email)
"""

# Identidade e resumo em uma ida só ao warehouse.
#
# Antes eram duas consultas: a da pessoa e, com os setores em mãos, a das
# contagens. Medido em 07/08/2026, cada ida ao warehouse custa perto de 0,7
# segundo mesmo com a engine já aberta, então a segunda consulta era quase
# metade do tempo de carregamento da aba.
#
# O que permite juntar é o `IN (SELECT setor FROM pessoa)`: os setores saem da
# própria consulta em vez de voltarem ao Python e descerem de novo. O
# `CROSS JOIN` repete as duas contagens em cada linha da pessoa, o que é
# inofensivo porque quem tem dois setores tem duas linhas e o resumo já é a
# soma dos dois.
#
# Sobre os filtros das contagens, que não são detalhe:
#
# `STATUS_RECOMENDACAO = 'PENDENTE'` porque o card conta pendência. Hoje as
# 416.745 linhas estão todas nesse status, e é o estado correto: o piloto não
# começou e nada foi desconsiderado. O filtro entra escrito desde já para o
# card acompanhar sozinho quando os status variarem.
#
# O ciclo é obrigatório nas duas. `tb_recomendacoes_painel_historico` é um log:
# cada ciclo acrescenta linhas em vez de substituir, então contar tudo somaria
# agosto com setembro e cresceria para sempre. No ranking, sem o filtro, o
# `MAX(QTD_MEDICOS_PAINEL_SETOR)` devolveria o maior valor entre ciclos e não o
# do vigente. Hoje só existe `202608`, então nenhum dos dois muda resultado, e
# é justamente por isso que precisam estar aqui: quando o 202609 chegar,
# ninguém vai lembrar. Regra dada por George em 07/08/2026.
#
# O ciclo corrente é o `MAX` da própria tabela, não `current_date()` formatado.
# Se a carga do mês atrasar, o portal segue mostrando o último ciclo carregado,
# que é o que vale para o propagandista, em vez de zerar o card no dia 1º.
#
# `QTD_MEDICOS_PAINEL_SETOR` é atributo do setor, repetido em todas as linhas
# dele, então o `MAX` agrupado devolve o valor e não um máximo de verdade.
# Verificado em 07/08/2026: nenhum dos 2.152 setores tem mais de um valor
# distinto nessa coluna.
_SQL_COM_RESUMO = f"""
    WITH pessoa AS ({_CAMPOS_PESSOA}),
    painel AS (
        SELECT COALESCE(SUM(qtd), 0) AS medicos_no_painel FROM (
            SELECT MAX(QTD_MEDICOS_PAINEL_SETOR) AS qtd
            FROM tb_ranking_medicos_validacao
            WHERE SETOR IN (SELECT setor FROM pessoa)
              AND CICLO_REFERENCIA = (
                  SELECT MAX(CICLO_REFERENCIA) FROM tb_ranking_medicos_validacao
              )
            GROUP BY SETOR
        )
    ),
    pendentes AS (
        SELECT COUNT(*) AS recomendacoes_pendentes
        FROM tb_recomendacoes_painel_historico
        WHERE SETOR IN (SELECT setor FROM pessoa)
          AND STATUS_RECOMENDACAO = 'PENDENTE'
          AND CICLO_RECOMENDACAO = (
              SELECT MAX(CICLO_RECOMENDACAO) FROM tb_recomendacoes_painel_historico
          )
    )
    SELECT pessoa.*, painel.medicos_no_painel, pendentes.recomendacoes_pendentes
    FROM pessoa CROSS JOIN painel CROSS JOIN pendentes
    ORDER BY pessoa.setor
"""

_SQL_SEM_RESUMO = f"{_CAMPOS_PESSOA} ORDER BY p.setor"


def resolver_perfil(email: str) -> PerfilResponse:
    """Monta o perfil a partir de todas as linhas do e-mail em tb_propagandistas.

    O `LOWER()` dos dois lados repete o cuidado já tomado em
    `auth/context.py`: parte dos registros tem o e-mail gravado em maiúsculas
    na origem, enquanto o provedor de identidade envia normalizado. Sem isso,
    esses propagandistas ficariam sem perfil. O mesmo `LOWER()` vale no join
    com `tb_perfil_portal`, porque a chave de lá é gravada em minúsculas mas o
    valor comparado vem da SIMV.

    O `LEFT JOIN` e não `JOIN`: quem nunca editou o perfil não tem linha em
    `tb_perfil_portal`, e é o caso de todo mundo hoje. Um join fechado deixaria
    a aba Usuário vazia para os 2.153 propagandistas.

    O `ORDER BY setor` existe para a resposta ser estável entre chamadas. Sem
    ordenação explícita, a ordem das atribuições pode variar e a tela reordena
    sozinha a cada carregamento, o que parece defeito para quem usa.

    A consulta com resumo é tentada primeiro e, se falhar, a identidade é
    buscada sozinha. Juntar as duas em uma ida ao warehouse é o que torna a aba
    rápida, mas amarra o perfil às tabelas de ranking e recomendação, que são
    reescritas por job. Sem esse cuidado, um problema nelas deixaria a pessoa
    sem ver nem o próprio nome. O caminho de erro custa uma consulta a mais e
    só acontece quando algo já está errado.
    """

    def _consultar(sql: str):
        engine = _get_engine()
        with engine.connect() as conn:
            return conn.execute(text(sql), {"email": email}).mappings().fetchall()

    try:
        linhas = _consultar(_SQL_COM_RESUMO)
    except Exception:
        logger.warning("Resumo do setor indisponível; carregando só a identidade.")
        linhas = _consultar(_SQL_SEM_RESUMO)

    if not linhas:
        # Mesmo critério de `/auth/contexto`: não existe coluna de ativo ou
        # inativo na tabela, e setores vagos já são removidos na origem. A
        # ausência de linha é o proxy correto de "não cadastrado".
        raise HTTPException(status_code=404, detail=_PERFIL_NAO_ENCONTRADO)

    primeira = linhas[0]

    # COALESCE resolvido aqui e não no SQL de propósito: `nome_editado` precisa
    # dizer de qual das duas fontes o valor veio, e um COALESCE no SELECT
    # entregaria só o resultado, sem a origem. Decisão de George em 07/08/2026,
    # item 1.2: mostra o editado quando existe, cai no nome de guerra da SIMV
    # quando não existe.
    nome_editado = primeira["nome_exibicao"]

    # Ausentes quando a consulta caiu para o caminho sem resumo. A interface
    # trata como não disponível e o resto da aba continua de pé.
    medicos = primeira.get("medicos_no_painel")
    pendentes = primeira.get("recomendacoes_pendentes")

    return PerfilResponse(
        matricula=primeira["rep_matricula"],
        nome=nome_editado or primeira["rep_nome"],
        nome_editado=nome_editado is not None,
        email=primeira["rep_email"],
        login=primeira["rep_login"],
        foto_path=primeira["foto_path"],
        cargo=primeira["cargo"],
        regional=primeira["regional"],
        uf=primeira["uf"],
        linha_nome=primeira["linha_nome"],
        cidades=_lista(primeira["cidades_setor"]),
        especialidades=_lista(primeira["especialidades_setor"]),
        # `linha_produto` vem como texto na origem ("1".."6"). str() protege
        # contra a coluna voltar como inteiro num rebuild da tabela.
        franquias_linha=FRANQUIAS_POR_LINHA.get(
            str(primeira["linha_produto"] or "").strip(), []
        ),
        dt_acesso_anterior=primeira["dt_acesso_anterior"],
        medicos_no_painel=medicos,
        recomendacoes_pendentes=pendentes,
        # Mesmo COALESCE do notebook de geração. Quando ninguém personalizou,
        # a coluna é nula e o valor em vigor é o padrão — lido de
        # tb_renovai_parametros no mesmo SELECT (CROSS JOIN em
        # _CAMPOS_PESSOA), não mais um literal 318 em Python.
        limite_painel=primeira.get("limite_painel") or primeira.get("limite_painel_padrao"),
        limite_painel_personalizado=primeira.get("limite_painel") is not None,
        atribuicoes=[
            AtribuicaoSetor(
                setor=linha["setor"],
                linha_produto=linha["linha_produto"],
                gd_nome=linha["gd_nome"],
                gd_email=linha["gd_email"],
                gr_nome=linha["gr_nome"],
                gn_nome=linha["gn_nome"],
            )
            for linha in linhas
        ],
    )


def gravar_nome(email: str, nome: Optional[str]) -> PerfilResponse:
    """Grava o nome de exibição e devolve o perfil já atualizado.

    A matrícula e o valor de origem são lidos de `tb_propagandistas` dentro
    desta função, nunca aceitos do corpo da requisição. Aceitar identificador
    do cliente permitiria que uma pessoa editasse o perfil de outra.

    `NOME_ORIGEM_NA_EDICAO` guarda o que a SIMV dizia no momento da edição.
    Serve para descobrir depois que o nome oficial mudou: comparando essa
    coluna com o `REP_NOME` atual dá para saber se a pessoa está vendo um nome
    editado que já ficou defasado em relação ao cadastro. Nada é feito com isso
    hoje, a coluna só evita que a informação se perca. Decisão de George em
    07/08/2026.

    `MERGE` e não `UPDATE` seguido de `INSERT` porque a pessoa pode nunca ter
    editado antes, e as duas situações precisam do mesmo comportamento externo.
    A cláusula `UPDATE SET` lista os campos um a um de propósito: um
    `UPDATE SET *` apagaria `FOTO_PATH`, que é escrito por outro fluxo.

    Delta não impõe chave primária, então a unicidade por e-mail depende do
    `ON` deste MERGE ser a única porta de escrita da tabela.
    """
    engine = _get_engine()
    with engine.connect() as conn:
        cadastro = (
            conn.execute(
                text("""
                    SELECT rep_matricula, rep_nome
                    FROM tb_propagandistas
                    WHERE LOWER(rep_email) = LOWER(:email)
                    LIMIT 1
                """),
                {"email": email},
            )
            .mappings()
            .first()
        )

        if cadastro is None:
            raise HTTPException(status_code=404, detail=_PERFIL_NAO_ENCONTRADO)

        conn.execute(
            text("""
                MERGE INTO tb_perfil_portal AS destino
                USING (SELECT LOWER(:email) AS rep_email) AS origem
                   ON destino.rep_email = origem.rep_email
                WHEN MATCHED THEN UPDATE SET
                    rep_matricula = :matricula,
                    nome_exibicao = :nome,
                    nome_origem_na_edicao = :origem_nome,
                    dt_atualizacao = current_timestamp
                WHEN NOT MATCHED THEN INSERT
                    (rep_email, rep_matricula, nome_exibicao,
                     nome_origem_na_edicao, foto_path, dt_atualizacao)
                    VALUES (LOWER(:email), :matricula, :nome,
                            :origem_nome, NULL, current_timestamp)
            """),
            {
                "email": email,
                "matricula": cadastro["rep_matricula"],
                "nome": nome,
                "origem_nome": cadastro["rep_nome"],
            },
        )
        conn.commit()

    return resolver_perfil(email)


def registrar_acesso(email: str) -> None:
    """Carimba o acesso da pessoa, chamada pelo login.

    Duas colunas em vez de uma: `DT_ACESSO_ATUAL` guarda o login em curso e
    `DT_ACESSO_ANTERIOR` recebe o valor que estava lá antes. A aba Usuário
    exibe a anterior, porque mostrar o acesso em curso daria sempre "agora" e
    não informaria nada. Decisão de George em 07/08/2026.

    No primeiro login da pessoa a anterior fica nula, e a interface trata isso
    como primeiro acesso em vez de data vazia.

    **Falha aqui nunca derruba o login.** Registrar acesso é informação de
    conveniência na tela de perfil; impedir alguém de entrar no portal por
    causa disso seria trocar um problema pequeno por um grande. O erro é
    registrado no log e o login segue.

    A matrícula do INSERT sai do próprio `USING`, lendo `tb_propagandistas`,
    em vez de vir por parâmetro: a `Identidade` montada no login carrega só
    e-mail, setor e nome, e abrir uma consulta a mais no caminho do login para
    buscar a matrícula encareceria a entrada de todo mundo por um campo que é
    só de rastreio.

    Ponto de atenção para a migração ao Entra ID: esta função é chamada de
    `auth/sessao.py`, no login por senha, que deixa de existir quando
    `AUTH_MODE=entra_id`. O ponto equivalente passa a ser onde a sessão
    corporativa é criada, e a chamada precisa acompanhar.
    """
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("""
                    MERGE INTO tb_perfil_portal AS destino
                    USING (
                        SELECT LOWER(:email) AS rep_email,
                               MAX(rep_matricula) AS rep_matricula
                        FROM tb_propagandistas
                        WHERE LOWER(rep_email) = LOWER(:email)
                    ) AS origem
                       ON destino.rep_email = origem.rep_email
                    WHEN MATCHED THEN UPDATE SET
                        dt_acesso_anterior = destino.dt_acesso_atual,
                        dt_acesso_atual = current_timestamp
                    WHEN NOT MATCHED THEN INSERT
                        (rep_email, rep_matricula, dt_acesso_anterior,
                         dt_acesso_atual)
                        VALUES (origem.rep_email, origem.rep_matricula, NULL,
                                current_timestamp)
                """),
                {"email": email},
            )
            conn.commit()
    except Exception:
        logger.warning("Não foi possível registrar o acesso no perfil.")


@perfil_router.get("/perfil", response_model=PerfilResponse)
def get_perfil(
    email: Optional[str] = Query(
        None,
        description=(
            "E-mail (modo dev, AUTH_REQUIRE_JWT=false). "
            "Ignorado se AUTH_REQUIRE_JWT=true."
        ),
    ),
    authorization: Optional[str] = Header(None),
):
    return resolver_perfil(resolver_email_autenticado(authorization, email))


@perfil_router.put("/perfil", response_model=PerfilResponse)
def put_perfil(
    body: PerfilUpdateRequest,
    email: Optional[str] = Query(
        None,
        description=(
            "E-mail (modo dev, AUTH_REQUIRE_JWT=false). "
            "Ignorado se AUTH_REQUIRE_JWT=true."
        ),
    ),
    authorization: Optional[str] = Header(None),
):
    """Edita o nome de exibição. `nome` nulo ou vazio desfaz a edição."""
    return gravar_nome(resolver_email_autenticado(authorization, email), body.nome)


def gravar_limite_painel(email: str, limite: Optional[int]) -> PerfilResponse:
    """Grava o limite do painel da pessoa em `tb_perfil_portal`.

    `limite` nulo volta ao padrão: a coluna é limpa e a leitura cai no
    COALESCE, mesmo desenho já usado no nome de exibição.

    O MERGE lista as colunas uma a uma em vez de `UPDATE SET *` porque a
    linha guarda também NOME_EXIBICAO e FOTO_PATH, escritos por outros
    fluxos. Um update amplo apagaria o nome editado de quem só quis mexer no
    tamanho do painel.

    A alteração fica auditada: LIMITE_ALTERADO_POR guarda a matrícula de quem
    mexeu e LIMITE_DT_ALTERACAO o momento. Como o limite muda o corte que o
    motor aplica no ciclo seguinte, saber quem mudou e quando é o que permite
    explicar depois por que o painel de alguém encolheu ou cresceu.
    """
    with _get_engine().connect() as conn:
        cadastro = conn.execute(
            text(
                "SELECT rep_matricula FROM tb_propagandistas "
                "WHERE LOWER(rep_email) = LOWER(:email) LIMIT 1"
            ),
            {"email": email},
        ).mappings().fetchone()

        if cadastro is None:
            raise HTTPException(status_code=404, detail=_PERFIL_NAO_ENCONTRADO)

        conn.execute(
            text("""
                MERGE INTO tb_perfil_portal AS destino
                USING (SELECT LOWER(:email) AS rep_email) AS origem
                   ON destino.rep_email = origem.rep_email
                WHEN MATCHED THEN UPDATE SET
                    rep_matricula = :matricula,
                    limite_painel = :limite,
                    limite_alterado_por = :matricula,
                    limite_dt_alteracao = current_timestamp
                WHEN NOT MATCHED THEN INSERT
                    (rep_email, rep_matricula, nome_exibicao,
                     nome_origem_na_edicao, foto_path, dt_atualizacao,
                     limite_painel, limite_alterado_por, limite_dt_alteracao)
                    VALUES (LOWER(:email), :matricula, NULL,
                            NULL, NULL, current_timestamp,
                            :limite, :matricula, current_timestamp)
            """),
            {
                "email": email,
                "matricula": cadastro["rep_matricula"],
                "limite": limite,
            },
        )
        conn.commit()

    return resolver_perfil(email)


@perfil_router.put("/perfil/limite-painel", response_model=PerfilResponse)
def put_limite_painel(
    body: LimitePainelUpdateRequest,
    email: Optional[str] = Query(
        None,
        description=(
            "E-mail (modo dev, AUTH_REQUIRE_JWT=false). "
            "Ignorado se AUTH_REQUIRE_JWT=true."
        ),
    ),
    authorization: Optional[str] = Header(None),
):
    """Altera o limite do painel. `limite` nulo volta ao padrão de 318.

    A faixa aceita é validada no corpo da requisição, não aqui: um valor fora
    dela devolve 422 antes de chegar ao banco.
    """
    return gravar_limite_painel(
        resolver_email_autenticado(authorization, email), body.limite
    )
