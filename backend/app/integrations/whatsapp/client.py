"""
Wrapper fino sobre o SDK oficial da Twilio (`twilio.rest.Client`).

Fino de propósito: a única responsabilidade daqui é traduzir
`TwilioRestException` (erro cru do SDK, com atributos específicos da Twilio)
em `TwilioSendError` (erro deste projeto, com o código preservado) — quem
chama `send_raw_message()` não precisa importar nada da Twilio para tratar
falha de envio.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from backend.app.integrations.whatsapp.config import TwilioConfig


class TwilioSendError(Exception):
    """Falha ao enviar mensagem via Twilio. `codigo` preserva o código de
    erro da Twilio (ex.: 63016, número fora da janela de 24h sem Template
    aprovado) para quem for decidir se vale re-tentar ou não."""

    def __init__(self, mensagem: str, codigo: Optional[int] = None):
        super().__init__(mensagem)
        self.codigo = codigo


@dataclass(frozen=True)
class ResultadoEnvio:
    sid: str
    status: str


def send_raw_message(config: TwilioConfig, to: str, body: str) -> ResultadoEnvio:
    """Envia uma mensagem de WhatsApp já renderizada (texto final, sem
    placeholder). Quem monta `body` a partir de template é `templates.py`;
    esta função não sabe nada sobre template.

    `to`/`from_` levam o prefixo `whatsapp:` exigido pela API da Twilio para
    WhatsApp (canal distinto de SMS na mesma conta) — quem chama passa só o
    número em E.164 (`+55...`), sem o prefixo.
    """
    cliente = Client(config.account_sid, config.auth_token)

    kwargs = {
        "to": f"whatsapp:{to}",
        "body": body,
    }
    if config.messaging_service_sid:
        kwargs["messaging_service_sid"] = config.messaging_service_sid
    else:
        kwargs["from_"] = f"whatsapp:{config.whatsapp_number}"
    if config.status_callback_url:
        kwargs["status_callback"] = config.status_callback_url

    try:
        mensagem = cliente.messages.create(**kwargs)
    except TwilioRestException as exc:
        raise TwilioSendError(str(exc), codigo=exc.code) from exc

    return ResultadoEnvio(sid=mensagem.sid, status=mensagem.status)
