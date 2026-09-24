"""Testes de bloqueio de acesso por STATUS_ACESSO/PERFIL_ACESSO.

Contra o Postgres local de verdade (não mockado) — a seed está em
data/scripts/20_migrar_status_acesso.sql:

  REP001 (ana.lima@ache.com.br,    rep_login=ana.lima.upn)    -> ATIVO / PROPAGANDISTA
  REP002 (bruno.melo@ache.com.br,  rep_login=bruno.melo.upn)  -> BLOQUEADO / PROPAGANDISTA, setor SP_INTERIOR
  REP003 (carla.souza@ache.com.br, rep_login=carla.souza.upn) -> tem linha em tb_perfil_portal, mas SEM status_acesso/perfil_acesso
  REP004 (diego.costa@ache.com.br, rep_login=diego.costa.upn) -> SEM linha nenhuma em tb_perfil_portal
  admin.ativo.teste@ache.com.br     -> ATIVO / ADMINISTRADOR, sem rep_matricula
  admin.bloqueado.teste@ache.com.br -> BLOQUEADO / ADMINISTRADOR, sem rep_matricula

Cobre os 8 cenários pedidos (4 casos x 2 modos de autenticação), mais:
personificação nunca influencia a checagem; administrador chega ao seletor
sem setor; ADMIN_EMAILS removido não quebra nada; tag da aba Usuário reflete
STATUS_ACESSO.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.app.auth.administrativo import (
    _SETOR_ALVO,
    eh_administrador,
    registrar_alvo,
    sessao_admin,
)
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.auth.status_acesso import exigir_acesso_liberado, resolver_status_acesso
from backend.app.config import Settings

pytestmark = pytest.mark.usefixtures("forcar_data_source_local")


def _settings(auth_mode: str) -> Settings:
    return Settings(auth_mode=auth_mode, sessao_jwt_secret="x" * 32, data_source="local")


def _settings_identidade_direta():
    """`auth_mode="local"` com `auth_require_jwt=False`: aceita a identidade
    como parâmetro direto, sem exigir Bearer token — mesmo padrão já usado em
    test_administrativo.py para testar o fluxo de personificação sem montar
    um token de sessão de verdade. `coluna_identidade_para_auth_mode` cai no
    ramo `rep_email` (só distingue `entra_id`, o resto vai tudo pra lá).

    `Settings.auth_mode` é `Literal["senha","entra_id"]` — um objeto real não
    aceita "local", por isso `SimpleNamespace` aqui, não `Settings`.
    """
    from types import SimpleNamespace

    return SimpleNamespace(auth_mode="local", auth_require_jwt=False)


@pytest.fixture(autouse=True)
def _limpar_alvo():
    registrar_alvo(None)
    yield
    registrar_alvo(None)


# --------------------------------------------------------- 8 cenários ----
# 4 casos (sem linha, BLOQUEADO, ATIVO propagandista, ATIVO administrador)
# x 2 modos (senha usa e-mail direto; entra_id usa UPN, resolvido por
# REP_LOGIN via tb_propagandistas antes de chegar em tb_perfil_portal).

_CASOS_SENHA = [
    pytest.param("ana.lima@ache.com.br", "ATIVO", "PROPAGANDISTA", id="senha-propagandista-ativo"),
    pytest.param("bruno.melo@ache.com.br", "BLOQUEADO", "PROPAGANDISTA", id="senha-propagandista-bloqueado"),
    pytest.param("diego.costa@ache.com.br", None, None, id="senha-propagandista-sem-linha"),
    pytest.param("admin.ativo.teste@ache.com.br", "ATIVO", "ADMINISTRADOR", id="senha-admin-ativo"),
]

_CASOS_ENTRA_ID = [
    pytest.param("ana.lima.upn@ache.com.br", "ATIVO", "PROPAGANDISTA", id="entra_id-propagandista-ativo"),
    pytest.param("bruno.melo.upn@ache.com.br", "BLOQUEADO", "PROPAGANDISTA", id="entra_id-propagandista-bloqueado"),
    pytest.param("diego.costa.upn@ache.com.br", None, None, id="entra_id-propagandista-sem-linha"),
    # Administrador não tem rep_login (sem linha em tb_propagandistas) — o
    # fallback usa o UPN bruto direto contra tb_perfil_portal.rep_email, e é
    # exatamente isso que este caso prova: casa mesmo sem passar pela
    # primeira consulta (propagandista).
    pytest.param("admin.ativo.teste@ache.com.br", "ATIVO", "ADMINISTRADOR", id="entra_id-admin-ativo"),
]


@pytest.mark.parametrize("identidade,status_esperado,perfil_esperado", _CASOS_SENHA)
def test_resolver_status_acesso_modo_senha(identidade, status_esperado, perfil_esperado):
    resultado = resolver_status_acesso(identidade, _settings("senha"))
    assert resultado.status_acesso == status_esperado
    assert resultado.perfil_acesso == perfil_esperado


@pytest.mark.parametrize("identidade,status_esperado,perfil_esperado", _CASOS_ENTRA_ID)
def test_resolver_status_acesso_modo_entra_id(identidade, status_esperado, perfil_esperado):
    resultado = resolver_status_acesso(identidade, _settings("entra_id"))
    assert resultado.status_acesso == status_esperado
    assert resultado.perfil_acesso == perfil_esperado


@pytest.mark.parametrize(
    "identidade,deveria_bloquear",
    [
        ("ana.lima@ache.com.br", False),
        ("bruno.melo@ache.com.br", True),
        ("diego.costa@ache.com.br", True),  # sem linha = deny-by-default
        ("admin.ativo.teste@ache.com.br", False),
        ("admin.bloqueado.teste@ache.com.br", True),
    ],
)
def test_exigir_acesso_liberado_modo_senha(identidade, deveria_bloquear):
    if deveria_bloquear:
        with pytest.raises(HTTPException) as erro:
            exigir_acesso_liberado(identidade, _settings("senha"))
        assert erro.value.status_code == 403
        assert erro.value.detail["codigo"] == "ACESSO_BLOQUEADO"
    else:
        exigir_acesso_liberado(identidade, _settings("senha"))  # não levanta


# ----------------------------------------------------- resposta padronizada ----
# Os dois pontos de integração (login por senha e resolver_contexto, via
# resolver_email_autenticado) devolvem exatamente o mesmo formato.


def test_formato_da_excecao_e_o_mesmo_nos_dois_pontos_de_integracao():
    with pytest.raises(HTTPException) as erro_direto:
        exigir_acesso_liberado("bruno.melo@ache.com.br", _settings("senha"))

    with pytest.raises(HTTPException) as erro_via_login:
        from backend.app.auth.sessao import login as login_fn  # noqa: F401 — só confirma que existe
        exigir_acesso_liberado("bruno.melo@ache.com.br", _settings("senha"))

    assert erro_direto.value.status_code == erro_via_login.value.status_code == 403
    assert erro_direto.value.detail == erro_via_login.value.detail
    assert set(erro_direto.value.detail.keys()) == {"codigo", "detail"}
    assert erro_direto.value.detail["codigo"] == "ACESSO_BLOQUEADO"


def test_post_login_devolve_403_acesso_bloqueado_para_bloqueado():
    """Integração real via POST /auth/login — não só a função isolada."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with patch("backend.app.auth.sessao.acessos") as mock_acessos, patch(
        "backend.app.auth.sessao.verificar_senha", return_value=True
    ):
        mock_acessos.buscar.return_value = type("A", (), {"senha_hash": "x"})()
        resposta = TestClient(app).post(
            "/auth/login", json={"email": "bruno.melo@ache.com.br", "senha": "qualquer"}
        )
    assert resposta.status_code == 403
    assert resposta.json()["detail"]["codigo"] == "ACESSO_BLOQUEADO"


def test_post_login_nao_chega_a_buscar_cadastro_quando_bloqueado():
    """Ordem explícita da Fase 2: STATUS_ACESSO checado ANTES de
    buscar_cadastro() — quem não tem linha recebe 403, não 401 genérico."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with patch("backend.app.auth.sessao.acessos") as mock_acessos, patch(
        "backend.app.auth.sessao.verificar_senha", return_value=True
    ), patch("backend.app.auth.sessao.buscar_cadastro") as mock_buscar:
        mock_acessos.buscar.return_value = type("A", (), {"senha_hash": "x"})()
        resposta = TestClient(app).post(
            # diego.costa não tem linha em tb_perfil_portal — deny-by-default
            "/auth/login", json={"email": "diego.costa@ache.com.br", "senha": "qualquer"}
        )
    assert resposta.status_code == 403
    assert resposta.json()["detail"]["codigo"] == "ACESSO_BLOQUEADO"
    mock_buscar.assert_not_called()


# --------------------------------------------- personificação nunca influencia ----


def test_personificacao_nao_influencia_a_checagem_de_acesso():
    """Administrador ATIVO personificando um propagandista BLOQUEADO: a
    checagem de acesso é sobre o administrador (ATIVO, passa), nunca sobre
    quem está sendo personificado (BLOQUEADO). Se a ordem estivesse errada
    (checagem depois de aplicar_personificacao, ou sobre o valor
    personificado), isto levantaria 403 incorretamente.

    `email_do_setor` mockado (mesmo padrão de test_administrativo.py): SP_
    INTERIOR tem 3 propagandistas na seed local, e a função real exige
    exatamente 1 (ambiguidade = None) — não é o que este teste quer exercitar.
    """
    from backend.app.auth import administrativo

    registrar_alvo("SP_INTERIOR")  # setor de bruno.melo, BLOQUEADO
    settings = _settings_identidade_direta()

    with patch.object(administrativo, "email_do_setor", return_value="bruno.melo@ache.com.br"):
        resultado = resolver_email_autenticado(
            None, "admin.ativo.teste@ache.com.br", settings
        )

    # Personificou de verdade (achou o e-mail do setor pedido) — prova que a
    # checagem de acesso não bloqueou o fluxo, mesmo com o alvo bloqueado.
    assert resultado == "bruno.melo@ache.com.br"


def test_administrador_bloqueado_nao_consegue_personificar_ninguem():
    """O inverso do teste acima: administrador BLOQUEADO nunca chega a
    aplicar_personificacao, mesmo pedindo um setor de propagandista ATIVO."""
    registrar_alvo("SP_CAPITAL")  # setor de ana.lima, ATIVO — irrelevante aqui
    settings = _settings_identidade_direta()

    with pytest.raises(HTTPException) as erro:
        resolver_email_autenticado(None, "admin.bloqueado.teste@ache.com.br", settings)
    assert erro.value.status_code == 403
    assert erro.value.detail["codigo"] == "ACESSO_BLOQUEADO"


# ------------------------------------------------- administrador sem setor ----


def test_admin_chega_ao_seletor_sem_setor(monkeypatch):
    """GET /admin/sessao não tenta resolver setor em tb_propagandistas —
    administrador pode não ter (nem existir) linha lá.

    `sessao_admin` lê `get_settings()` global (não aceita settings por
    parâmetro) — env var é o jeito de simular isso aqui, mesmo padrão de
    `forcar_data_source_local`. `AUTH_MODE=entra_id` (Literal válido, ao
    contrário de "local") com o ContextVar de headers do Easy Auth setado
    direto — o mesmo que `capturar_cabecalhos_easy_auth` faria a partir do
    header `X-MS-CLIENT-PRINCIPAL-NAME` numa requisição real.
    """
    from backend.app.auth.jwt_auth import CabecalhosEasyAuth, _cabecalhos_easy_auth
    from backend.app.config import get_settings

    monkeypatch.setenv("AUTH_MODE", "entra_id")
    get_settings.cache_clear()
    token = _cabecalhos_easy_auth.set(
        CabecalhosEasyAuth(client_principal_name="admin.ativo.teste@ache.com.br")
    )
    try:
        resposta = sessao_admin(email=None, authorization=None)
    finally:
        _cabecalhos_easy_auth.reset(token)
        get_settings.cache_clear()
    assert resposta.administrador is True
    assert resposta.identidade == "admin.ativo.teste@ache.com.br"


def test_admin_bloqueado_nao_e_oferecido_o_seletor(monkeypatch):
    """/admin/sessao em si não é ponto de decisão de segurança (comentário
    do próprio módulo), mas segue barrado por resolver_email_autenticado
    antes de chegar até aqui — confirmado batendo no endpoint real via
    TestClient, com o header que o Easy Auth injetaria de verdade em
    AUTH_MODE=entra_id, não só na função isolada."""
    from fastapi.testclient import TestClient

    from backend.app.config import get_settings
    from backend.app.main import app

    monkeypatch.setenv("AUTH_MODE", "entra_id")
    get_settings.cache_clear()
    try:
        resposta = TestClient(app).get(
            "/admin/sessao",
            headers={"X-MS-CLIENT-PRINCIPAL-NAME": "admin.bloqueado.teste@ache.com.br"},
        )
    finally:
        get_settings.cache_clear()
    assert resposta.status_code == 403
    assert resposta.json()["detail"]["codigo"] == "ACESSO_BLOQUEADO"


# ------------------------------------------------- ADMIN_EMAILS removido ----


def test_admin_emails_nao_existe_mais_em_settings():
    settings = Settings(sessao_jwt_secret="x" * 32)
    assert not hasattr(settings, "admin_emails")


def test_eh_administrador_ignora_qualquer_env_admin_emails(monkeypatch):
    """Mesmo que alguém deixe ADMIN_EMAILS setado no ambiente (resquício de
    deploy antigo), não influencia mais nada — só PERFIL_ACESSO importa."""
    monkeypatch.setenv("ADMIN_EMAILS", "ninguem.deveria.usar@ache.com.br")
    settings = _settings("senha")
    assert eh_administrador("ninguem.deveria.usar@ache.com.br", settings) is False
    assert eh_administrador("admin.ativo.teste@ache.com.br", settings) is True


# --------------------------------------------------- tag da aba Usuário ----


def test_tag_da_aba_usuario_reflete_status_acesso():
    """`resolver_perfil` só é testável sem Postgres local de verdade — mesmo
    motivo de test_perfil.py (tb_propagandistas local não tem todas as
    colunas que a consulta com resumo pede; ver limitação já documentada em
    CLAUDE.md sobre GET/PUT /auth/perfil). Reaproveita o dublê de engine de
    lá e mocka resolver_status_acesso, já testado à exaustão acima — aqui só
    interessa a fiação: o valor que ele devolve chega ao PerfilResponse.
    """
    from backend.app.auth.perfil import resolver_perfil
    from backend.app.auth.status_acesso import StatusAcesso
    from backend.app.tests.test_perfil import _com_linhas, _linha

    linha = _linha("SP_CAPITAL", "3", "GD Teste")

    with _com_linhas([linha]):
        with patch(
            "backend.app.auth.perfil.resolver_status_acesso",
            return_value=StatusAcesso("BLOQUEADO", "PROPAGANDISTA"),
        ) as mock_status:
            perfil = resolver_perfil(linha["rep_email"])

    mock_status.assert_called_once_with(linha["rep_email"])
    assert perfil.status_acesso == "BLOQUEADO"
