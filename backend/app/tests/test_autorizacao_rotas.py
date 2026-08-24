"""Testes de autorização das rotas de negócio.

Contexto. Até 04/08/2026 o portal emitia um token no login que nenhuma rota
conferia. Bastava informar o e-mail de outro propagandista por query string
para consultar os dados dele, sem senha e sem token. As rotas gerenciais eram
ainda mais abertas: recebiam `gd_email` e não olhavam autenticação alguma.

Estes testes fixam o comportamento esperado com `AUTH_MODE=senha`:

- sem token, nenhuma rota de negócio responde;
- com token válido, a identidade vem do token;
- o e-mail informado por query é ignorado, então não dá para se passar por
  outra pessoa mantendo o próprio token.
"""

from typing import Optional
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.app.auth import sessao as modulo_sessao
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.config import Settings

SEGREDO = "z" * 48

IDENTIDADE = modulo_sessao.Identidade(
    email="aline.garcia@ache.com.br",
    setor="010103020856",
    nome="ALINE GARCIA",
)


@pytest.fixture
def modo_senha() -> Settings:
    return Settings(auth_mode="senha", sessao_jwt_secret=SEGREDO, sessao_token_minutos=60)


@pytest.fixture
def token_valido(modo_senha) -> str:
    token, _ = modulo_sessao.criar_token(IDENTIDADE, modo_senha)
    return token


def cabecalho(token: str) -> str:
    return f"Bearer {token}"


# ------------------------------------------------------- sem token, sem acesso


@pytest.mark.parametrize(
    "authorization, email_informado",
    [
        (None, "aline.garcia@ache.com.br"),
        (None, None),
        ("", "aline.garcia@ache.com.br"),
        ("Basic YWJjOjEyMw==", "aline.garcia@ache.com.br"),
        ("Bearer", "aline.garcia@ache.com.br"),
    ],
)
def test_sem_token_valido_nao_resolve_identidade(modo_senha, authorization, email_informado):
    """Informar o e-mail por query não substitui a sessão."""
    with pytest.raises(HTTPException) as erro:
        resolver_email_autenticado(authorization, email_informado, modo_senha)
    assert erro.value.status_code == 401


def test_token_de_outro_segredo_e_recusado(modo_senha):
    outro = Settings(auth_mode="senha", sessao_jwt_secret="w" * 48)
    token, _ = modulo_sessao.criar_token(IDENTIDADE, outro)

    with pytest.raises(HTTPException) as erro:
        resolver_email_autenticado(cabecalho(token), None, modo_senha)
    assert erro.value.status_code == 401


def test_token_adulterado_e_recusado(modo_senha, token_valido):
    partes = token_valido.split(".")
    adulterado = f"{partes[0]}.{partes[1]}.{'a' * len(partes[2])}"

    with pytest.raises(HTTPException) as erro:
        resolver_email_autenticado(cabecalho(adulterado), None, modo_senha)
    assert erro.value.status_code == 401


# ------------------------------------------------------ com token, identidade


def test_token_valido_devolve_o_email_da_sessao(modo_senha, token_valido):
    assert resolver_email_autenticado(cabecalho(token_valido), None, modo_senha) == (
        "aline.garcia@ache.com.br"
    )


def test_email_da_query_nao_sobrepoe_o_token(modo_senha, token_valido):
    """Com sessão da Aline, pedir dados como se fosse outra pessoa não funciona."""
    resolvido = resolver_email_autenticado(
        cabecalho(token_valido), "bibiana.nozari@ache.com.br", modo_senha
    )
    assert resolvido == "aline.garcia@ache.com.br"


def test_token_expirado_e_recusado(modo_senha):
    expirado = Settings(
        auth_mode="senha", sessao_jwt_secret=SEGREDO, sessao_token_minutos=-1
    )
    token, _ = modulo_sessao.criar_token(IDENTIDADE, expirado)

    with pytest.raises(HTTPException) as erro:
        resolver_email_autenticado(cabecalho(token), None, modo_senha)
    assert erro.value.status_code == 401


# ------------------------------------------------------------- outros modos


def test_modo_entra_id_continua_usando_o_fluxo_corporativo():
    """Trocar AUTH_MODE não pode desligar a validação do token corporativo."""
    settings = Settings(auth_mode="entra_id", auth_require_jwt=True, auth0_domain="x.auth0.com")

    with pytest.raises(HTTPException) as erro:
        resolver_email_autenticado(None, "aline.garcia@ache.com.br", settings)
    assert erro.value.status_code == 401


def test_modo_local_aceita_email_cru():
    """Comportamento preservado para desenvolvimento local."""
    settings = Settings(auth_mode="local", auth_require_jwt=False)
    assert resolver_email_autenticado(None, "aline.garcia@ache.com.br", settings) == (
        "aline.garcia@ache.com.br"
    )


# ------------------------------------------------------- rotas gerenciais


def test_gerencial_exige_sessao(modo_senha):
    """As três rotas gerenciais passaram a resolver identidade pela sessão."""
    from backend.app.routers.gerencial import _gd_autenticado

    with patch("backend.app.routers.gerencial.resolver_email_autenticado") as resolvedor:
        resolvedor.side_effect = HTTPException(status_code=401, detail="Sessão ausente.")
        with pytest.raises(HTTPException) as erro:
            _gd_autenticado(None, "lucas.goncalves@ache.com.br")
    assert erro.value.status_code == 401


def test_gerencial_ignora_gd_email_informado(modo_senha, token_valido):
    from backend.app.routers.gerencial import _gd_autenticado

    with patch("backend.app.routers.gerencial.get_settings", return_value=modo_senha):
        with patch(
            "backend.app.routers.gerencial.resolver_email_autenticado",
            side_effect=lambda a, e: resolver_email_autenticado(a, e, modo_senha),
        ):
            resolvido = _gd_autenticado(cabecalho(token_valido), "outro.gd@ache.com.br")
    assert resolvido == "aline.garcia@ache.com.br"


def test_todas_as_rotas_de_negocio_recebem_authorization():
    """Guarda contra alguém adicionar rota nova sem o header de sessão."""
    import inspect

    from backend.app.routers import gerencial, recomendacoes

    for modulo in (gerencial, recomendacoes):
        for nome, funcao in inspect.getmembers(modulo, inspect.isfunction):
            if nome.startswith("_") or funcao.__module__ != modulo.__name__:
                continue
            parametros = inspect.signature(funcao).parameters
            assert "authorization" in parametros, (
                f"{modulo.__name__}.{nome} não recebe authorization e "
                "responderia sem sessão."
            )
