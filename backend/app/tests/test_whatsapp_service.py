"""
Testes de send_whatsapp_notification()
(backend/app/integrations/whatsapp/service.py) — Sprint 7.

Mocka só o client Twilio e a config — nunca bate na API real do sandbox
dentro da suíte automatizada (ver Fase 8 do pedido original; validação
manual contra o sandbox é passo separado, fora daqui). A gravação em
tb_notificacoes_whatsapp usa o Postgres local de verdade, mesmo padrão de
test_registro_notificacao_whatsapp.py — mais simples e mais representativo
do que mockar as duas camadas ao mesmo tempo.
"""
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend.app.db.databricks_connection import get_engine
from backend.app.integrations.whatsapp.client import ResultadoEnvio, TwilioSendError
from backend.app.integrations.whatsapp.config import TwilioConfig
from backend.app.integrations.whatsapp.service import send_whatsapp_notification

pytestmark = [pytest.mark.requer_banco, pytest.mark.usefixtures("forcar_data_source_local")]

_DESTINATARIO = "+5511911112222"

_CONFIG_FAKE = TwilioConfig(
    env="sandbox",
    account_sid="ACfake",
    auth_token="tokenfake",
    whatsapp_number="+14155238886",
    messaging_service_sid="",
    status_callback_url="",
)


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


def _contexto():
    return {"nome_propagandista": "Carla", "nome_medico": "Dr. Teste", "ciclo": "202608"}


@patch("backend.app.integrations.whatsapp.service.get_twilio_config", return_value=_CONFIG_FAKE)
@patch("backend.app.integrations.whatsapp.service.send_raw_message")
def test_envio_com_sucesso_registra_sent_com_sid(mock_send, _mock_config):
    mock_send.return_value = ResultadoEnvio(sid="SMsucesso1", status="sent")

    resultado = send_whatsapp_notification(
        destinatario=_DESTINATARIO,
        template_key="entrada_painel",
        context=_contexto(),
        tipo_notificacao="ENTRADA_PAINEL",
    )

    assert resultado.sucesso is True
    assert resultado.status == "sent"
    assert resultado.sid_twilio == "SMsucesso1"
    assert resultado.erro is None

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status, sid_twilio, erro FROM tb_notificacoes_whatsapp WHERE id = :id"),
            {"id": resultado.registro_id},
        ).fetchone()
    assert row.status == "sent"
    assert row.sid_twilio == "SMsucesso1"
    assert row.erro is None


@patch("backend.app.integrations.whatsapp.service.get_twilio_config", return_value=_CONFIG_FAKE)
@patch("backend.app.integrations.whatsapp.service.send_raw_message")
def test_envio_com_falha_registra_failed_com_erro_sem_levantar(mock_send, _mock_config):
    mock_send.side_effect = TwilioSendError("número fora da janela de 24h", codigo=63016)

    resultado = send_whatsapp_notification(
        destinatario=_DESTINATARIO,
        template_key="entrada_painel",
        context=_contexto(),
        tipo_notificacao="ENTRADA_PAINEL",
    )

    assert resultado.sucesso is False
    assert resultado.status == "failed"
    assert resultado.sid_twilio is None
    assert "63016" in resultado.erro or "janela" in resultado.erro

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status, sid_twilio, erro FROM tb_notificacoes_whatsapp WHERE id = :id"),
            {"id": resultado.registro_id},
        ).fetchone()
    assert row.status == "failed"
    assert row.sid_twilio is None
    assert row.erro is not None


@patch("backend.app.integrations.whatsapp.service.get_twilio_config", return_value=_CONFIG_FAKE)
@patch("backend.app.integrations.whatsapp.service.send_raw_message")
def test_template_inexistente_nao_grava_nada_e_levanta_antes_de_configurar_ou_enviar(
    mock_send, mock_config
):
    from backend.app.integrations.whatsapp.templates import TemplateNotFoundError

    with pytest.raises(TemplateNotFoundError):
        send_whatsapp_notification(
            destinatario=_DESTINATARIO,
            template_key="template_que_nao_existe",
            context=_contexto(),
            tipo_notificacao="ENTRADA_PAINEL",
        )

    mock_config.assert_not_called()
    mock_send.assert_not_called()
    with get_engine().connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) AS n FROM tb_notificacoes_whatsapp WHERE destinatario = :d"),
            {"d": _DESTINATARIO},
        ).fetchone()
    assert total.n == 0
