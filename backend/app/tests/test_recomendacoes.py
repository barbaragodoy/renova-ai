"""
Testes dos endpoints GET /recomendacoes/entrada e /recomendacoes/revisao.
Usa banco local via SQLAlchemy (requer Docker rodando).
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.auth.context import ContextoResponse, StatusContexto

CLIENT = TestClient(app)

# Este arquivo testa contra a seed do Postgres local (schema
# tb_recomendacoes_painel) — deve continuar passando independente do
# DATA_SOURCE configurado no .env real (que pode estar em 'databricks' para
# rodar a API/test_recomendacoes_integration.py contra o Databricks de
# verdade). Fixture compartilhada em conftest.py, mesmo padrão de test_context.py.
pytestmark = pytest.mark.usefixtures("forcar_data_source_local")

_CTX_VALIDO = ContextoResponse(
    status=StatusContexto.SETOR_RESOLVIDO,
    matricula="REP001",
    setor="SP_INTERIOR",
    cod_linha="CARDIO",
    nome="Ana Silva",
)

_CTX_NAO_ENCONTRADO = ContextoResponse(
    status=StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO,
    mensagem="Não encontrado.",
)


def test_lista_entrada_com_pendencias():
    """Integração real: busca recomendações de entrada (pode retornar vazio se tabela vazia)."""
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tipo"] == "ENTRADA_PAINEL"
    assert isinstance(data["recomendacoes"], list)


def test_lista_entrada_vazia():
    """Retorna lista vazia quando não há pendências."""
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.mappings.return_value.fetchall.return_value = []
            mock_eng.return_value.connect.return_value = mock_conn
            resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_propagandista_nao_encontrado():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_NAO_ENCONTRADO):
        resp = CLIENT.get("/recomendacoes/entrada", params={"email": "x@x.com"})
    assert resp.status_code == 403


def test_limite_5_registros():
    """Nunca deve retornar mais de 5 recomendações."""
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    assert len(resp.json()["recomendacoes"]) <= 5


def test_entrada_nome_medico_nulo_aplica_fallback():
    """NOME_MEDICO vem nulo da fonte real para candidatos a ENTRADA_PAINEL
    ainda fora do painel (ver docs/context/known-issues.md) — o endpoint não
    pode responder 500, deve aplicar o fallback consultivo com o UFCRM."""
    row = {
        "id_recomendacao": "11111111-1111-1111-1111-111111111111",
        "nome_medico": None,
        "ufcrm": "SP00099",
        "posicao_ranking": 42,
        "soma_pontuacao": 100.0,
        "ciclo_referencia": "202607",
    }
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.mappings.return_value.fetchall.return_value = [row]
            mock_eng.return_value.connect.return_value = mock_conn
            resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    item = resp.json()["recomendacoes"][0]
    assert item["nome_medico"] == "Médico ainda não identificado (UFCRM SP00099)"
