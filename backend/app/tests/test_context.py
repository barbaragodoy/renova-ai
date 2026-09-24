"""
Testes de resolver_contexto.

Os testes de SETOR_RESOLVIDO e PROPAGANDISTA_NAO_ENCONTRADO usam dados reais
do banco local (requer PostgreSQL rodando via docker compose up -d).

Schema real confirmado em acheinfo_dev.renovai.tb_propagandistas: não existe
coluna de status ativo/inativo (ausência de linha = não encontrado) e não há
duplicidade de e-mail nos 2156 registros reais. Por isso o teste de
IDENTIDADE_AMBIGUA é necessariamente mockado — não é reprodutível com dado
real hoje, mas a lógica defensiva é mantida no código.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from backend.app.auth.context import (
    StatusContexto,
    coluna_identidade_para_auth_mode,
    extrair_login_do_upn,
    resolver_contexto,
)

# Este arquivo testa contra a seed do Postgres local — deve continuar
# passando independente do DATA_SOURCE configurado no .env real (que pode
# estar em 'databricks' para rodar a API/test_context_integration.py contra
# o Databricks de verdade). Fixture compartilhada em conftest.py.
pytestmark = pytest.mark.usefixtures("forcar_data_source_local")

# E-mail inserido em 02_populate_propagandistas.sql (domínio ache.com.br)
EMAIL_ACHE = "ana.lima@ache.com.br"
# E-mail que não existe no banco
EMAIL_INEXISTENTE = "fulano.naoexiste@ache.com.br"


def test_extrai_login_de_upn_ache():
    assert extrair_login_do_upn("usuario.teste@ache.com.br") == "usuario.teste"


def test_extrai_login_sem_assumir_dominio():
    assert (
        extrair_login_do_upn("usuario.teste@biosintetica.com.br")
        == "usuario.teste"
    )


def test_extrai_login_preservando_caixa_para_comparacao_no_banco():
    assert (
        extrair_login_do_upn("USUARIO.TESTE@DOMINIO-EXEMPLO.COM")
        == "USUARIO.TESTE"
    )


def test_coluna_de_identidade_depende_do_auth_mode():
    assert coluna_identidade_para_auth_mode(
        SimpleNamespace(auth_mode="senha")
    ) == "rep_email"
    assert coluna_identidade_para_auth_mode(
        SimpleNamespace(auth_mode="entra_id")
    ) == "rep_login"


def test_entra_id_resolve_por_rep_login_customizado_case_insensitive():
    registro = {
        "rep_email": "caixa.portal@ache.com.br",
        "rep_login": "USUARIO.TESTE",
        "rep_matricula": "REP-FICTICIO",
        "setor": "SETOR_TESTE",
        "rep_nome": "Pessoa Fictícia",
    }
    execucao = {}

    class FakeConn:
        def execute(self, query, params):
            execucao["sql"] = str(query)
            execucao["params"] = params
            resultado = MagicMock()
            if params["email"].lower() == registro["rep_login"].lower():
                resultado.fetchall.return_value = [
                    MagicMock(
                        rep_matricula=registro["rep_matricula"],
                        setor=registro["setor"],
                        rep_nome=registro["rep_nome"],
                    )
                ]
            else:
                resultado.fetchall.return_value = []
            return resultado

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("backend.app.auth.context._get_engine") as engine:
        engine.return_value.connect.return_value = FakeConn()
        ctx = resolver_contexto(
            "usuario.teste@biosintetica.com.br",
            coluna_identidade="rep_login",
        )

    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula == "REP-FICTICIO"
    assert "LOWER(rep_login) = LOWER(:email)" in execucao["sql"]
    assert execucao["params"] == {"email": "usuario.teste"}


def test_coluna_de_identidade_fora_da_whitelist_e_rejeitada():
    with pytest.raises(ValueError, match="Coluna de identidade não permitida"):
        resolver_contexto(
            "usuario.teste",
            coluna_identidade="rep_matricula",
        )


@pytest.mark.requer_banco
def test_setor_resolvido_dominio_ache():
    ctx = resolver_contexto(EMAIL_ACHE)
    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula is not None
    assert ctx.setor is not None
    assert ctx.nome is not None


def test_setor_resolvido_dominio_biosintetica(monkeypatch):
    """
    Domínio biosintetica.com.br confirmado por George (PM Simbiox) como parte
    do escopo (mesmo grupo econômico do ache.com.br). Mockado porque a massa
    de dados local (02_populate_propagandistas.sql) só tem e-mails
    @ache.com.br; em produção o match é o mesmo, apenas contra REP_EMAIL.
    """
    row = {"rep_matricula": "REP123", "setor": "SP_CAPITAL", "rep_nome": "Carlos Bio"}

    class FakeConn:
        def execute(self, *a, **kw):
            fake = MagicMock()
            fake_row = MagicMock(**row)
            fake_row.__getitem__ = lambda s, k: row[k]
            fake.fetchall.return_value = [fake_row]
            return fake

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("backend.app.auth.context._get_engine") as mock_engine:
        mock_engine.return_value.connect.return_value = FakeConn()
        ctx = resolver_contexto("carlos.bio@biosintetica.com.br")

    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula == "REP123"
    assert ctx.setor == "SP_CAPITAL"
    assert ctx.nome == "Carlos Bio"


@pytest.mark.requer_banco
def test_propagandista_nao_encontrado():
    ctx = resolver_contexto(EMAIL_INEXISTENTE)
    assert ctx.status == StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO
    assert ctx.mensagem is not None
    assert ctx.matricula is None


def test_identidade_ambigua(monkeypatch):
    """
    Simula dois cadastros para o mesmo e-mail. Cenário defensivo que NÃO
    ocorre no dado real hoje (2156/2156 e-mails únicos confirmado) — só
    validável via massa sintética/mock, como aqui.
    """
    row1 = {"rep_matricula": "REP001", "setor": "SP_INTERIOR", "rep_nome": "Ana"}
    row2 = {"rep_matricula": "REP999", "setor": "RJ_CAPITAL", "rep_nome": "Ana Clone"}

    class FakeConn:
        def execute(self, *a, **kw):
            fake = MagicMock()
            fake.fetchall.return_value = [MagicMock(**row1), MagicMock(**row2)]
            fake.fetchall.return_value[0].__getitem__ = lambda s, k: row1[k]
            fake.fetchall.return_value[1].__getitem__ = lambda s, k: row2[k]
            return fake

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("backend.app.auth.context._get_engine") as mock_engine:
        mock_engine.return_value.connect.return_value = FakeConn()
        ctx = resolver_contexto("ambiguo@ache.com.br")

    assert ctx.status == StatusContexto.IDENTIDADE_AMBIGUA
    assert ctx.mensagem is not None
