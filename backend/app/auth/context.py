from enum import Enum
from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel
from sqlalchemy import text

from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.config import Settings, get_settings
from backend.app.db.databricks_connection import get_engine as _get_engine

auth_router = APIRouter()


class StatusContexto(str, Enum):
    SETOR_RESOLVIDO = "SETOR_RESOLVIDO"
    PROPAGANDISTA_NAO_ENCONTRADO = "PROPAGANDISTA_NAO_ENCONTRADO"
    IDENTIDADE_AMBIGUA = "IDENTIDADE_AMBIGUA"
    # Declarado para completude/documentação do contrato — na prática,
    # resolver_contexto() nunca RETORNA este status: ele levanta o 403
    # ACESSO_BLOQUEADO diretamente (ver auth/status_acesso.py), porque essa
    # resposta precisa ter formato idêntico nos dois pontos de integração
    # (login por senha e aqui) e não pode depender de cada chamador (routers
    # que hoje duplicam a própria função _validar_contexto) tratar o status
    # do jeito certo.
    ACESSO_BLOQUEADO = "ACESSO_BLOQUEADO"


class ContextoResponse(BaseModel):
    status: StatusContexto
    matricula: Optional[str] = None
    setor: Optional[str] = None
    nome: Optional[str] = None
    mensagem: Optional[str] = None
    # E-mail corporativo real do propagandista (tb_propagandistas.rep_email,
    # nunca o UPN bruto nem o rep_login). Adicionado para o fluxo de login
    # por Entra ID: sem formulário de e-mail/senha, este é o único jeito da
    # interface aprender o e-mail de quem entrou, para montar a sessão. Em
    # AUTH_MODE=senha a interface já sabe o e-mail (digitou no formulário) e
    # não depende deste campo, mas ele vem preenchido do mesmo jeito.
    email: Optional[str] = None


# tb_propagandista_teste: tabela dedicada no mesmo catálogo/schema real,
# criada especificamente para validar IDENTIDADE_AMBIGUA com dado real (a
# tb_propagandistas real não tem nenhuma duplicidade hoje — ver CLAUDE.md).
# Whitelist evita que `tabela` vire um vetor de SQL injection caso algum dia
# passe a vir de fora — hoje só é usado internamente por testes de integração.
_TABELAS_PERMITIDAS = {"tb_propagandistas", "tb_propagandista_teste"}
_COLUNAS_IDENTIDADE_PERMITIDAS = {"rep_email", "rep_login"}


def extrair_login_do_upn(upn: str) -> str:
    """Retorna apenas a parte anterior ao primeiro '@', sem assumir domínio."""
    return upn.strip().split("@", 1)[0]


def coluna_identidade_para_auth_mode(
    settings: Optional[Settings] = None,
) -> str:
    settings = settings or get_settings()
    return "rep_login" if settings.auth_mode == "entra_id" else "rep_email"


def resolver_contexto(
    email: str,
    tabela: str = "tb_propagandistas",
    coluna_identidade: str = "rep_email",
) -> ContextoResponse:
    # Schema real confirmado em acheinfo_dev.renovai.tb_propagandistas (verificação
    # técnica direta no Databricks, 2026-07): não existe coluna de status
    # ativo/inativo. Registros "VAGO" (vaga sem titular) já são removidos na
    # origem pelo pipeline de ingestão (acheinfo_prd.2_tru.tbl_tru_simv_sector_brazil
    # → carga diária via ADF). Ausência de linha para o e-mail já é o proxy
    # correto de "não encontrado/inativo" — por isso não há filtro `ativo`.
    #
    # cod_linha (linha de produto) também não existe na tabela real — não é
    # selecionado aqui. Se essa dimensão for necessária para recomendações,
    # a fonte real precisa ser confirmada com Hugo (relacionado a HUGO-08).
    #
    # Validação de domínio de e-mail (settings.lista_dominios_email_aceitos)
    # não é aplicada como filtro aqui: o match direto contra tb_propagandistas
    # já restringe o resultado a e-mails cadastrados, o que cobre ache.com.br
    # e biosintetica.com.br sem precisar de uma checagem de domínio redundante.
    # E-mail comparado via LOWER() dos dois lados: 14/2156 registros reais têm
    # rep_email gravado em maiúsculas (ex.: SUELEN.BRITO@ACHE.COM.BR), enquanto
    # Auth0/Entra ID tipicamente envia o e-mail normalizado em minúsculas — um
    # match exato (`=`) deixava esses 14 propagandistas incorretamente como
    # PROPAGANDISTA_NAO_ENCONTRADO. Confirmado que isso não introduz
    # duplicidade: zero colisões via LOWER(rep_email) nos 2156 registros reais.
    if tabela not in _TABELAS_PERMITIDAS:
        raise ValueError(f"Tabela não permitida: {tabela}")
    if coluna_identidade not in _COLUNAS_IDENTIDADE_PERMITIDAS:
        raise ValueError(f"Coluna de identidade não permitida: {coluna_identidade}")

    # A checagem de STATUS_ACESSO NÃO fica aqui, apesar do que a primeira
    # leitura da task sugeria. Todo chamador real deste módulo passa
    # `resolver_email_autenticado(...)` como `email` — e essa função, por
    # padrão (aplicar_admin=True), já devolve o e-mail PERSONIFICADO quando
    # X-Ver-Como está ativo. Checar acesso aqui checaria o status do
    # propagandista sendo visualizado, não do administrador real — o
    # inverso exato do que a regra exige (personificação nunca deve
    # influenciar esta checagem). A checagem real fica em
    # auth/jwt_auth.py::resolver_email_autenticado(), sobre `email_real`,
    # antes do branch de personificação — todo chamador passa por lá antes
    # de chegar aqui, então repetir a checagem neste ponto, sobre o valor
    # já (possivelmente) personificado, seria redundante e incorreto.

    identidade = (
        extrair_login_do_upn(email)
        if coluna_identidade == "rep_login"
        else email
    )

    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT rep_matricula, setor, rep_nome, rep_email "
                f"FROM {tabela} "
                f"WHERE LOWER({coluna_identidade}) = LOWER(:email)"
            ),
            {"email": identidade},
        ).fetchall()

    if len(rows) == 0:
        return ContextoResponse(
            status=StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO,
            mensagem=(
                "Nenhum propagandista encontrado para este e-mail. "
                "Verifique seu cadastro ou contate o administrador."
            ),
        )

    if len(rows) > 1:
        # No dado real da tb_propagandistas (2156 registros), COUNT(*) ==
        # COUNT(DISTINCT REP_EMAIL) — não há duplicidade hoje. Este branch é
        # exercitado por teste mockado (test_identidade_ambigua) e, com dado
        # real, por tb_propagandista_teste (ver test_context_integration.py).
        return ContextoResponse(
            status=StatusContexto.IDENTIDADE_AMBIGUA,
            mensagem=(
                "Mais de um cadastro encontrado para este e-mail. "
                "Contate o administrador para regularizar o cadastro."
            ),
        )

    row = rows[0]
    return ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO,
        matricula=row.rep_matricula,
        setor=row.setor,
        nome=row.rep_nome,
        email=row.rep_email,
    )


@auth_router.get("/contexto", response_model=ContextoResponse)
def get_contexto(
    email: Optional[str] = Query(
        None, description="E-mail (modo dev, AUTH_REQUIRE_JWT=false). Ignorado se AUTH_REQUIRE_JWT=true."
    ),
    authorization: Optional[str] = Header(None),
):
    email_autenticado = resolver_email_autenticado(authorization, email)
    return resolver_contexto(
        email_autenticado,
        coluna_identidade=coluna_identidade_para_auth_mode(),
    )
