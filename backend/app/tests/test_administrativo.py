"""Testes do acesso administrativo (auth/administrativo.py).

Cobrem as três regras que sustentam a feature: a identidade real nunca vem do
header, a permissão é conferida sobre ela a cada chamada, e sessão de
conferência não escreve.

O banco não é tocado: `email_do_setor` é substituído por mock, porque o que está
sob teste é a decisão de autorização, não a consulta.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.app.auth import administrativo
from backend.app.auth.administrativo import (
    HEADER_VER_COMO,
    METODOS_SOMENTE_LEITURA,
    aplicar_personificacao,
    eh_administrador,
    registrar_alvo,
)

ADMIN = "george.fernandes@ache.com.br"
ALHEIO = "ana.lima@ache.com.br"
SETOR = "010101020551"
EMAIL_DO_SETOR = "bibiana.nozari@ache.com.br"


def _settings(admin_emails: str = ADMIN):
    return SimpleNamespace(auth_mode="local", admin_emails=admin_emails)


@pytest.fixture(autouse=True)
def _limpar_alvo():
    """Zera o ContextVar entre testes.

    Sem isto, um teste que registra o alvo contamina o seguinte, porque o
    ContextVar sobrevive dentro da mesma task do pytest.
    """
    registrar_alvo(None)
    yield
    registrar_alvo(None)


# --------------------------------------------------------------- lista ----


def test_lista_vazia_nao_tem_administrador():
    assert eh_administrador(ADMIN, _settings(admin_emails="")) is False


def test_lista_ignora_caixa_e_espaco():
    settings = _settings(admin_emails="  GEORGE.FERNANDES@ACHE.COM.BR , outro@ache.com.br ")
    assert eh_administrador(ADMIN, settings) is True


def test_lista_aceita_login_corporativo_alem_do_email():
    """Enquanto a claim do Entra ID não estiver confirmada, as duas formas valem."""
    settings = _settings(admin_emails=f"{ADMIN},gfernandes")
    assert eh_administrador("gfernandes", settings) is True
    assert eh_administrador(ADMIN, settings) is True


def test_settings_sem_o_campo_nao_quebra():
    """Mocks antigos de settings não declaram `admin_emails`; o padrão é negar."""
    assert eh_administrador(ADMIN, SimpleNamespace(auth_mode="local")) is False


# ------------------------------------------------------- personificacao ----


def test_sem_header_devolve_identidade_real():
    assert aplicar_personificacao(ADMIN, _settings()) == ADMIN


def test_administrador_com_header_assume_o_setor():
    registrar_alvo(SETOR)
    with patch.object(administrativo, "email_do_setor", return_value=EMAIL_DO_SETOR) as m:
        assert aplicar_personificacao(ADMIN, _settings()) == EMAIL_DO_SETOR
    m.assert_called_once_with(SETOR)


def test_nao_administrador_tem_o_header_ignorado():
    """O pedido é descartado, não recusado: a resposta é a sessão normal dele.

    Recusar com erro entregaria a informação de que existe um modo
    administrativo e de que aquele setor existe.
    """
    registrar_alvo(SETOR)
    with patch.object(administrativo, "email_do_setor") as m:
        assert aplicar_personificacao(ALHEIO, _settings()) == ALHEIO
    m.assert_not_called()


def test_setor_inexistente_devolve_404():
    registrar_alvo("setor-que-nao-existe")
    with patch.object(administrativo, "email_do_setor", return_value=None):
        with pytest.raises(HTTPException) as erro:
            aplicar_personificacao(ADMIN, _settings())
    assert erro.value.status_code == 404


def test_header_em_branco_nao_personifica():
    registrar_alvo("   ")
    with patch.object(administrativo, "email_do_setor") as m:
        assert aplicar_personificacao(ADMIN, _settings()) == ADMIN
    m.assert_not_called()


# ------------------------------------------- integracao com o resolvedor ----


def test_resolver_aplica_personificacao_por_padrao():
    from backend.app.auth.jwt_auth import resolver_email_autenticado

    registrar_alvo(SETOR)
    settings = SimpleNamespace(
        auth_mode="local", auth_require_jwt=False, admin_emails=ADMIN
    )
    with patch.object(administrativo, "email_do_setor", return_value=EMAIL_DO_SETOR):
        assert resolver_email_autenticado(None, ADMIN, settings) == EMAIL_DO_SETOR


def test_resolver_com_aplicar_admin_false_devolve_identidade_real():
    """É o que os endpoints administrativos usam para não perder a própria permissão."""
    from backend.app.auth.jwt_auth import resolver_email_autenticado

    registrar_alvo(SETOR)
    settings = SimpleNamespace(
        auth_mode="local", auth_require_jwt=False, admin_emails=ADMIN
    )
    with patch.object(administrativo, "email_do_setor") as m:
        assert (
            resolver_email_autenticado(None, ADMIN, settings, aplicar_admin=False)
            == ADMIN
        )
    m.assert_not_called()


# ------------------------------------------------------------ middleware ----


def _cliente():
    from fastapi.testclient import TestClient

    from backend.app.main import app

    return TestClient(app)


def test_middleware_recusa_escrita_com_header():
    resposta = _cliente().post(
        "/recomendacoes/1/desconsiderar",
        json={"motivo": "OUTROS", "motivo_outros_texto": "teste"},
        headers={HEADER_VER_COMO: SETOR},
    )
    assert resposta.status_code == 403
    assert "somente leitura" in resposta.json()["detail"]


def test_middleware_libera_leitura_com_header():
    """A leitura passa pelo middleware; o 401/403 que vier depois é de autenticação."""
    resposta = _cliente().get("/health", headers={HEADER_VER_COMO: SETOR})
    assert resposta.status_code == 200


def test_metodos_de_leitura_nao_incluem_escrita():
    assert METODOS_SOMENTE_LEITURA == {"GET", "HEAD", "OPTIONS"}
