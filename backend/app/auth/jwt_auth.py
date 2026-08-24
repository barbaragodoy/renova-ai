"""
Resolução do e-mail autenticado, com flag de dev.

AUTH_REQUIRE_JWT=false (padrão local) -> aceita o e-mail cru vindo de
query/body, exatamente como hoje. Nenhum token é validado.

AUTH_REQUIRE_JWT=true (produção) -> exige header `Authorization: Bearer
<token>` válido (assinatura + audience + issuer via JWKS do Auth0/Entra ID) e
extrai o e-mail da claim configurada em AUTH_EMAIL_CLAIM (ainda não
confirmada com Flávio — ver CLAUDE.md). O e-mail recebido por query/body é
ignorado nesse modo: só o token é fonte de verdade.
"""
from typing import TYPE_CHECKING, Optional

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient

if TYPE_CHECKING:
    from backend.app.config import Settings

_jwks_clients: dict[str, PyJWKClient] = {}


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
) -> str:
    """Devolve o e-mail de quem está chamando, conforme o modo configurado.

    Ordem de precedência:

    1. `AUTH_MODE=senha`: o token de sessão do portal é a única fonte. O e-mail
       recebido por query ou body é ignorado. Sem token válido, 401.
    2. `AUTH_REQUIRE_JWT=true`: token corporativo validado por JWKS.
    3. Caso contrário: aceita o e-mail cru de query/body. Esse caminho existe
       para desenvolvimento local e NÃO deve valer em ambiente publicado, pois
       permite que qualquer solicitante escolha a identidade que quiser.
    """
    if settings is None:
        from backend.app.config import get_settings

        settings = get_settings()

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

    if not settings.auth_require_jwt:
        if not email_param:
            raise HTTPException(status_code=422, detail="email é obrigatório (AUTH_REQUIRE_JWT=false).")
        return email_param

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Header Authorization: Bearer <token> ausente.")

    token = authorization.split(" ", 1)[1].strip()
    return _extrair_email_do_token(token, settings)
