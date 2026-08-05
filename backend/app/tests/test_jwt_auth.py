"""
Testes de resolver_email_autenticado (auth/jwt_auth.py).

Modo dev (AUTH_REQUIRE_JWT=false): e-mail cru via query/body, sem validar token.
Modo produção (AUTH_REQUIRE_JWT=true): exige Bearer token válido, e-mail vem
da claim configurada (AUTH_EMAIL_CLAIM) — mockado aqui, sem bater num Auth0/
Entra ID real.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from backend.app.auth.jwt_auth import resolver_email_autenticado


def _settings(**overrides):
    base = dict(
        auth_require_jwt=False,
        auth_email_claim="preferred_username",
        auth0_domain="renovai.auth0.com",
        auth0_audience="https://api.renovai/",
        auth0_algorithms="RS256",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_modo_dev_usa_email_do_parametro():
    email = resolver_email_autenticado(None, "ana.lima@ache.com.br", settings=_settings())
    assert email == "ana.lima@ache.com.br"


def test_modo_dev_ignora_authorization_presente():
    """No modo dev, o token (se vier) é ignorado — só o parâmetro conta."""
    email = resolver_email_autenticado("Bearer qualquer-coisa", "ana.lima@ache.com.br", settings=_settings())
    assert email == "ana.lima@ache.com.br"


def test_modo_dev_sem_email_retorna_422():
    with pytest.raises(HTTPException) as exc:
        resolver_email_autenticado(None, None, settings=_settings())
    assert exc.value.status_code == 422


def test_modo_producao_sem_token_retorna_401():
    with pytest.raises(HTTPException) as exc:
        resolver_email_autenticado(None, "ana.lima@ache.com.br", settings=_settings(auth_require_jwt=True))
    assert exc.value.status_code == 401


def test_modo_producao_header_sem_bearer_retorna_401():
    with pytest.raises(HTTPException) as exc:
        resolver_email_autenticado("Basic abc123", None, settings=_settings(auth_require_jwt=True))
    assert exc.value.status_code == 401


def test_modo_producao_token_valido_extrai_claim():
    settings = _settings(auth_require_jwt=True)
    fake_signing_key = MagicMock(key="fake-key")

    with patch("backend.app.auth.jwt_auth._get_jwks_client") as mock_get_client, \
         patch("backend.app.auth.jwt_auth.jwt.decode") as mock_decode:
        mock_get_client.return_value.get_signing_key_from_jwt.return_value = fake_signing_key
        mock_decode.return_value = {"preferred_username": "joao.gd@ache.com.br"}

        email = resolver_email_autenticado("Bearer token.valido.aqui", None, settings=settings)

    assert email == "joao.gd@ache.com.br"
    mock_decode.assert_called_once_with(
        "token.valido.aqui",
        "fake-key",
        algorithms=["RS256"],
        audience="https://api.renovai/",
    )


def test_modo_producao_token_invalido_retorna_401():
    settings = _settings(auth_require_jwt=True)

    with patch("backend.app.auth.jwt_auth._get_jwks_client") as mock_get_client:
        mock_get_client.return_value.get_signing_key_from_jwt.side_effect = pyjwt.PyJWTError("assinatura inválida")

        with pytest.raises(HTTPException) as exc:
            resolver_email_autenticado("Bearer token.invalido", None, settings=settings)

    assert exc.value.status_code == 401


def test_modo_producao_claim_ausente_retorna_401():
    settings = _settings(auth_require_jwt=True)
    fake_signing_key = MagicMock(key="fake-key")

    with patch("backend.app.auth.jwt_auth._get_jwks_client") as mock_get_client, \
         patch("backend.app.auth.jwt_auth.jwt.decode") as mock_decode:
        mock_get_client.return_value.get_signing_key_from_jwt.return_value = fake_signing_key
        mock_decode.return_value = {"sub": "abc123"}  # sem preferred_username

        with pytest.raises(HTTPException) as exc:
            resolver_email_autenticado("Bearer token.valido", None, settings=settings)

    assert exc.value.status_code == 401
