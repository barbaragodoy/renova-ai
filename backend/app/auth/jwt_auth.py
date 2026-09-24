"""Resolução da identidade autenticada.

- AUTH_MODE=senha: valida o JWT de sessão próprio do portal.
- AUTH_MODE=entra_id: usa os headers injetados pelo App Service Easy Auth.

O caminho AUTH_REQUIRE_JWT/JWKS permanece como legado, sem alteração. Ele
não é usado quando AUTH_MODE=entra_id.
"""
import base64
import binascii
import json
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator, TYPE_CHECKING, Optional

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

if TYPE_CHECKING:
    from backend.app.config import Settings

_jwks_clients: dict[str, PyJWKClient] = {}


@dataclass(frozen=True)
class CabecalhosEasyAuth:
    client_principal: Optional[str] = None


_CABECALHOS_VAZIOS = CabecalhosEasyAuth()
_cabecalhos_easy_auth: ContextVar[CabecalhosEasyAuth] = ContextVar(
    "cabecalhos_easy_auth",
    default=_CABECALHOS_VAZIOS,
)


async def capturar_cabecalhos_easy_auth(
    client_principal: Optional[str] = Header(
        None, alias="X-MS-CLIENT-PRINCIPAL"
    ),
) -> AsyncIterator[None]:
    """Captura os headers do Easy Auth uma única vez por requisição."""
    token = _cabecalhos_easy_auth.set(
        CabecalhosEasyAuth(client_principal=client_principal)
    )
    try:
        yield
    finally:
        _cabecalhos_easy_auth.reset(token)


# Claims aceitos como identidade, em ordem. Na Aché o login está em
# `preferred_username` (o token não traz `upn`); `upn` fica como reserva para
# tenants que o emitem. `emailaddress` nunca entra: é nome.sobrenome, não o
# login, e não bate com `REP_LOGIN`.
_CLAIMS_IDENTIDADE = ("preferred_username", "upn")


def _extrair_login_do_client_principal(client_principal: str) -> Optional[str]:
    """Decodifica o payload do Easy Auth e devolve o claim de login."""
    try:
        codificado = client_principal.strip()
        codificado += "=" * (-len(codificado) % 4)
        payload = json.loads(
            base64.b64decode(codificado, validate=True).decode("utf-8")
        )
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return None

    claims = payload.get("claims") if isinstance(payload, dict) else None
    if not isinstance(claims, list):
        return None

    valores = {
        claim.get("typ"): claim.get("val")
        for claim in claims
        if isinstance(claim, dict)
    }
    for tipo in _CLAIMS_IDENTIDADE:
        valor = valores.get(tipo)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return None


def _resolver_upn_easy_auth(
    client_principal: Optional[str] = None,
) -> str:
    """Identidade do Easy Auth, lida só de `X-MS-CLIENT-PRINCIPAL`.

    `X-MS-CLIENT-PRINCIPAL-NAME` não é usado. Em hmg, em 24/09/2026, ele trouxe
    o `emailaddress` (`nome.sobrenome_terceiro@...`), não o login. Com esse
    valor, a comparação com `REP_LOGIN` e com `tb_perfil_portal` falharia.
    """
    principal = (
        client_principal
        if client_principal is not None
        else _cabecalhos_easy_auth.get().client_principal
    )

    upn = _extrair_login_do_client_principal(principal) if principal else None
    if not upn:
        raise HTTPException(
            status_code=401,
            detail="Identidade do Easy Auth ausente ou inválida.",
        )
    return upn


def _get_jwks_client(domain: str) -> PyJWKClient:
    if domain not in _jwks_clients:
        _jwks_clients[domain] = PyJWKClient(f"https://{domain}/.well-known/jwks.json")
    return _jwks_clients[domain]


def _extrair_email_do_token(token: str, settings: "Settings") -> str:
    try:
        signing_key = _get_jwks_client(settings.auth0_domain).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[settings.auth0_algorithms],
            audience=settings.auth0_audience,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Token inválido: {exc}") from exc

    email = claims.get(settings.auth_email_claim)
    if not email:
        raise HTTPException(
            status_code=401,
            detail=f"Claim '{settings.auth_email_claim}' ausente ou vazia no token.",
        )
    return email


def resolver_email_autenticado(
    authorization: Optional[str],
    email_param: Optional[str],
    settings: Optional["Settings"] = None,
    *,
    client_principal: Optional[str] = None,
    aplicar_admin: bool = True,
) -> str:
    """Devolve a identidade efetiva de quem está chamando, conforme o modo configurado.

    Ordem de precedência para a identidade real:

    1. `AUTH_MODE=senha`: o token de sessão do portal é a única fonte. O e-mail
       recebido por query ou body é ignorado. Sem token válido, 401.
    2. `AUTH_MODE=entra_id`: claim `preferred_username` do header
       `X-MS-CLIENT-PRINCIPAL`, injetado pelo App Service Easy Auth.
    3. `AUTH_REQUIRE_JWT=true`: caminho legado, validado por JWKS.
    4. Caso contrário: aceita o e-mail cru de query/body. Esse caminho existe
       para desenvolvimento local e NÃO deve valer em ambiente publicado, pois
       permite que qualquer solicitante escolha a identidade que quiser.

    Resolvida a identidade real, o acesso administrativo pode trocar o e-mail
    devolvido pelo do propagandista que está sendo visualizado — ver
    `auth/administrativo.py`. A troca só acontece para quem está na lista
    configurada, e a conferência usa sempre a identidade real, nunca o header.

    `aplicar_admin=False` devolve a identidade real sem essa troca. É o que os
    próprios endpoints administrativos usam: com a troca aplicada, o
    administrador perderia a permissão ao abrir o painel de alguém e não
    conseguiria escolher um segundo propagandista sem reiniciar a sessão.
    """
    if settings is None:
        from backend.app.config import get_settings

        settings = get_settings()

    email_real = _resolver_identidade_real(
        authorization,
        email_param,
        settings,
        client_principal=client_principal,
    )

    # Checagem de STATUS_ACESSO sobre a identidade REAL, sempre antes de
    # qualquer outra resolução (matrícula/setor via resolver_contexto(),
    # personificação abaixo). Import local: status_acesso.py importa
    # coluna_identidade_para_auth_mode de auth/context.py, e um import no
    # topo deste módulo fecharia o ciclo (mesmo motivo do import de
    # administrativo mais abaixo).
    from backend.app.auth.status_acesso import exigir_acesso_liberado

    exigir_acesso_liberado(email_real, settings)

    if not aplicar_admin:
        return email_real

    # Importado aqui pelo mesmo motivo do import de `sessao` abaixo: o módulo
    # administrativo depende deste para resolver a identidade real, e um import
    # no topo fecharia o ciclo.
    from backend.app.auth.administrativo import aplicar_personificacao

    return aplicar_personificacao(email_real, settings)


def _resolver_identidade_real(
    authorization: Optional[str],
    email_param: Optional[str],
    settings: "Settings",
    *,
    client_principal: Optional[str] = None,
) -> str:
    """Quem está autenticado de fato, sem considerar acesso administrativo."""
    if settings.auth_mode.lower() == "senha":
        # Importado aqui para evitar dependência circular: sessao importa este
        # módulo indiretamente pela cadeia de configuração.
        from backend.app.auth.sessao import ler_token

        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=401, detail="Sessão ausente. Faça login no portal."
            )
        claims = ler_token(authorization.split(" ", 1)[1].strip(), settings)
        email = claims.get("email") or claims.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Sessão sem identidade.")
        return email

    if settings.auth_mode.lower() == "entra_id":
        # Confiar nestes headers é seguro em produção somente porque o App
        # Service Easy Auth está configurado com "Require authentication":
        # requisições não autenticadas são bloqueadas antes de chegar ao
        # FastAPI. Se a API for exposta diretamente, como num ambiente local,
        # qualquer cliente poderá forjar estes headers.
        return _resolver_upn_easy_auth(client_principal=client_principal)

    # Caminho legado AUTH_REQUIRE_JWT/JWKS. Intencionalmente intocado nesta task.
    if not settings.auth_require_jwt:
        if not email_param:
            raise HTTPException(status_code=422, detail="email é obrigatório (AUTH_REQUIRE_JWT=false).")
        return email_param

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Header Authorization: Bearer <token> ausente.")

    token = authorization.split(" ", 1)[1].strip()
    return _extrair_email_do_token(token, settings)
