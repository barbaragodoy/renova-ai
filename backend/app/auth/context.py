from enum import Enum
from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel
from sqlalchemy import text

from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.db.databricks_connection import get_engine as _get_engine

auth_router = APIRouter()


class StatusContexto(str, Enum):
    SETOR_RESOLVIDO = "SETOR_RESOLVIDO"
    PROPAGANDISTA_NAO_ENCONTRADO = "PROPAGANDISTA_NAO_ENCONTRADO"
    IDENTIDADE_AMBIGUA = "IDENTIDADE_AMBIGUA"


class ContextoResponse(BaseModel):
    status: StatusContexto
    matricula: Optional[str] = None
    setor: Optional[str] = None
    nome: Optional[str] = None
    mensagem: Optional[str] = None


# tb_propagandista_teste: tabela dedicada no mesmo catálogo/schema real,
# criada especificamente para validar IDENTIDADE_AMBIGUA com dado real (a
# tb_propagandistas real não tem nenhuma duplicidade hoje — ver CLAUDE.md).
# Whitelist evita que `tabela` vire um vetor de SQL injection caso algum dia
# passe a vir de fora — hoje só é usado internamente por testes de integração.
_TABELAS_PERMITIDAS = {"tb_propagandistas", "tb_propagandista_teste"}


def resolver_contexto(email: str, tabela: str = "tb_propagandistas") -> ContextoResponse:
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

    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT rep_matricula, setor, rep_nome "
                f"FROM {tabela} "
                f"WHERE LOWER(rep_email) = LOWER(:email)"
            ),
            {"email": email},
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
    )


@auth_router.get("/contexto", response_model=ContextoResponse)
def get_contexto(
    email: Optional[str] = Query(
        None, description="E-mail (modo dev, AUTH_REQUIRE_JWT=false). Ignorado se AUTH_REQUIRE_JWT=true."
    ),
    authorization: Optional[str] = Header(None),
):
    email_autenticado = resolver_email_autenticado(authorization, email)
    return resolver_contexto(email_autenticado)
