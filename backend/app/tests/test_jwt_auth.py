"""
Testes de resolver_email_autenticado (auth/jwt_auth.py).

Modo dev (AUTH_REQUIRE_JWT=false): e-mail cru via query/body, sem validar token.
Modo produção (AUTH_REQUIRE_JWT=true): exige Bearer token válido, e-mail vem
da claim configurada (AUTH_EMAIL_CLAIM) — mockado aqui, sem bater num Auth0/
Entra ID real.
"""
import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.auth.jwt_auth import (
    capturar_cabecalhos_easy_auth,
    resolver_email_autenticado,
)

# Este arquivo testa a extração de identidade (JWT/headers Easy Auth), não a
# checagem de STATUS_ACESSO — ela é testada em test_status_acesso.py. Sem
# isto, toda identidade fictícia usada aqui seria bloqueada por não ter linha
# real em tb_perfil_portal. Fixture compartilhada em conftest.py.
pytestmark = pytest.mark.usefixtures("liberar_acesso_por_padrao")


def _settings(**overrides):
    # `auth_mode` entrou no contrato em 04/08/2026, quando o modo `senha` passou
    # a ser o único caminho válido no ambiente publicado. Este arquivo cobre os
    # outros dois modos, então o mock precisa dizer explicitamente que não é o
    # `senha`. O modo `senha` é coberto em `test_sessao.py`.
    base = dict(
        auth_mode="local",
        auth_require_jwt=False,
        auth_email_claim="preferred_username",
        auth0_domain="renovai.auth0.com",
        auth0_audience="https://api.renovai/",
        auth0_algorithms="RS256",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _client_principal(*claims: dict) -> str:
    payload = json.dumps({"claims": list(claims)}).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def test_entra_id_usa_principal_name_e_ignora_bearer_e_email_param():
    settings = _settings(auth_mode="entra_id", auth_require_jwt=True)

    with patch("backend.app.auth.jwt_auth._get_jwks_client") as jwks:
        upn = resolver_email_autenticado(
            "Bearer token-legado",
            "email.informado@ache.com.br",
            settings=settings,
            client_principal_name="usuario.teste@biosintetica.com.br",
        )

    assert upn == "usuario.teste@biosintetica.com.br"
    jwks.assert_not_called()


def test_entra_id_faz_fallback_para_claim_upn():
    upn = resolver_email_autenticado(
        None,
        None,
        settings=_settings(auth_mode="entra_id"),
        client_principal_name="   ",
        client_principal=_client_principal(
            {"typ": "name", "val": "Nome Fictício"},
            {"typ": "upn", "val": "USUARIO.TESTE@DOMINIO-EXEMPLO.COM"},
        ),
    )

    assert upn == "USUARIO.TESTE@DOMINIO-EXEMPLO.COM"


@pytest.mark.parametrize(
    "principal",
    [None, "", "base64-invalido", _client_principal({"typ": "sub", "val": "123"})],
)
def test_entra_id_sem_upn_retorna_401(principal):
    with pytest.raises(HTTPException) as exc:
        resolver_email_autenticado(
            None,
            None,
            settings=_settings(auth_mode="entra_id"),
            client_principal=principal,
        )

    assert exc.value.status_code == 401


def test_dependency_global_captura_header_easy_auth():
    settings = _settings(auth_mode="entra_id")
    app = FastAPI(dependencies=[Depends(capturar_cabecalhos_easy_auth)])

    @app.get("/identidade")
    def identidade():
        return {
            "upn": resolver_email_autenticado(None, None, settings=settings)
        }

    resposta = TestClient(app).get(
        "/identidade",
        headers={
            "X-MS-CLIENT-PRINCIPAL-NAME": "conta.ficticia@biosintetica.com.br"
        },
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "upn": "conta.ficticia@biosintetica.com.br"
    }


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
