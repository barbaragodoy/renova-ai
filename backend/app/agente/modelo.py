"""O cliente do modelo, trocável por configuração.

O portal já tem `app/llm/adapter.py`, mas a interface de lá é de uma volta só,
`complete(system, user) -> str`, e não carrega ferramenta nem histórico. O
agente precisa de várias voltas, então este módulo define a interface própria e
reaproveita as exceções existentes, para o tratamento de erro do portal
continuar valendo.

Agnóstico de modelo significa aqui: o nome do endpoint sai da configuração, e
qualquer endpoint de serving do workspace que aceite o formato de tools serve.
Verificado em 19/08/2026 que `databricks-claude-sonnet-5` responde com
`finish_reason: tool_calls` e escolhe a ferramenta certa.

A credencial é a mesma que o portal já usa para o SQL, sem chave nova.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from backend.app.llm.adapter import LLMError, LLMTimeoutError

# Tarifa por mil tokens. A decisao D10 pede custo **auditavel por chamada**, e
# nao projetado a partir de token agregado, entao a tarifa aplicada viaja junto
# com cada chamada em `chamadas_modelo`.
#
# Sem tarifa configurada o custo grava zero, e a tarifa zero fica registrada ao
# lado: quem auditar ve tarifa zero e sabe que a interacao nao foi precificada,
# em vez de ler um custo baixo como se fosse medicao. A T4.2 precisa das tarifas
# reais do workspace para o numero significar alguma coisa.
def _tarifa(nome: str) -> Decimal:
    try:
        return Decimal(os.getenv(nome, "0"))
    except Exception:  # noqa: BLE001
        return Decimal("0")


@dataclass
class Volta:
    """Uma ida ao modelo, com o que o log precisa registrar dela."""
    mensagem: dict
    endpoint: str = ""
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache: int = 0

    def para_log(self, chamada_id: str) -> dict:
        entrada, saida = _tarifa("AGENTE_TARIFA_ENTRADA"), _tarifa("AGENTE_TARIFA_SAIDA")
        mil = Decimal("1000")
        custo = (Decimal(self.tokens_entrada) / mil * entrada
                 + Decimal(self.tokens_saida) / mil * saida)
        return {
            "chamada_id": chamada_id, "endpoint": self.endpoint, "modelo": self.modelo,
            "tokens_entrada": self.tokens_entrada, "tokens_saida": self.tokens_saida,
            "tokens_cache": self.tokens_cache,
            "tarifa_entrada": entrada, "tarifa_saida": saida,
            "moeda": os.getenv("AGENTE_MOEDA", "USD"), "custo": custo,
        }


class ModeloComFerramentas(Protocol):
    def conversar(self, mensagens: list[dict], ferramentas: list[dict]) -> Volta:
        """Devolve a volta: mensagem, endpoint, modelo e consumo de tokens."""


class ServingDatabricks:
    """Chama um endpoint de serving do próprio workspace.

    O token OAuth é obtido por client_credentials e reaproveitado enquanto
    vale, para não pagar uma ida ao emissor a cada volta do laço de
    ferramentas.
    """

    def __init__(self, settings, endpoint: str | None = None):
        host = (settings.databricks_server_hostname or "").replace("https://", "").strip("/")
        self._host = f"https://{host}"
        self._id = settings.databricks_client_id
        self._segredo = settings.databricks_client_secret
        # trocar de modelo é trocar esta string: parâmetro, variável de ambiente
        # AGENTE_ENDPOINT, campo no Settings, ou o padrão. Verificado em 19/08
        # com databricks-claude-sonnet-5, databricks-claude-opus-4-8 e
        # databricks-gpt-oss-120b, sem uma linha de diferença no código.
        self._endpoint = (
            endpoint
            or getattr(settings, "agente_endpoint", None)
            or os.getenv("AGENTE_ENDPOINT")
            or "databricks-claude-sonnet-5"
        )
        self._timeout = getattr(settings, "llm_timeout_seconds", 30)
        self._token: str | None = None

    def _obter_token(self) -> str:
        if self._token:
            return self._token
        credencial = base64.b64encode(f"{self._id}:{self._segredo}".encode()).decode()
        req = urllib.request.Request(
            f"{self._host}/oidc/v1/token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "all-apis"}).encode(),
            headers={"Authorization": f"Basic {credencial}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                self._token = json.load(r)["access_token"]
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"não foi possível autenticar no workspace: {exc}") from exc
        return self._token

    def conversar(self, mensagens: list[dict], ferramentas: list[dict]) -> Volta:
        return self._chamar(mensagens, ferramentas=ferramentas, max_tokens=1200)

    def extrair_estruturado(self, mensagens: list[dict], max_tokens: int = 160) -> Volta:
        """Uma resposta curta sem ferramentas, para scripts de extração offline.

        Mantém a autenticação, o tratamento de erro e a medição de tokens do
        agente. O fluxo conversacional continua usando ``conversar``.
        """
        # Uma extração individual usa cerca de 160 tokens. Validações em lote
        # podem precisar de mais espaço para fechar o array JSON completo.
        if not 1 <= max_tokens <= 4000:
            raise ValueError("max_tokens deve estar entre 1 e 4000")
        return self._chamar(mensagens, ferramentas=None, max_tokens=max_tokens)

    def _chamar(self, mensagens: list[dict], ferramentas: list[dict] | None,
                max_tokens: int) -> Volta:
        payload: dict[str, Any] = {"messages": mensagens, "max_tokens": max_tokens}
        if ferramentas is not None:
            payload["tools"] = ferramentas
        corpo = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._host}/serving-endpoints/{self._endpoint}/invocations",
            data=corpo,
            headers={"Authorization": f"Bearer {self._obter_token()}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                resposta = json.load(r)
        except urllib.error.HTTPError as exc:
            # o token pode ter expirado entre uma volta e outra
            if exc.code == 401 and self._token:
                self._token = None
                return self._chamar(mensagens, ferramentas, max_tokens)
            raise LLMError(f"endpoint {self._endpoint} devolveu HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise LLMTimeoutError(f"endpoint {self._endpoint} não respondeu no tempo limite") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"falha ao chamar {self._endpoint}: {exc}") from exc

        escolhas = resposta.get("choices") or []
        if not escolhas:
            raise LLMError(f"endpoint {self._endpoint} devolveu resposta sem choices")
        uso = resposta.get("usage") or {}
        return Volta(
            mensagem=escolhas[0].get("message") or {},
            endpoint=self._endpoint,
            modelo=resposta.get("model") or self._endpoint,
            tokens_entrada=int(uso.get("prompt_tokens") or 0),
            tokens_saida=int(uso.get("completion_tokens") or 0),
            tokens_cache=int(uso.get("cache_read_input_tokens") or 0),
        )
