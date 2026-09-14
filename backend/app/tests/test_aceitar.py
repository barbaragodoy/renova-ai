"""Testes do POST /recomendacoes/{id}/aceitar.

O aceite e intencao declarada pelo propagandista, e nao confirmacao de que o
medico entrou no painel. Quem confirma continua sendo o job diario do Hugo,
comparando contra o painel real. Por isso o teste central aqui e o que garante
que o aceite grava `ACEITA` e nunca `APLICADA`.

Mocka `_engine` no mesmo padrao de test_desconsiderar.py: nada de banco.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.tests.apoio_sessao import CABECALHO
from backend.app.auth.context import ContextoResponse, StatusContexto

CLIENT = TestClient(app)

pytestmark = pytest.mark.usefixtures("forcar_data_source_local")

_CTX = ContextoResponse(
    status=StatusContexto.SETOR_RESOLVIDO,
    matricula="REP001",
    setor="SP_INTERIOR",
    cod_linha="CARDIO",
    nome="Ana Silva",
)

_ID = str(uuid.uuid4())


def _mock_engine(status="PENDENTE", matricula="REP001", found=True, rowcount=1, captured=None):
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "SELECT" in sql:
            if found:
                result.mappings.return_value.fetchone.return_value = {
                    "rep_matricula": matricula,
                    "status_recomendacao": status,
                }
            else:
                result.mappings.return_value.fetchone.return_value = None
        elif "UPDATE" in sql:
            if captured is not None:
                captured.append((sql, params))
            result.rowcount = rowcount
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def _post(engine=None, id_rec=None):
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", engine or _mock_engine()):
            return CLIENT.post(
                f"/recomendacoes/{id_rec or _ID}/aceitar",
                params={"email": "ana@ache.com.br"},
                headers=CABECALHO,
            )


def test_aceite_grava_aceita_e_nunca_aplicada():
    """O ponto central do desenho: o aceite e intencao, nao fato.

    `APLICADA` continua sendo do job que compara contra o painel real. Se o
    endpoint gravasse `APLICADA`, o portal afirmaria que o medico entrou no
    painel antes de ele ter entrado, e a exportacao por CSV nem existe ainda.
    """
    captured = []
    resp = _post(engine=_mock_engine(captured=captured))
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["success"] is True
    assert corpo["status_recomendacao"] == "ACEITA"
    assert corpo["id_recomendacao"] == _ID
    assert corpo["data_aceite"]

    sql, params = captured[0]
    assert "'ACEITA'" in sql
    assert "APLICADA" not in sql
    assert params["mat"] == "REP001"


def test_aceite_registra_quem_aceitou_e_quando():
    """Identidade vem do token, nunca do cliente, e a data e gerada no
    backend. Mesma regra do desconsiderar."""
    captured = []
    _post(engine=_mock_engine(captured=captured))
    sql, params = captured[0]
    assert "aceito_por" in sql.lower()
    assert "data_aceite" in sql.lower()
    assert params["mat"] == "REP001"
    assert params["agora"] is not None


def test_update_repete_o_status_esperado_no_where():
    """Dois cliques simultaneos gravam uma vez so: o WHERE repete
    status = 'PENDENTE', entao o segundo recebe rowcount 0."""
    captured = []
    _post(engine=_mock_engine(captured=captured))
    sql, _ = captured[0]
    assert "WHERE" in sql
    assert "'PENDENTE'" in sql


def test_recomendacao_de_outro_propagandista_da_403():
    resp = _post(engine=_mock_engine(matricula="REP999"))
    assert resp.status_code == 403
    # Mensagem generica: nao revela status nem existencia de recomendacao alheia.
    assert "status" not in resp.json()["detail"].lower()


def test_recomendacao_inexistente_da_404():
    assert _post(engine=_mock_engine(found=False)).status_code == 404


def test_aceitar_duas_vezes_da_409():
    assert _post(engine=_mock_engine(status="ACEITA")).status_code == 409


def test_corrida_de_dois_cliques_da_409():
    """SELECT viu PENDENTE, mas o UPDATE nao pegou linha nenhuma porque outra
    requisicao gravou primeiro.

    A mensagem nao afirma qual foi a mudanca: pode ter sido aceite,
    desconsideracao ou expiracao de ciclo, e o backend nao sabe qual.
    """
    resp = _post(engine=_mock_engine(rowcount=0))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "A recomendação não está mais pendente."


@pytest.mark.parametrize("status", ["DESCONSIDERADA", "APLICADA", "EXPIRADA", "INELEGIVEL"])
def test_status_incompativel_da_400(status):
    """INELEGIVEL entra aqui de proposito: e o medico que deixou de ser
    recomendado no ranking, e aceitar o que o sistema ja retirou nao faz
    sentido."""
    resp = _post(engine=_mock_engine(status=status))
    assert resp.status_code == 400
    assert status in resp.json()["detail"]


def test_id_invalido_no_path_da_422():
    resp = _post(id_rec="nao-e-uuid")
    assert resp.status_code == 422
