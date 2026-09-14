"""
Testes de POST /webhooks/twilio/status (backend/app/routers/webhooks_twilio.py)
— Sprint 7. TestClient real (FastAPI), Postgres local de verdade para o
registro (mesmo padrão dos demais testes de integração deste projeto).
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.db.databricks_connection import get_engine
from backend.app.main import app
from backend.app.services.registro_notificacao_whatsapp import registrar_notificacao

pytestmark = [pytest.mark.requer_banco, pytest.mark.usefixtures("forcar_data_source_local")]

CLIENT = TestClient(app)
_DESTINATARIO = "+5511933334444"


@pytest.fixture(autouse=True)
def _limpar_cenario(forcar_data_source_local):
    # Dependência explícita — mesma razão de test_registro_notificacao_whatsapp.py.
    def _limpar():
        with get_engine().connect() as conn:
            conn.execute(
                text("DELETE FROM tb_notificacoes_whatsapp WHERE destinatario = :d"),
                {"d": _DESTINATARIO},
            )
            conn.commit()

    _limpar()
    yield
    _limpar()


def _criar_registro_sent(sid: str) -> str:
    return registrar_notificacao(
        registro_id=None,
        destinatario=_DESTINATARIO,
        tipo_notificacao="ENTRADA_PAINEL",
        template_usado="entrada_painel",
        status="sent",
        sid_twilio=sid,
    )


def test_status_conhecido_atualiza_o_registro():
    sid = f"SM{uuid.uuid4().hex[:16]}"
    registro_id = _criar_registro_sent(sid)

    resp = CLIENT.post(
        "/webhooks/twilio/status",
        data={"MessageSid": sid, "MessageStatus": "delivered"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ignorado": False}

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status, erro FROM tb_notificacoes_whatsapp WHERE id = :id"),
            {"id": registro_id},
        ).fetchone()
    assert row.status == "delivered"
    assert row.erro is None


def test_status_com_error_code_grava_o_erro():
    sid = f"SM{uuid.uuid4().hex[:16]}"
    registro_id = _criar_registro_sent(sid)

    resp = CLIENT.post(
        "/webhooks/twilio/status",
        data={"MessageSid": sid, "MessageStatus": "failed", "ErrorCode": "63016"},
    )
    assert resp.status_code == 200

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status, erro FROM tb_notificacoes_whatsapp WHERE id = :id"),
            {"id": registro_id},
        ).fetchone()
    assert row.status == "failed"
    assert row.erro == "63016"


@pytest.mark.parametrize("status_ignorado", ["queued", "sending", "receiving"])
def test_status_desconhecido_e_ignorado_sem_erro_e_sem_alterar_o_registro(status_ignorado):
    sid = f"SM{uuid.uuid4().hex[:16]}"
    registro_id = _criar_registro_sent(sid)

    resp = CLIENT.post(
        "/webhooks/twilio/status",
        data={"MessageSid": sid, "MessageStatus": status_ignorado},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ignorado": True}

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status FROM tb_notificacoes_whatsapp WHERE id = :id"),
            {"id": registro_id},
        ).fetchone()
    assert row.status == "sent"  # continua o valor original, não foi tocado


def test_sid_desconhecido_e_ignorado_sem_erro_500():
    resp = CLIENT.post(
        "/webhooks/twilio/status",
        data={"MessageSid": f"SM-inexistente-{uuid.uuid4().hex}", "MessageStatus": "delivered"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ignorado": True}


def test_campos_obrigatorios_ausentes_devolve_422():
    resp = CLIENT.post("/webhooks/twilio/status", data={"MessageSid": "SMxyz"})
    assert resp.status_code == 422
