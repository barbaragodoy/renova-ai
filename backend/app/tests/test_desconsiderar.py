"""
Testes do endpoint POST /recomendacoes/desconsiderar.
"""
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.auth.context import ContextoResponse, StatusContexto

CLIENT = TestClient(app)

_CTX = ContextoResponse(
    status=StatusContexto.SETOR_RESOLVIDO,
    matricula="REP001",
    setor="SP_INTERIOR",
    cod_linha="CARDIO",
    nome="Ana Silva",
)

_ID = str(uuid.uuid4())
_BODY = {
    "id_recomendacao": _ID,
    "rep_matricula": "REP001",
    "motivo": "Médico fora da minha área de atuação.",
    "timestamp": datetime.utcnow().isoformat(),
}


def _mock_engine(status="PENDENTE", matricula="REP001", found=True):
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    if found:
        row = MagicMock()
        row.__getitem__ = lambda s, k: {"rep_matricula": matricula, "status_recomendacao": status}[k]
        conn.execute.return_value.mappings.return_value.fetchone.return_value = row
    else:
        conn.execute.return_value.mappings.return_value.fetchone.return_value = None
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def test_desconsiderar_sucesso():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine()):
            resp = CLIENT.post("/recomendacoes/desconsiderar", json=_BODY, params={"email": "ana@ache.com.br"})
    assert resp.status_code == 200
    assert resp.json()["sucesso"] is True


def test_desconsiderar_nao_encontrada():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine(found=False)):
            resp = CLIENT.post("/recomendacoes/desconsiderar", json=_BODY, params={"email": "ana@ache.com.br"})
    assert resp.status_code == 404


def test_desconsiderar_outro_propagandista():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine(matricula="REP999")):
            resp = CLIENT.post("/recomendacoes/desconsiderar", json=_BODY, params={"email": "ana@ache.com.br"})
    assert resp.status_code == 403


def test_desconsiderar_ja_desconsiderada():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine(status="DESCONSIDERADA")):
            resp = CLIENT.post("/recomendacoes/desconsiderar", json=_BODY, params={"email": "ana@ache.com.br"})
    assert resp.status_code == 409


def test_desconsiderar_ja_aplicada():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine(status="APLICADA")):
            resp = CLIENT.post("/recomendacoes/desconsiderar", json=_BODY, params={"email": "ana@ache.com.br"})
    assert resp.status_code == 409
