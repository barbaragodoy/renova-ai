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


def _mock_engine_ciclo(ciclo_max: str, capturados: list):
    """Mocka _engine() distinguindo a query MAX(...) (resolução do ciclo
    mais recente) da query principal de listagem — permite verificar qual
    ciclo foi efetivamente usado no bind param, e se a query MAX chegou a
    ser executada."""
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "MAX(" in sql:
            result.fetchone.return_value = MagicMock(ciclo=ciclo_max)
        else:
            capturados.append(params)
            result.mappings.return_value.fetchall.return_value = []
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def test_entrada_sem_ciclo_usa_max_da_tabela():
    """Sem ?ciclo= explícito, usa MAX(ciclo_referencia) da própria tabela em
    vez do default estático settings.ciclo_referencia (known-issue: default
    fica obsoleto a cada rollover mensal de ciclo)."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_ciclo("202699", capturados)):
            resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    assert capturados[0]["ciclo"] == "202699"


def test_entrada_com_ciclo_explicito_nao_consulta_max():
    """Com ?ciclo= explícito, a query MAX(...) nem chega a ser executada —
    o parâmetro do chamador prevalece, mesma capacidade já usada por
    test_recomendacoes_integration.py e documentada no README."""
    capturados = []
    chamadas_max = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)

            def _exec(query, params=None):
                sql = str(query)
                if "MAX(" in sql:
                    chamadas_max.append(True)
                result = MagicMock()
                capturados.append(params)
                result.mappings.return_value.fetchall.return_value = []
                return result

            conn.execute.side_effect = _exec
            mock_eng.return_value.connect.return_value = conn
            resp = CLIENT.get(
                "/recomendacoes/entrada",
                params={"email": "ana.silva@ache.com.br", "ciclo": "202501"},
            )
    assert resp.status_code == 200
    assert chamadas_max == []
    assert capturados[0]["ciclo"] == "202501"


def test_revisao_sem_ciclo_usa_max_da_tabela():
    """Mesmo comportamento de test_entrada_sem_ciclo_usa_max_da_tabela,
    para /recomendacoes/revisao — a correção foi aplicada nos dois
    endpoints, o known-issue afetava ambos igualmente."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_ciclo("202699", capturados)):
            resp = CLIENT.get("/recomendacoes/revisao", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    assert capturados[0]["ciclo"] == "202699"


def test_revisao_com_ciclo_explicito_nao_consulta_max():
    chamadas_max = []
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)

            def _exec(query, params=None):
                sql = str(query)
                if "MAX(" in sql:
                    chamadas_max.append(True)
                result = MagicMock()
                capturados.append(params)
                result.mappings.return_value.fetchall.return_value = []
                return result

            conn.execute.side_effect = _exec
            mock_eng.return_value.connect.return_value = conn
            resp = CLIENT.get(
                "/recomendacoes/revisao",
                params={"email": "ana.silva@ache.com.br", "ciclo": "202501"},
            )
    assert resp.status_code == 200
    assert chamadas_max == []
    assert capturados[0]["ciclo"] == "202501"


# ---------------------------------------------------------------------------
# GET /recomendacoes/desconsideradas — aba Arquivadas (consulta)
# ---------------------------------------------------------------------------

_ROW_DESCONSIDERADA = {
    "id_recomendacao": "22222222-2222-2222-2222-222222222222",
    "nome_medico": "Dr. Fulano",
    "ufcrm": "SP00042",
    "tipo_recomendacao": "ENTRADA_PAINEL",
    "motivo_recomendacao": None,
    "motivo_desconsideracao": "MEDICO_APOSENTADO",
    "bloquear_novas_recomendacoes": True,
    "data_desconsideracao": "2026-08-01T10:00:00+00:00",
    "ciclo_recomendacao": "202507",
}


def _mock_engine_desconsideradas(rows=None, captured=None):
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if captured is not None:
            captured.append({"sql": sql, "params": params})
        result.mappings.return_value.fetchall.return_value = rows or []
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def test_lista_desconsideradas_retorna_status_desconsiderada():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch(
            "backend.app.routers.recomendacoes._engine",
            _mock_engine_desconsideradas(rows=[_ROW_DESCONSIDERADA]),
        ):
            resp = CLIENT.get("/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["recomendacoes"][0]
    assert item["motivo_desconsideracao"] == "MEDICO_APOSENTADO"
    assert item["bloquear_novas_recomendacoes"] is True


def test_lista_desconsideradas_filtra_por_status_e_matricula_autenticada():
    """A query filtra status_recomendacao = 'DESCONSIDERADA' e usa a
    matrícula resolvida via contexto autenticado (nunca aceita de outro
    propagandista/input externo) — garante que não vaza dado de terceiro."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(captured=capturados)):
            resp = CLIENT.get("/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    sql = capturados[0]["sql"]
    assert "DESCONSIDERADA" in sql
    assert capturados[0]["params"] == {"mat": "REP001"}


def test_lista_desconsideradas_ordenacao_desc_por_data():
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(captured=capturados)):
            resp = CLIENT.get("/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    sql = capturados[0]["sql"]
    assert "ORDER BY data_desconsideracao DESC" in sql


def test_lista_desconsideradas_vazia_nao_da_erro():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(rows=[])):
            resp = CLIENT.get("/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "recomendacoes": []}


def test_lista_desconsideradas_sem_limit():
    """Diferente de /entrada e /revisao, não deve haver LIMIT na query —
    é consulta de histórico completo, não sugestão priorizada."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(captured=capturados)):
            resp = CLIENT.get("/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"})
    assert resp.status_code == 200
    assert "LIMIT" not in capturados[0]["sql"]


def test_desconsideradas_integracao_real_nao_retorna_de_outro_propagandista():
    """Integração real: REP002 (bruno.melo@ache.com.br) não deve ver a
    recomendação desconsiderada do cenário fixo pertencente a REP001
    (data/scripts/10_popular_cenarios_desconsiderar.sql, cenário 2)."""
    ctx_rep002 = ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO,
        matricula="REP002",
        setor="SP_INTERIOR",
        cod_linha="SNC",
        nome="Bruno Melo",
    )
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=ctx_rep002):
        resp = CLIENT.get("/recomendacoes/desconsideradas", params={"email": "bruno.melo@ache.com.br"})
    assert resp.status_code == 200
    ids = [item["id_recomendacao"] for item in resp.json()["recomendacoes"]]
    assert "10000000-0000-0000-0000-000000000002" not in ids
