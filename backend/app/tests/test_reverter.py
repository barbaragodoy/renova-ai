"""
Testes do endpoint POST /recomendacoes/{id_recomendacao}/reverter
(aba Arquivadas — reversão), contraparte de POST /desconsiderar.
"""
import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text as _text
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.auth.context import ContextoResponse, StatusContexto
from backend.app.db.databricks_connection import get_engine

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


def _mock_engine(
    status="DESCONSIDERADA",
    matricula="REP001",
    found=True,
    ciclo_recomendacao="202507",
    ciclo_atual="202507",
    rowcount=1,
    captured=None,
):
    """Mocka as três consultas envolvidas no endpoint: SELECT de
    dono/status/ciclo, SELECT MAX(...) (_ciclo_mais_recente) e o UPDATE
    final — distinguidas por string matching no SQL, mesmo padrão de
    test_desconsiderar.py."""
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "MAX(" in sql:
            result.fetchone.return_value = MagicMock(ciclo=ciclo_atual)
        elif "UPDATE" in sql:
            if captured is not None:
                captured.append({"sql": sql, "params": params})
            result.rowcount = rowcount
        else:
            if found:
                result.mappings.return_value.fetchone.return_value = {
                    "rep_matricula": matricula,
                    "status_recomendacao": status,
                    "ciclo_referencia": ciclo_recomendacao,
                }
            else:
                result.mappings.return_value.fetchone.return_value = None
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def _post(engine=None):
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", engine or _mock_engine()):
            return CLIENT.post(f"/recomendacoes/{_ID}/reverter", params={"email": "ana@ache.com.br"})


def test_reverter_ciclo_atual_retorna_pendente():
    resp = _post(_mock_engine(ciclo_recomendacao="202507", ciclo_atual="202507"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status_recomendacao"] == "PENDENTE"
    assert data["id_recomendacao"] == _ID


def test_reverter_ciclo_anterior_retorna_expirada():
    resp = _post(_mock_engine(ciclo_recomendacao="202501", ciclo_atual="202507"))
    assert resp.status_code == 200
    assert resp.json()["status_recomendacao"] == "EXPIRADA"


def test_reverter_limpa_4_campos_mantem_contador_intacto():
    """O UPDATE deve zerar (NULL) motivo_desconsideracao, desconsiderado_por,
    bloquear_novas_recomendacoes e data_desconsideracao, mas nunca tocar em
    qtd_vezes_desconsiderado — verificação de forma da query."""
    capturados = []
    resp = _post(_mock_engine(captured=capturados))
    assert resp.status_code == 200
    sql = capturados[0]["sql"]
    for coluna in (
        "motivo_desconsideracao",
        "desconsiderado_por",
        "bloquear_novas_recomendacoes",
        "data_desconsideracao",
    ):
        assert coluna in sql
    assert "qtd_vezes_desconsiderado" not in sql


def test_reverter_nao_encontrada_404():
    resp = _post(_mock_engine(found=False))
    assert resp.status_code == 404


def test_reverter_outro_propagandista_403():
    resp = _post(_mock_engine(matricula="REP999"))
    assert resp.status_code == 403


def test_reverter_nao_desconsiderada_400():
    resp = _post(_mock_engine(status="PENDENTE"))
    assert resp.status_code == 400


def test_reverter_id_inexistente_nao_confunde_com_outro_propagandista():
    """404 (não existe) e 403 (existe, mas é de outro) são caminhos
    distintos — reforço de que o 404 não vaza por engano."""
    resp = _post(_mock_engine(found=False))
    assert resp.status_code == 404
    assert resp.json()["detail"] != "Não autorizado a reverter esta recomendação."


def test_reverter_concorrencia_duas_chamadas_simultaneas():
    """Duas requisições concorrentes de reversão na mesma recomendação: o
    UPDATE atômico (WHERE status_recomendacao = 'DESCONSIDERADA') garante
    que só uma grava — a outra recebe 400 (diferente do 409 usado por
    /desconsiderar; aqui não há distinção de 'já revertida', é só estado
    incompatível)."""
    estado = {"status": "DESCONSIDERADA"}
    lock = threading.Lock()
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "MAX(" in sql:
            result.fetchone.return_value = MagicMock(ciclo="202507")
        elif "UPDATE" in sql:
            with lock:
                if estado["status"] == "DESCONSIDERADA":
                    estado["status"] = "PENDENTE"
                    result.rowcount = 1
                else:
                    result.rowcount = 0
        else:
            with lock:
                status_atual = estado["status"]
            result.mappings.return_value.fetchone.return_value = {
                "rep_matricula": "REP001",
                "status_recomendacao": status_atual,
                "ciclo_referencia": "202507",
            }
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn

    resultados = []

    def _chamar():
        with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
            with patch("backend.app.routers.recomendacoes._engine", mock_eng):
                resp = CLIENT.post(f"/recomendacoes/{_ID}/reverter", params={"email": "ana@ache.com.br"})
        resultados.append(resp.status_code)

    t1 = threading.Thread(target=_chamar)
    t2 = threading.Thread(target=_chamar)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(resultados) == [200, 400]


# ---------------------------------------------------------------------------
# Integração real (Postgres local) — cenário fixo de
# data/scripts/10_popular_cenarios_desconsiderar.sql (id ...0002, REP001,
# ENTRADA_PAINEL, ciclo 202507, já com histórico completo de desconsideração
# e qtd_vezes_desconsiderado = 1). Reseta para DESCONSIDERADA no início de
# cada teste para ser repetível em reruns.
# ---------------------------------------------------------------------------
_ID_CENARIO = "10000000-0000-0000-0000-000000000002"


def _resetar_para_desconsiderada(id_recomendacao: str, qtd: int = 1):
    with get_engine().connect() as conn:
        conn.execute(
            _text(
                """
                UPDATE tb_recomendacoes_painel
                SET status_recomendacao = 'DESCONSIDERADA',
                    motivo_desconsideracao = 'MEDICO_APOSENTADO',
                    desconsiderado_por = 'REP001',
                    data_desconsideracao = NOW(),
                    qtd_vezes_desconsiderado = :qtd,
                    bloquear_novas_recomendacoes = FALSE
                WHERE id_recomendacao = :id
                """
            ),
            {"id": id_recomendacao, "qtd": qtd},
        )
        conn.commit()


def _ler_cenario(id_recomendacao: str):
    with get_engine().connect() as conn:
        return conn.execute(
            _text(
                """
                SELECT status_recomendacao, motivo_desconsideracao, desconsiderado_por,
                       bloquear_novas_recomendacoes, data_desconsideracao, qtd_vezes_desconsiderado
                FROM tb_recomendacoes_painel
                WHERE id_recomendacao = :id
                """
            ),
            {"id": id_recomendacao},
        ).mappings().fetchone()


def test_reverter_integracao_real_limpa_campos_mantem_contador():
    _resetar_para_desconsiderada(_ID_CENARIO, qtd=3)

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp = CLIENT.post(f"/recomendacoes/{_ID_CENARIO}/reverter", params={"email": "ana.lima@ache.com.br"})
    assert resp.status_code == 200

    row = _ler_cenario(_ID_CENARIO)
    assert row["status_recomendacao"] in ("PENDENTE", "EXPIRADA")
    assert row["motivo_desconsideracao"] is None
    assert row["desconsiderado_por"] is None
    assert row["bloquear_novas_recomendacoes"] is None
    assert row["data_desconsideracao"] is None
    assert row["qtd_vezes_desconsiderado"] == 3


def test_reverter_integracao_real_nao_exclui_fisicamente():
    _resetar_para_desconsiderada(_ID_CENARIO)

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp = CLIENT.post(f"/recomendacoes/{_ID_CENARIO}/reverter", params={"email": "ana.lima@ache.com.br"})
    assert resp.status_code == 200

    row = _ler_cenario(_ID_CENARIO)
    assert row is not None


def test_reverter_integracao_real_pendente_reaparece_na_lista_entrada():
    """Efeito natural: recomendação revertida para PENDENTE deve voltar a
    aparecer em GET /recomendacoes/entrada sem nenhuma alteração em
    listar_entrada() — mesmo princípio já validado para /desconsiderar em
    test_desconsiderar.py."""
    _resetar_para_desconsiderada(_ID_CENARIO)

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp = CLIENT.post(f"/recomendacoes/{_ID_CENARIO}/reverter", params={"email": "ana.lima@ache.com.br"})
    assert resp.status_code == 200
    novo_status = resp.json()["status_recomendacao"]

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp_lista = CLIENT.get(
            "/recomendacoes/entrada", params={"email": "ana.lima@ache.com.br", "ciclo": "202507"}
        )
    assert resp_lista.status_code == 200
    ids = [item["id_recomendacao"] for item in resp_lista.json()["recomendacoes"]]

    if novo_status == "PENDENTE":
        assert _ID_CENARIO in ids
    else:
        # Cenário 202507 == ciclo mais recente na seed local; se algum dia
        # deixar de ser, o teste sinaliza aqui em vez de falhar calado.
        assert _ID_CENARIO not in ids
