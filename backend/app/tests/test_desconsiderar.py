"""
Testes do endpoint POST /recomendacoes/{id_recomendacao}/desconsiderar
(task 161830/163626 — substitui o antigo POST /recomendacoes/desconsiderar,
ID no corpo, descontinuado — ver docs/context/decisions-log.md).
"""
import threading
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.auth.context import ContextoResponse, StatusContexto
from backend.app.schemas.recomendacoes import DesconsiderarRequest

CLIENT = TestClient(app)

# Testes mockados não dependem de DATA_SOURCE, mas o teste de integração
# real (test_desconsiderar_integracao_real_some_da_lista_entrada) precisa
# do Postgres local independente do que estiver em .env (que pode estar em
# 'databricks' — ver test_recomendacoes.py). Mesmo padrão do resto do projeto.
pytestmark = pytest.mark.usefixtures("forcar_data_source_local")

_CTX = ContextoResponse(
    status=StatusContexto.SETOR_RESOLVIDO,
    matricula="REP001",
    setor="SP_INTERIOR",
    cod_linha="CARDIO",
    nome="Ana Silva",
)

_ID = str(uuid.uuid4())

_BODY_BLOQUEAR_TRUE = {"motivo": "MEDICO_APOSENTADO", "bloquear_novas_recomendacoes": True}
_BODY_BLOQUEAR_FALSE = {"motivo": "SEM_INTERESSE_COMERCIAL", "bloquear_novas_recomendacoes": False}
_BODY_OUTROS = {
    "motivo": "OUTROS",
    "motivo_outros_texto": "Médico mudou de especialidade",
    "bloquear_novas_recomendacoes": True,
}
_BODY_OUTROS_SEM_TEXTO = {"motivo": "OUTROS", "bloquear_novas_recomendacoes": True}


def _mock_engine(status="PENDENTE", matricula="REP001", found=True, rowcount=1, captured=None):
    """Mocka as duas conexões (_engine().connect()) do endpoint: a primeira
    (SELECT) resolve dono/status via string matching no SQL, mesmo padrão de
    _exec em test_cenarios_completos.py; a segunda (UPDATE) devolve rowcount
    controlável para simular a corrida de concorrência."""
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
                captured.append(params)
            result.rowcount = rowcount
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def _post(body, engine=None):
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", engine or _mock_engine()):
            return CLIENT.post(f"/recomendacoes/{_ID}/desconsiderar", json=body, params={"email": "ana@ache.com.br"})


def test_desconsiderar_sucesso_bloquear_true():
    resp = _post(_BODY_BLOQUEAR_TRUE)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status_recomendacao"] == "DESCONSIDERADA"
    assert data["id_recomendacao"] == _ID


def test_desconsiderar_sucesso_bloquear_false():
    resp = _post(_BODY_BLOQUEAR_FALSE)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_desconsiderar_outros_formatado_corretamente():
    captured = []
    resp = _post(_BODY_OUTROS, engine=_mock_engine(captured=captured))
    assert resp.status_code == 200
    assert captured[0]["motivo"] == "OUTROS: Médico mudou de especialidade"


def test_desconsiderar_outros_sem_texto_retorna_422():
    resp = _post(_BODY_OUTROS_SEM_TEXTO)
    assert resp.status_code == 422


def test_desconsiderar_motivo_fora_da_lista_retorna_422():
    resp = _post({"motivo": "MOTIVO_INVENTADO", "bloquear_novas_recomendacoes": True})
    assert resp.status_code == 422


def test_desconsiderar_nao_encontrada_404():
    resp = _post(_BODY_BLOQUEAR_TRUE, engine=_mock_engine(found=False))
    assert resp.status_code == 404


def test_desconsiderar_outro_propagandista_403():
    resp = _post(_BODY_BLOQUEAR_TRUE, engine=_mock_engine(matricula="REP999"))
    assert resp.status_code == 403


def test_desconsiderar_ja_desconsiderada_409():
    resp = _post(_BODY_BLOQUEAR_TRUE, engine=_mock_engine(status="DESCONSIDERADA"))
    assert resp.status_code == 409


def test_desconsiderar_estado_incompativel_400():
    """EXPIRADA (ou qualquer status que não PENDENTE/DESCONSIDERADA) é erro
    de estado incompatível — distinto de 409 (já desconsiderada)."""
    resp = _post(_BODY_BLOQUEAR_TRUE, engine=_mock_engine(status="EXPIRADA"))
    assert resp.status_code == 400


def test_desconsiderar_concorrencia_duas_chamadas_simultaneas():
    """Simula duas requisições concorrentes na mesma recomendação. O UPDATE
    atômico do endpoint (WHERE status_recomendacao = 'PENDENTE') garante que
    só uma grava; a outra recebe 409 — sem precisar de lock explícito no
    código do endpoint. O mock é criado UMA vez e compartilhado pelas duas
    threads (patch de módulo não é thread-safe se cada thread entrar/sair do
    context manager por conta própria)."""
    estado = {"status": "PENDENTE"}
    lock = threading.Lock()
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "SELECT" in sql:
            with lock:
                status_atual = estado["status"]
            result.mappings.return_value.fetchone.return_value = {
                "rep_matricula": "REP001",
                "status_recomendacao": status_atual,
            }
        elif "UPDATE" in sql:
            with lock:
                if estado["status"] == "PENDENTE":
                    estado["status"] = "DESCONSIDERADA"
                    result.rowcount = 1
                else:
                    result.rowcount = 0
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn

    resultados = []

    def _chamar():
        resp = CLIENT.post(
            f"/recomendacoes/{_ID}/desconsiderar", json=_BODY_BLOQUEAR_TRUE, params={"email": "ana@ache.com.br"}
        )
        resultados.append(resp.status_code)

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        with patch("backend.app.routers.recomendacoes._engine", mock_eng):
            t1 = threading.Thread(target=_chamar)
            t2 = threading.Thread(target=_chamar)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

    assert sorted(resultados) == [200, 409]


def test_data_desconsideracao_gerada_pelo_backend_nunca_aceita_do_cliente():
    # Contrato não tem o campo — enviar um extra no corpo não deve influenciar
    # nada (pydantic ignora campos extras por padrão), a resposta sempre
    # reflete o timestamp gerado no momento da chamada, nunca o do cliente.
    body = dict(_BODY_BLOQUEAR_TRUE)
    body["data_desconsideracao"] = "2000-01-01T00:00:00+00:00"
    resp = _post(body)
    assert resp.status_code == 200
    data_resp = resp.json()["data_desconsideracao"]
    assert not data_resp.startswith("2000-01-01")
    assert data_resp.startswith(str(datetime.now(timezone.utc).year))


def test_id_recomendacao_e_matricula_nao_fazem_parte_do_corpo():
    """Reforço estrutural da regra 'matrícula nunca aceita no corpo': o
    schema do contrato nem sequer declara esses campos, então não há como um
    client-supplied id/matrícula jamais influenciar a operação."""
    campos = DesconsiderarRequest.model_fields
    assert "id_recomendacao" not in campos
    assert "rep_matricula" not in campos
    assert "matricula" not in campos
    assert "data_desconsideracao" not in campos


# ---------------------------------------------------------------------------
# Integração real (Postgres local) — confirma que a recomendação some das
# listas pendentes automaticamente, sem qualquer alteração em
# listar_entrada()/listar_revisao(). Usa os cenários fixos de
# data/scripts/10_popular_cenarios_desconsiderar.sql, resetando o estado no
# início para o teste ser repetível em reruns.
# ---------------------------------------------------------------------------
_ID_CENARIO_ENTRADA = "10000000-0000-0000-0000-000000000001"
_ID_CENARIO_REVISAO = "10000000-0000-0000-0000-000000000005"


def _resetar_cenario(id_recomendacao: str):
    from sqlalchemy import text as _text

    from backend.app.db.databricks_connection import get_engine

    with get_engine().connect() as conn:
        conn.execute(
            _text(
                """
                UPDATE tb_recomendacoes_painel
                SET status_recomendacao = 'PENDENTE',
                    motivo_desconsideracao = NULL,
                    desconsiderado_por = NULL,
                    data_desconsideracao = NULL,
                    qtd_vezes_desconsiderado = 0,
                    bloquear_novas_recomendacoes = NULL
                WHERE id_recomendacao = :id
                """
            ),
            {"id": id_recomendacao},
        )
        conn.commit()


def test_desconsiderar_integracao_real_some_da_lista_entrada():
    _resetar_cenario(_ID_CENARIO_ENTRADA)

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp = CLIENT.post(
            f"/recomendacoes/{_ID_CENARIO_ENTRADA}/desconsiderar",
            json=_BODY_BLOQUEAR_TRUE,
            params={"email": "ana.lima@ache.com.br"},
        )
    assert resp.status_code == 200

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp_lista = CLIENT.get(
            "/recomendacoes/entrada", params={"email": "ana.lima@ache.com.br", "ciclo": "202507"}
        )
    assert resp_lista.status_code == 200
    ids = [item["id_recomendacao"] for item in resp_lista.json()["recomendacoes"]]
    assert _ID_CENARIO_ENTRADA not in ids


def test_desconsiderar_integracao_real_some_da_lista_revisao():
    _resetar_cenario(_ID_CENARIO_REVISAO)

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp = CLIENT.post(
            f"/recomendacoes/{_ID_CENARIO_REVISAO}/desconsiderar",
            json=_BODY_BLOQUEAR_FALSE,
            params={"email": "ana.lima@ache.com.br"},
        )
    assert resp.status_code == 200

    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX):
        resp_lista = CLIENT.get(
            "/recomendacoes/revisao", params={"email": "ana.lima@ache.com.br", "ciclo": "202507"}
        )
    assert resp_lista.status_code == 200
    ids = [item["id_recomendacao"] for item in resp_lista.json()["recomendacoes"]]
    assert _ID_CENARIO_REVISAO not in ids
