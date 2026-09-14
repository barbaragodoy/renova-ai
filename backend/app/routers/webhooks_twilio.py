"""
Webhook de status de mensagem da Twilio (Sprint 7).

A Twilio chama esta rota (configurada como `TWILIO_STATUS_CALLBACK_URL`,
ver `integrations/whatsapp/config.py`) de forma assíncrona, um POST por
mudança de status da mensagem — não é a mesma requisição que enviou a
mensagem. O corpo vem como `application/x-www-form-urlencoded`
(`Form(...)`, não JSON), formato padrão da Twilio para webhooks.

Endpoint síncrono (`def`, não `async def`) — mesmo padrão de todo o resto
do projeto (ver `routers/recomendacoes.py`), já que o acesso a banco aqui
também é `get_engine()`/SQLAlchemy síncrono.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Form

from backend.app.services.registro_notificacao_whatsapp import (
    buscar_por_sid_twilio,
    registrar_notificacao,
)

logger = logging.getLogger("renovai.whatsapp")

router = APIRouter()

# Status da Twilio que carregam informação nova para nós. `queued`/`sending`/
# `receiving` ficam de fora de propósito: `queued` já é o status que
# `service.py` grava na criação, e `sending` é um passo intermediário sem
# nada de acionável — ignorar os dois evita um UPDATE (e um log) por
# webhook que não muda nada do que já sabíamos. Qualquer valor fora deste
# conjunto (incluindo um status novo que a Twilio venha a introduzir) cai
# no mesmo caminho de "ignorado sem erro", nunca em erro 500.
_STATUS_RASTREADOS = {"sent", "delivered", "failed", "undelivered", "read"}


@router.post("/status")
def status_callback(
    MessageSid: str = Form(...),
    MessageStatus: str = Form(...),
    ErrorCode: Optional[str] = Form(None),
):
    """Sempre devolve 200 — inclusive quando o status é ignorado ou o SID
    não é conhecido. A Twilio reenvia o callback se não receber 2xx; como
    nenhum desses casos é recuperável reenviando (o status não vai mudar
    de "desconhecido" para "conhecido", nem o SID vai passar a existir),
    devolver erro só geraria reenvio inútil."""
    if MessageStatus not in _STATUS_RASTREADOS:
        logger.info(
            "Webhook Twilio ignorado (status não rastreado): sid=%s status=%s",
            MessageSid, MessageStatus,
        )
        return {"ignorado": True}

    registro = buscar_por_sid_twilio(MessageSid)
    if registro is None:
        logger.warning(
            "Webhook Twilio para SID não encontrado em tb_notificacoes_whatsapp: sid=%s status=%s",
            MessageSid, MessageStatus,
        )
        return {"ignorado": True}

    registrar_notificacao(
        registro_id=str(registro.id),
        destinatario=registro.destinatario,
        tipo_notificacao=registro.tipo_notificacao,
        template_usado=registro.template_usado,
        status=MessageStatus,
        sid_twilio=registro.sid_twilio,
        erro=ErrorCode,
    )
    return {"ignorado": False}
