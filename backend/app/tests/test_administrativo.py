"""Testes do acesso administrativo (auth/administrativo.py).

Cobrem as três regras que sustentam a feature: a identidade real nunca vem do
header, a permissão é conferida sobre ela a cada chamada, e sessão de
conferência não escreve.

O banco não é tocado: `email_do_setor` e `resolver_status_acesso` são
substituídos por mock, porque o que está sob teste é a decisão de
autorização, não a consulta. `eh_administrador` lê PERFIL_ACESSO via
`resolver_status_acesso` desde a task de bloqueio de acesso (substituiu
`ADMIN_EMAILS`, removido do settings) — mockar essa função no lugar de
declarar uma lista fixa é o que mudou neste arquivo.
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
from backend.app.auth.status_acesso import StatusAcesso

ADMIN = "george.fernandes@ache.com.br"
ALHEIO = "ana.lima@ache.com.br"
SETOR = "010101020551"
EMAIL_DO_SETOR = "bibiana.nozari@ache.com.br"

_SETTINGS = SimpleNamespace(auth_mode="local")


def _mockar_status(mapa: dict[str, StatusAcesso], padrao=StatusAcesso("ATIVO", "PROPAGANDISTA")):
    """`resolver_status_acesso` mockado com resultado por identidade.

    `mapa` associa identidade (case-sensitive, como os testes já chamam) ao
    `StatusAcesso` que deve devolver; qualquer identidade fora do mapa cai no
    `padrao` (ATIVO/PROPAGANDISTA, isto é, "existe mas não é admin" — o caso
    mais comum de não precisar declarar em todo teste).
    """
    def _resolver(identidade, settings=None):
        return mapa.get(identidade, padrao)

    return patch("backend.app.auth.status_acesso.resolver_status_acesso", side_effect=_resolver)


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
# Substituiu ADMIN_EMAILS: agora é PERFIL_ACESSO em tb_perfil_portal, via
# resolver_status_acesso (mesma consulta de identidade dupla da checagem de
# STATUS_ACESSO).


def test_propagandista_nao_e_administrador():
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "PROPAGANDISTA")}):
        assert eh_administrador(ADMIN, _SETTINGS) is False


def test_perfil_administrador_habilita():
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "ADMINISTRADOR")}):
        assert eh_administrador(ADMIN, _SETTINGS) is True


def test_perfil_administrador_bloqueado_continua_sendo_administrador():
    """`eh_administrador` só olha PERFIL_ACESSO — não é o gate de acesso.

    Quem bloqueia um administrador BLOQUEADO é `exigir_acesso_liberado`,
    chamado antes disto em `resolver_email_autenticado`. Confundir os dois
    faria um administrador bloqueado nunca chegar a este ponto (correto),
    mas por um motivo diferente do que esta função decide.
    """
    with _mockar_status({ADMIN: StatusAcesso("BLOQUEADO", "ADMINISTRADOR")}):
        assert eh_administrador(ADMIN, _SETTINGS) is True


def test_sem_linha_em_tb_perfil_portal_nao_e_administrador():
    with _mockar_status({ADMIN: StatusAcesso(None, None)}):
        assert eh_administrador(ADMIN, _SETTINGS) is False


def test_identidade_vazia_nao_e_administrador():
    assert eh_administrador("", _SETTINGS) is False


# ------------------------------------------------------- personificacao ----


def test_sem_header_devolve_identidade_real():
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "ADMINISTRADOR")}):
        assert aplicar_personificacao(ADMIN, _SETTINGS) == ADMIN


def test_administrador_com_header_assume_o_setor():
    registrar_alvo(SETOR)
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "ADMINISTRADOR")}):
        with patch.object(administrativo, "email_do_setor", return_value=EMAIL_DO_SETOR) as m:
            assert aplicar_personificacao(ADMIN, _SETTINGS) == EMAIL_DO_SETOR
        m.assert_called_once_with(SETOR)


def test_nao_administrador_tem_o_header_ignorado():
    """O pedido é descartado, não recusado: a resposta é a sessão normal dele.

    Recusar com erro entregaria a informação de que existe um modo
    administrativo e de que aquele setor existe.
    """
    registrar_alvo(SETOR)
    with _mockar_status({ALHEIO: StatusAcesso("ATIVO", "PROPAGANDISTA")}):
        with patch.object(administrativo, "email_do_setor") as m:
            assert aplicar_personificacao(ALHEIO, _SETTINGS) == ALHEIO
        m.assert_not_called()


def test_setor_inexistente_devolve_404():
    registrar_alvo("setor-que-nao-existe")
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "ADMINISTRADOR")}):
        with patch.object(administrativo, "email_do_setor", return_value=None):
            with pytest.raises(HTTPException) as erro:
                aplicar_personificacao(ADMIN, _SETTINGS)
    assert erro.value.status_code == 404


def test_header_em_branco_nao_personifica():
    registrar_alvo("   ")
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "ADMINISTRADOR")}):
        with patch.object(administrativo, "email_do_setor") as m:
            assert aplicar_personificacao(ADMIN, _SETTINGS) == ADMIN
        m.assert_not_called()


# ------------------------------------------- integracao com o resolvedor ----


def test_resolver_aplica_personificacao_por_padrao():
    from backend.app.auth.jwt_auth import resolver_email_autenticado

    registrar_alvo(SETOR)
    settings = SimpleNamespace(auth_mode="local", auth_require_jwt=False)
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "ADMINISTRADOR")}):
        with patch.object(administrativo, "email_do_setor", return_value=EMAIL_DO_SETOR):
            assert resolver_email_autenticado(None, ADMIN, settings) == EMAIL_DO_SETOR


def test_resolver_com_aplicar_admin_false_devolve_identidade_real():
    """É o que os endpoints administrativos usam para não perder a própria permissão."""
    from backend.app.auth.jwt_auth import resolver_email_autenticado

    registrar_alvo(SETOR)
    settings = SimpleNamespace(auth_mode="local", auth_require_jwt=False)
    with _mockar_status({ADMIN: StatusAcesso("ATIVO", "ADMINISTRADOR")}):
        with patch.object(administrativo, "email_do_setor") as m:
            assert (
                resolver_email_autenticado(None, ADMIN, settings, aplicar_admin=False)
                == ADMIN
            )
        m.assert_not_called()


def test_resolver_bloqueia_antes_de_personificar():
    """A checagem de STATUS_ACESSO roda antes da personificação, mesmo para
    quem tem PERFIL_ACESSO=ADMINISTRADOR — ver auth/jwt_auth.py."""
    from backend.app.auth.jwt_auth import resolver_email_autenticado

    registrar_alvo(SETOR)
    settings = SimpleNamespace(auth_mode="local", auth_require_jwt=False)
    with _mockar_status({ADMIN: StatusAcesso("BLOQUEADO", "ADMINISTRADOR")}):
        with patch.object(administrativo, "email_do_setor") as m:
            with pytest.raises(HTTPException) as erro:
                resolver_email_autenticado(None, ADMIN, settings)
        m.assert_not_called()
    assert erro.value.status_code == 403
    assert erro.value.detail["codigo"] == "ACESSO_BLOQUEADO"


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
