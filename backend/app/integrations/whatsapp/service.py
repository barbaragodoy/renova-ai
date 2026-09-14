"""
Integração principal do envio de notificação WhatsApp (Sprint 7).

`send_whatsapp_notification()` é a única função que o resto do projeto
deveria chamar — desacoplada do gatilho: hoje não existe job nem endpoint
que a chame automaticamente (mesma situação de `registrar_envio_
recomendacoes()` na Sprint 5, ver docs/context/decisions-log.md). Quando
o gatilho existir (job agendado, reação a um evento, etc.), ele importa
esta função direto, sem precisar de rota HTTP.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, Optional

from backend.app.integrations.whatsapp.client import TwilioSendError, send_raw_message
from backend.app.integrations.whatsapp.config import get_twilio_config
from backend.app.integrations.whatsapp.templates import render_template
from backend.app.services.registro_notificacao_whatsapp import registrar_notificacao

logger = logging.getLogger("renovai.whatsapp")


@dataclass(frozen=True)
class ResultadoNotificacao:
    registro_id: str
    status: str
    sid_twilio: Optional[str] = None
    erro: Optional[str] = None

    @property
    def sucesso(self) -> bool:
        return self.status not in ("failed", "undelivered")


def send_whatsapp_notification(
    destinatario: str,
    template_key: str,
    context: Mapping[str, str],
    tipo_notificacao: str,
) -> ResultadoNotificacao:
    """Renderiza o template, registra `queued`, envia, e atualiza para o
    status final. Nunca levanta por falha de ENVIO — devolve
    `ResultadoNotificacao` com `sucesso=False` e `erro` preenchido, para um
    chamador em lote (ex.: iterar vários propagandistas) não precisar de
    try/except por item. Levanta, sim, para erro de configuração/entrada
    ANTES de gravar qualquer coisa: `TemplateNotFoundError`/`KeyError` de
    contexto incompleto, e `TwilioConfigError` — nenhum dos dois é "esta
    notificação falhou", é "o chamador pediu algo que não dá para fazer",
    e registrar um `queued` que nunca teria como progredir só sujaria a
    rastreabilidade.
    """
    corpo = render_template(template_key, context)
    config = get_twilio_config()

    registro_id = registrar_notificacao(
        registro_id=None,
        destinatario=destinatario,
        tipo_notificacao=tipo_notificacao,
        template_usado=template_key,
        status="queued",
    )

    try:
        resultado = send_raw_message(config, destinatario, corpo)
    except TwilioSendError as exc:
        logger.warning(
            "Falha ao enviar notificação WhatsApp (registro_id=%s, código=%s): %s",
            registro_id, exc.codigo, exc,
        )
        registrar_notificacao(
            registro_id=registro_id,
            destinatario=destinatario,
            tipo_notificacao=tipo_notificacao,
            template_usado=template_key,
            status="failed",
            erro=str(exc),
        )
        return ResultadoNotificacao(registro_id=registro_id, status="failed", erro=str(exc))

    registrar_notificacao(
        registro_id=registro_id,
        destinatario=destinatario,
        tipo_notificacao=tipo_notificacao,
        template_usado=template_key,
        status=resultado.status,
        sid_twilio=resultado.sid,
    )
    return ResultadoNotificacao(
        registro_id=registro_id, status=resultado.status, sid_twilio=resultado.sid
    )
