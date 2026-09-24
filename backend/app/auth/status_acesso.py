"""Bloqueio de acesso por STATUS_ACESSO/PERFIL_ACESSO em tb_perfil_portal.

Controla quem pode entrar no portal, independente do modo de autenticação
(senha ou entra_id) e independente de já ter cadastro em tb_propagandistas
— administradores não têm. A checagem é sempre sobre a identidade REAL que
autenticou: o header X-Ver-Como (personificação, ver auth/administrativo.py)
NUNCA entra aqui, porque bloqueio de acesso é sobre quem está logado, não
sobre o que essa pessoa está temporariamente vendo.

tb_perfil_portal (Databricks real): 2.146 propagandistas (60 ATIVO, 2.086
BLOQUEADO) + 13 administradores, carregado desde 21/09/2026.
"""
from typing import NamedTuple, Optional

from fastapi import HTTPException
from sqlalchemy import text

from backend.app.auth.context import coluna_identidade_para_auth_mode, extrair_login_do_upn
from backend.app.config import Settings, get_settings
from backend.app.db.databricks_connection import get_engine

_MENSAGEM_BLOQUEADO = (
    "Seu acesso ao Ped.AI está bloqueado temporariamente. Aguarde a "
    "ativação da sua conta ou o fim do período de testes."
)


class StatusAcesso(NamedTuple):
    status_acesso: Optional[str]
    perfil_acesso: Optional[str]


def levantar_acesso_bloqueado(mensagem: str = _MENSAGEM_BLOQUEADO) -> None:
    """Levanta o 403 padronizado de bloqueio de acesso.

    Helper único, para os dois pontos de integração (POST /auth/login e
    resolver_contexto()) nunca divergirem no formato da resposta.
    """
    raise HTTPException(
        status_code=403,
        detail={"codigo": "ACESSO_BLOQUEADO", "detail": mensagem},
    )


def resolver_status_acesso(
    identidade: str, settings: Optional[Settings] = None, *, por_email: bool = False
) -> StatusAcesso:
    """Resolve status_acesso e perfil_acesso para a identidade autenticada.

    `identidade` é sempre a identidade REAL que autenticou, na forma bruta
    recebida: e-mail corporativo em AUTH_MODE=senha, UPN completo (com
    domínio) em AUTH_MODE=entra_id — nunca um e-mail vindo de X-Ver-Como.

    Duas tentativas, nesta ordem:

    1. Propagandista — resolve a matrícula via tb_propagandistas, casando
       pela coluna do modo de autenticação (coluna_identidade_para_auth_mode:
       rep_login em entra_id, rep_email em senha), e junta tb_perfil_portal
       por rep_matricula. Matrícula é a chave estável entre os dois modos,
       ao contrário do e-mail/UPN bruto.
    2. Administrador — sem propagandista encontrado, tenta direto em
       tb_perfil_portal.rep_email com a identidade bruta recebida.
       ATENÇÃO: para administradores, rep_email guarda o UPN do Entra ID tal
       como recebido, não necessariamente um e-mail corporativo real — não
       há vínculo com tb_propagandistas para resolver de outra forma.

    Sem match em nenhuma das duas: (None, None). Quem chama trata isso como
    bloqueado (deny-by-default) — ver `exigir_acesso_liberado`.
    """
    settings = settings or get_settings()
    # `por_email=True`: a aba Usuário (auth/perfil.py) consulta o status da
    # pessoa exibida pelo REP_EMAIL da linha dela, em qualquer modo. Esse
    # valor nunca é a identidade autenticada, então não vale a regra do modo.
    coluna = "rep_email" if por_email else coluna_identidade_para_auth_mode(settings)
    assert coluna in ("rep_login", "rep_email")  # só pode vir da ternária acima

    # Mesma extração de auth/context.py::resolver_contexto(): em entra_id o
    # identificador comparado contra rep_login é só a parte antes do primeiro
    # '@' do UPN, nunca o UPN inteiro. Sem isto, a consulta abaixo nunca
    # casaria propagandista nenhum em entra_id — bug real encontrado
    # escrevendo os testes desta task (fixado antes de qualquer teste
    # depender do comportamento errado).
    identidade_propagandista = (
        extrair_login_do_upn(identidade) if coluna == "rep_login" else identidade
    )

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT pp.status_acesso, pp.perfil_acesso
                FROM tb_propagandistas p
                JOIN tb_perfil_portal pp ON pp.rep_matricula = p.rep_matricula
                WHERE LOWER(p.{coluna}) = LOWER(:identidade)
                """
            ),
            {"identidade": identidade_propagandista},
        ).fetchone()

        if row is None:
            row = conn.execute(
                text(
                    "SELECT status_acesso, perfil_acesso FROM tb_perfil_portal "
                    "WHERE LOWER(rep_email) = LOWER(:identidade)"
                ),
                {"identidade": identidade},
            ).fetchone()

    if row is None:
        return StatusAcesso(None, None)
    return StatusAcesso(row.status_acesso, row.perfil_acesso)


def exigir_acesso_liberado(
    identidade: str, settings: Optional[Settings] = None
) -> StatusAcesso:
    """Resolve o status e levanta ACESSO_BLOQUEADO se não estiver ATIVO.

    Ponto único que aplica a condição `!= "ATIVO"` — nunca repetir essa
    comparação em outro lugar do código, para as duas integrações (login por
    senha e resolver_contexto) nunca divergirem sobre o que conta como
    liberado.
    """
    resultado = resolver_status_acesso(identidade, settings)
    if resultado.status_acesso != "ATIVO":
        levantar_acesso_bloqueado()
    return resultado
