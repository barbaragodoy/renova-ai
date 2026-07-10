"""
Testes de resolver_contexto com dados reais do banco local.
Requer PostgreSQL rodando (docker compose up -d).
"""
import pytest
from backend.app.auth.context import resolver_contexto, StatusContexto


# E-mail de um propagandista ativo inserido em 02_populate_propagandistas.sql
EMAIL_ATIVO = "ana.silva@ache.com.br"
# E-mail que não existe no banco
EMAIL_INEXISTENTE = "fulano.naoexiste@ache.com.br"


def test_setor_resolvido():
    ctx = resolver_contexto(EMAIL_ATIVO)
    assert ctx.status == StatusContexto.SETOR_RESOLVIDO
    assert ctx.matricula is not None
    assert ctx.setor is not None
    assert ctx.cod_linha is not None
    assert ctx.nome is not None


def test_propagandista_nao_encontrado():
    ctx = resolver_contexto(EMAIL_INEXISTENTE)
    assert ctx.status == StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO
    assert ctx.mensagem is not None
    assert ctx.matricula is None


def test_identidade_ambigua(monkeypatch):
    """Simula dois cadastros ativos para o mesmo e-mail."""
    from sqlalchemy.engine import MappingResult
    from unittest.mock import MagicMock, patch

    row1 = {"rep_matricula": "REP001", "setor": "SP_INTERIOR", "cod_linha": "CARDIO", "rep_nome": "Ana"}
    row2 = {"rep_matricula": "REP999", "setor": "RJ_CAPITAL", "cod_linha": "SNC", "rep_nome": "Ana Clone"}

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
