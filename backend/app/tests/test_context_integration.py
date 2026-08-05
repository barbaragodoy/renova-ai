"""
Testes de integração de resolver_contexto contra o Databricks REAL
(acheinfo_dev.renovai.tb_propagandistas), via OAuth M2M do Service Principal
sp-renovai-genie-api-poc.

Só rodam com DATA_SOURCE=databricks no .env (preenchido com
DATABRICKS_CLIENT_SECRET real) — em qualquer outro valor de DATA_SOURCE,
são pulados (skip), para não quebrar `pytest` local/CI sem credenciais.

IDENTIDADE_AMBIGUA com dado real: a tb_propagandistas real tem 2156/2156
e-mails distintos (zero duplicidade) — não reproduzível nela sem escrever
na tabela de produção, o que este arquivo não faz. Em vez disso, os testes
`*_tabela_teste` abaixo usam `tb_propagandista_teste`, uma tabela dedicada
no mesmo catálogo/schema, criada especificamente para esse cenário — ver
CLAUDE.md. Eles pulam (skip) automaticamente enquanto o SP não tiver
SELECT nessa tabela ou ela ainda não tiver a massa de teste (e-mail único +
e-mail duplicado), sem quebrar a suíte.
"""
import pytest
from sqlalchemy import text

from backend.app.auth.context import resolver_contexto, StatusContexto
from backend.app.config import get_settings
from backend.app.db.databricks_connection import get_engine

pytestmark = pytest.mark.skipif(
    get_settings().data_source.lower() != "databricks",
    reason="Requer DATA_SOURCE=databricks e credenciais reais do SP no .env.",
)


def _um_email_real(domino: str) -> str:
    """Busca um e-mail real de um domínio na tabela, em vez de fixar um valor
    que pode não existir/mudar com a carga diária via ADF."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT rep_email FROM tb_propagandistas WHERE rep_email LIKE :padrao LIMIT 1"),
            {"padrao": f"%@{domino}"},
        ).fetchone()
    assert row is not None, f"Nenhum e-mail @{domino} encontrado em tb_propagandistas."
    return row.rep_email


def test_setor_resolvido_dominio_ache_real():
    email = _um_email_real("ache.com.br")
    ctx = resolver_contexto(email)
    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula is not None
    assert ctx.setor is not None
    assert ctx.nome is not None


def test_setor_resolvido_dominio_biosintetica_real():
    email = _um_email_real("biosintetica.com.br")
    ctx = resolver_contexto(email)
    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula is not None
    assert ctx.setor is not None
    assert ctx.nome is not None


def test_propagandista_nao_encontrado_real():
    ctx = resolver_contexto("fulano.naoexiste.integracao@ache.com.br")
    assert ctx.status == StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO
    assert ctx.mensagem is not None
    assert ctx.matricula is None


def test_setor_resolvido_com_email_gravado_em_maiusculo():
    """
    Regressão: 14/2156 registros reais têm rep_email gravado com alguma letra
    maiúscula (ex.: SUELEN.BRITO@ACHE.COM.BR). Auth0/Entra ID normalmente
    envia o e-mail em minúsculas — resolver_contexto() precisa achar esse
    propagandista mesmo assim (comparação via LOWER() nos dois lados).
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rep_email FROM tb_propagandistas "
                "WHERE rep_email != LOWER(rep_email) LIMIT 1"
            )
        ).fetchone()
    assert row is not None, "Nenhum e-mail com maiúsculas encontrado — bug pode já ter sido corrigido na origem."

    ctx = resolver_contexto(row.rep_email.lower())
    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula is not None


def test_setor_resolvido_tabela_teste():
    """E-mail único em tb_propagandista_teste -> SETOR_RESOLVIDO com dado real."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT rep_email FROM tb_propagandista_teste "
                    "GROUP BY rep_email HAVING COUNT(*) = 1 LIMIT 1"
                )
            ).fetchone()
    except Exception as exc:
        pytest.skip(f"tb_propagandista_teste inacessível ainda (grant/massa pendente): {exc}")

    if row is None:
        pytest.skip("Nenhum e-mail único encontrado em tb_propagandista_teste ainda.")

    ctx = resolver_contexto(row.rep_email, tabela="tb_propagandista_teste")
    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula is not None


def test_identidade_ambigua_tabela_teste():
    """E-mail duplicado em tb_propagandista_teste -> IDENTIDADE_AMBIGUA com dado real."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT rep_email FROM tb_propagandista_teste "
                    "GROUP BY rep_email HAVING COUNT(*) > 1 LIMIT 1"
                )
            ).fetchone()
    except Exception as exc:
        pytest.skip(f"tb_propagandista_teste inacessível ainda (grant/massa pendente): {exc}")

    if row is None:
        pytest.skip("Nenhum e-mail duplicado encontrado em tb_propagandista_teste ainda.")

    ctx = resolver_contexto(row.rep_email, tabela="tb_propagandista_teste")
    assert ctx.status == StatusContexto.IDENTIDADE_AMBIGUA
    assert ctx.mensagem is not None
