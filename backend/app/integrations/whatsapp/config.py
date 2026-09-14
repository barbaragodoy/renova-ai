"""
Configuração da integração WhatsApp/Twilio (Sprint 7).

Categoria distinta de `DATA_SOURCE`/`get_engine()`: aquele par escolhe ENTRE
duas fontes de dado equivalentes (Postgres local vs. Databricks real) e é
consumido por praticamente todo o backend. Isto aqui é credencial de UMA
API externa específica — a Twilio nunca é "a fonte de dado" do projeto, é
só o canal de envio de uma notificação. Por isso fica isolado neste módulo,
lido diretamente de variável de ambiente (não via `Settings`/`env_file`
central de `config.py`) e nunca com valor-exemplo funcional em `.env.example`.

`TWILIO_ENV` alterna sandbox/production. Hoje só sandbox tem credencial
real disponível — production ainda não tem conta/números aprovados (ver
docs/context/known-issues.md). `get_twilio_config()` falha alto e cedo com
`TwilioConfigError` se alguém tentar `TWILIO_ENV=production` de propósito,
em vez de deixar a Twilio devolver um erro de autenticação confuso mais
tarde, dentro de uma chamada de envio real.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class TwilioConfigError(Exception):
    """Configuração da Twilio ausente, incompleta, ou ambiente não suportado."""


@dataclass(frozen=True)
class TwilioConfig:
    env: str
    account_sid: str
    auth_token: str
    whatsapp_number: str
    messaging_service_sid: str
    status_callback_url: str


_VARIAVEIS_OBRIGATORIAS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_NUMBER",
)


def get_twilio_config() -> TwilioConfig:
    """Lê a configuração da Twilio do ambiente de processo.

    `TWILIO_MESSAGING_SERVICE_SID` e `TWILIO_STATUS_CALLBACK_URL` não estão
    em `_VARIAVEIS_OBRIGATORIAS`: o primeiro é opcional (dá para enviar
    informando `from_=whatsapp_number` direto, sem Messaging Service); o
    segundo é opcional porque nem todo ambiente de teste tem uma URL pública
    alcançável pela Twilio para receber o callback de status.
    """
    env = os.environ.get("TWILIO_ENV", "sandbox").strip().lower()

    if env == "production":
        raise TwilioConfigError(
            "TWILIO_ENV=production, mas não existe credencial de produção "
            "configurada ainda (conta/números de produção não aprovados — "
            "ver docs/context/known-issues.md). Use TWILIO_ENV=sandbox "
            "(default) enquanto a Sprint 7 não avança para produção."
        )

    if env != "sandbox":
        raise TwilioConfigError(
            f"TWILIO_ENV={env!r} não é um ambiente suportado. "
            "Valores aceitos hoje: 'sandbox' (default)."
        )

    faltando = [nome for nome in _VARIAVEIS_OBRIGATORIAS if not os.environ.get(nome)]
    if faltando:
        raise TwilioConfigError(
            "Variáveis de ambiente da Twilio ausentes: "
            f"{', '.join(faltando)}. Exportar manualmente antes de subir o "
            "backend — nunca commitar em .env (ver .env.example)."
        )

    return TwilioConfig(
        env=env,
        account_sid=os.environ["TWILIO_ACCOUNT_SID"],
        auth_token=os.environ["TWILIO_AUTH_TOKEN"],
        whatsapp_number=os.environ["TWILIO_WHATSAPP_NUMBER"],
        messaging_service_sid=os.environ.get("TWILIO_MESSAGING_SERVICE_SID", ""),
        status_callback_url=os.environ.get("TWILIO_STATUS_CALLBACK_URL", ""),
    )
