"""
Testes de integração do endpoint /prescricoes/consultar — golden set de 5 perguntas.
Usa mock do LLM para não depender de chave de API em CI.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app

CLIENT = TestClient(app)

EMAIL_VALIDO = "ana.silva@ache.com.br"


def _mock_nl_to_sql(status="OK", sql="SELECT 1", texto="Resposta simulada."):
    return AsyncMock(return_value={"resposta_texto": texto, "sql_gerado": sql, "status": status})


def _post(pergunta: str, email: str = EMAIL_VALIDO, periodo: str = None, tecnico: bool = False):
    body = {"pergunta": pergunta, "email": email, "perfil_tecnico": tecnico}
    if periodo:
        body["periodo"] = periodo
    return CLIENT.post("/prescricoes/consultar", json=body)


@patch("backend.app.routers.prescricoes.nl_to_sql.consultar", new_callable=lambda: lambda: _mock_nl_to_sql())
def test_pergunta_operacional_com_setor(mock_consultar):
    resp = _post("Quais são os médicos com mais prescrições no meu setor?")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OK"
    assert data["resposta_texto"]


@patch("backend.app.routers.prescricoes.nl_to_sql.consultar", new_callable=lambda: lambda: _mock_nl_to_sql())
def test_pergunta_total_geral(mock_consultar):
    resp = _post("Qual o total geral de prescrições de Venlaxin no Brasil?")
    assert resp.status_code == 200


@patch(
    "backend.app.routers.prescricoes.nl_to_sql.consultar",
    new_callable=lambda: lambda: _mock_nl_to_sql(texto="No 1º trimestre foram 200 prescrições."),
)
def test_pergunta_com_periodo_especifico(mock_consultar):
    resp = _post("Quantas prescrições no 1º trimestre?", periodo="1° trimestre")
    assert resp.status_code == 200
    assert "trimestre" in resp.json()["resposta_texto"].lower()


@patch(
    "backend.app.routers.prescricoes.nl_to_sql.consultar",
    new_callable=lambda: lambda: _mock_nl_to_sql(status="GENIE_ERROR"),
)
def test_pergunta_fora_de_escopo(mock_consultar):
    resp = _post("Qual é a previsão do tempo em São Paulo?")
    assert resp.status_code == 502


@patch("backend.app.routers.prescricoes.nl_to_sql.consultar", new_callable=lambda: lambda: _mock_nl_to_sql())
def test_pergunta_sem_periodo_aplica_ytd(mock_consultar):
    """Sem período informado, YTD deve ser aplicado pelo nl_to_sql."""
    resp = _post("Quantas prescrições de Lisinopril tivemos?")
    assert resp.status_code == 200


def test_propagandista_nao_encontrado():
    resp = _post("Alguma pergunta", email="nao.existe@ache.com.br")
    assert resp.status_code == 403
