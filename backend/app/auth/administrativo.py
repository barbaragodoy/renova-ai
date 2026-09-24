"""Acesso administrativo do projeto: abrir o portal no lugar de um propagandista.

Serve para o time do projeto conferir o que o propagandista vê, sem precisar da
senha dele e sem depender de o login próprio dele já estar funcionando.

Não confundir com o acesso futuro de gerente distrital, regional e nacional.
Aquilo é outra feature, com outra regra de escopo, e a hierarquia dela já existe
em `tb_propagandistas` (GD_EMAIL, GR_EMAIL, GN_EMAIL). Aqui a lista é fixa, curta
e vem do ambiente.

Como funciona
-------------
Todo endpoint do portal começa com `resolver_email_autenticado()`, que devolve o
e-mail de quem chamou, e `resolver_contexto()`, que transforma esse e-mail em
matrícula e setor. Este módulo entra entre os dois: quando quem chama está na
lista administrativa e a requisição traz o setor alvo, o e-mail devolvido passa a
ser o do propagandista escolhido. Daí para baixo nada muda, e nenhum endpoint
precisou ser alterado.

O alvo viaja no header `X-Ver-Como`, lido pelo middleware em `main.py` e guardado
num ContextVar. ContextVar porque o valor precisa atravessar a pilha de chamadas
sem passar por parâmetro em dez assinaturas, e porque ele é isolado por
requisição, tanto em corrotina quanto em thread do pool do FastAPI.

Três regras de segurança, nesta ordem de importância
----------------------------------------------------
1. A identidade real vem só do token. O header diz qual painel abrir, nunca quem
   é quem está pedindo.
2. A autorização é conferida no servidor, sobre a identidade real, a cada
   requisição. Não existe flag de administrador vinda do cliente.
3. Sessão personificada não escreve. O middleware recusa qualquer método que não
   seja GET enquanto o header estiver presente. Sem isso, um aceite ou uma
   desconsideração feita durante conferência ficaria registrada no nome do
   propagandista, e a pergunta "quem decidiu isto" deixaria de ter resposta.

O alvo é identificado pelo `setor`, e não pelo e-mail: setor é único por
propagandista (2.146 setores para 2.146 registros, conferido em 16/09/2026), é
opaco o bastante para trafegar em header e log, e restringe a escolha ao que
existe na tabela. Com e-mail, quem chama poderia digitar qualquer string.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from backend.app.db.databricks_connection import get_engine

logger = logging.getLogger("renovai")

admin_router = APIRouter()

# Setor que a requisição atual pediu para visualizar. Preenchido pelo middleware
# a partir do header, ainda sem nenhuma conferência de permissão — quem confere é
# `aplicar_personificacao`, que é o único ponto com a identidade real em mãos.
_SETOR_ALVO: ContextVar[Optional[str]] = ContextVar("setor_alvo", default=None)

# Métodos que uma sessão personificada pode usar. Tudo que escreve fica de fora.
METODOS_SOMENTE_LEITURA = {"GET", "HEAD", "OPTIONS"}

HEADER_VER_COMO = "X-Ver-Como"


def registrar_alvo(setor: Optional[str]) -> None:
    """Guarda o setor pedido pela requisição atual. Chamado pelo middleware."""
    _SETOR_ALVO.set((setor or "").strip() or None)


def alvo_atual() -> Optional[str]:
    return _SETOR_ALVO.get()


def eh_administrador(identidade: str, settings) -> bool:
    """Lista administrativa vinda de `tb_perfil_portal.PERFIL_ACESSO`.

    Substituiu `ADMIN_EMAILS` (lista fixa no ambiente) — a task de bloqueio
    de acesso trouxe PERFIL_ACESSO como fonte real, a mesma que já resolve
    STATUS_ACESSO (ver auth/status_acesso.py). Reaproveita a mesma consulta
    de identidade dupla (propagandista via coluna do modo de autenticação,
    fallback direto para administrador via REP_EMAIL) em vez de duplicá-la.

    Import local pelo mesmo motivo de sempre neste módulo: um import no topo
    fecharia ciclo com jwt_auth/context.
    """
    if not identidade:
        return False

    from backend.app.auth.status_acesso import resolver_status_acesso

    return resolver_status_acesso(identidade, settings).perfil_acesso == "ADMINISTRADOR"


SQL_EMAIL_DO_SETOR = """
SELECT rep_email
FROM tb_propagandistas
WHERE setor = :setor
"""


def email_do_setor(setor: str) -> Optional[str]:
    """E-mail do propagandista dono do setor, ou None se o setor não existir.

    Devolver None em vez de erro deixa a decisão para quem chama: em
    `aplicar_personificacao` isso vira 404, porque o administrador pediu um
    painel que não existe, e não uma falha de autenticação.
    """
    with get_engine().connect() as conn:
        linhas = conn.execute(text(SQL_EMAIL_DO_SETOR), {"setor": setor}).fetchall()
    if len(linhas) != 1:
        return None
    return linhas[0][0]


def aplicar_personificacao(email_real: str, settings) -> str:
    """Devolve o e-mail efetivo da requisição.

    Sem header, devolve a identidade real e o portal se comporta como sempre.
    Com header e sem permissão, também devolve a identidade real: o pedido é
    ignorado e registrado, nunca atendido. Só quem está na lista troca de
    contexto.
    """
    setor = alvo_atual()
    if not setor:
        return email_real

    if not eh_administrador(email_real, settings):
        # Registrar é o que transforma uma tentativa em evidência. Sem esta
        # linha, uma varredura de setores por alguém autenticado passaria
        # despercebida, porque a resposta é idêntica à de uma sessão normal.
        logger.warning(
            "personificacao negada | identidade=%s setor_pedido=%s", email_real, setor
        )
        return email_real

    email_alvo = email_do_setor(setor)
    if not email_alvo:
        raise HTTPException(
            status_code=404,
            detail=f"Setor {setor} não encontrado em tb_propagandistas.",
        )

    logger.info(
        "personificacao | administrador=%s setor=%s alvo=%s",
        email_real,
        setor,
        email_alvo,
    )
    return email_alvo


# ---------------------------------------------------------------------------
# Endpoints de apoio à tela de seleção
# ---------------------------------------------------------------------------


class PropagandistaItem(BaseModel):
    setor: str
    nome: Optional[str] = None
    linha: Optional[str] = None
    regional: Optional[str] = None
    uf: Optional[str] = None
    cidades: Optional[str] = None


class ListaPropagandistasResponse(BaseModel):
    total: int
    itens: list[PropagandistaItem]


class OpcoesResponse(BaseModel):
    """Valores distintos para montar a cascata da tela de seleção."""

    linhas: list[str]
    regionais: list[str]
    ufs: list[str]


class SessaoAdminResponse(BaseModel):
    administrador: bool
    identidade: str
    vendo_setor: Optional[str] = None


def _exigir_admin(authorization: Optional[str], email: Optional[str]):
    """Resolve a identidade real e exige que ela esteja na lista.

    Importa aqui dentro porque `jwt_auth` importa este módulo: no topo, o par
    fecharia um ciclo. Mesmo recurso que `jwt_auth` já usa para `sessao`.
    """
    from backend.app.auth.jwt_auth import resolver_email_autenticado
    from backend.app.config import get_settings

    settings = get_settings()
    # Identidade real de propósito: `resolver_email_autenticado` já aplicaria a
    # personificação, e aí o administrador perderia a própria permissão ao abrir
    # o painel de alguém — não conseguiria trocar para um segundo propagandista
    # sem sair e entrar de novo.
    identidade = _identidade_real(authorization, email, settings)
    if not eh_administrador(identidade, settings):
        raise HTTPException(
            status_code=403, detail="Acesso restrito à lista administrativa do projeto."
        )
    return identidade, settings


def _identidade_real(authorization: Optional[str], email: Optional[str], settings) -> str:
    from backend.app.auth.jwt_auth import resolver_email_autenticado

    return resolver_email_autenticado(
        authorization, email, settings, aplicar_admin=False
    )


@admin_router.get("/sessao", response_model=SessaoAdminResponse)
def sessao_admin(
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Diz ao frontend se deve oferecer o seletor de propagandista.

    Não é ponto de decisão de segurança: quem autoriza de fato é
    `aplicar_personificacao`, a cada chamada. Este endpoint só evita desenhar um
    botão que a pessoa não pode usar.
    """
    from backend.app.config import get_settings

    settings = get_settings()
    identidade = _identidade_real(authorization, email, settings)
    return SessaoAdminResponse(
        administrador=eh_administrador(identidade, settings),
        identidade=identidade,
        vendo_setor=alvo_atual(),
    )


SQL_OPCOES = """
SELECT DISTINCT linha_nome, regional, uf
FROM tb_propagandistas
"""


@admin_router.get("/opcoes", response_model=OpcoesResponse)
def listar_opcoes(
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    _exigir_admin(authorization, email)
    with get_engine().connect() as conn:
        linhas = conn.execute(text(SQL_OPCOES)).mappings().fetchall()

    def distintos(campo: str) -> list[str]:
        return sorted({r[campo] for r in linhas if r[campo]})

    return OpcoesResponse(
        linhas=distintos("linha_nome"),
        regionais=distintos("regional"),
        ufs=distintos("uf"),
    )


@admin_router.get("/propagandistas", response_model=ListaPropagandistasResponse)
def listar_propagandistas(
    linha: Optional[str] = Query(None),
    regional: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    busca: Optional[str] = Query(None, max_length=120),
    limite: int = Query(100, ge=1, le=500),
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Lista para o seletor, filtrada pela cascata.

    `busca` casa por nome ou por setor, porque quem confere às vezes já sabe o
    setor e não quer navegar a cascata inteira.
    """
    _exigir_admin(authorization, email)

    condicoes = []
    params: dict[str, object] = {"limite": limite}
    if linha:
        condicoes.append("linha_nome = :linha")
        params["linha"] = linha
    if regional:
        condicoes.append("regional = :regional")
        params["regional"] = regional
    if uf:
        condicoes.append("uf = :uf")
        params["uf"] = uf
    if busca:
        condicoes.append("(LOWER(rep_nome) LIKE :busca OR LOWER(setor) LIKE :busca)")
        params["busca"] = f"%{busca.strip().lower()}%"

    onde = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    # Os filtros entram por bind param; só o bloco WHERE é montado, e ele é
    # feito de literais fixos definidos acima. Nada vindo do cliente é
    # interpolado na string.
    query = text(
        f"""
        SELECT setor, rep_nome AS nome, linha_nome AS linha, regional, uf,
               cidades_setor AS cidades
        FROM tb_propagandistas
        {onde}
        ORDER BY rep_nome
        LIMIT :limite
        """
    )

    with get_engine().connect() as conn:
        linhas = conn.execute(query, params).mappings().fetchall()

    return ListaPropagandistasResponse(
        total=len(linhas),
        itens=[PropagandistaItem(**dict(r)) for r in linhas],
    )
