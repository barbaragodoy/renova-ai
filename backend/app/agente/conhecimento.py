"""A ferramenta de conhecimento sobre o Knowledge Assistant do piloto (T1.3).

O KA é `PED AI - Piloto KB`, endpoint `ka-288459c4-endpoint`, e responde no
formato `agent/v1/responses`, diferente do chat completions que o orquestrador
usa para o modelo. Por isso ele tem cliente próprio em vez de reaproveitar
`modelo.py`.

A resposta chega quebrada em vários blocos de texto, e a citação vem em
`annotations` do tipo `url_citation`, apontando o arquivo dentro do volume:

    .../Volumes/acheinfo_dev/renovai/volume_renovai_dev/kb-personas/medicos/PERFORMANCE.md#:~:text=...

Daí sai o nome do documento que vai para o log, que é o critério de aceite da
T1.3. A URL inteira não vai: ela carrega o trecho citado embutido no fragmento
`#:~:text=`, o que colocaria conteúdo da KB dentro da tabela de log.

**Permissão.** O service principal do portal não conseguia consultar o endpoint
até 19/08/2026, quando recebeu `CAN_QUERY`. Sem isso a chamada volta 403 e a
ferramenta degrada, que é o comportamento correto mas esconderia a causa.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from typing import Any
from urllib.parse import unquote

ENDPOINT_PADRAO = "ka-288459c4-endpoint"

# O KA leva cerca de 10 segundos numa pergunta de persona, bem mais que uma
# volta do modelo. Timeout próprio para não derrubar a conversa inteira.
TIMEOUT_SEGUNDOS = 60

_ARQUIVO = re.compile(r"/([^/]+\.(?:md|pdf|txt|docx?))(?:#|$)", re.IGNORECASE)


class ConhecimentoKA:
    def __init__(self, modelo, hostname: str, endpoint: str | None = None):
        """Reaproveita o token do `ServingDatabricks`, sem segunda credencial."""
        self._modelo = modelo
        self._host = "https://" + (hostname or "").replace("https://", "").strip("/")
        self._endpoint = endpoint or ENDPOINT_PADRAO

    def buscar(self, pergunta: str) -> list[dict[str, Any]]:
        corpo = json.dumps({"input": [{"role": "user", "content": pergunta}]}).encode()
        req = urllib.request.Request(
            f"{self._host}/serving-endpoints/{self._endpoint}/invocations",
            data=corpo,
            headers={"Authorization": f"Bearer {self._modelo._obter_token()}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as r:
            resposta = json.load(r)
        return [self._montar(resposta)]

    # ----------------------------------------------------------------

    @staticmethod
    def _montar(resposta: dict) -> dict[str, Any]:
        partes: list[str] = []
        documentos: list[str] = []
        # documento -> hashes das passagens citadas dele. Lista e nao valor
        # unico: o KA cita mais de um trecho do mesmo arquivo numa resposta, e
        # guardar so o primeiro perdia a evidencia dos demais. Achado do
        # julgamento independente de 20/08.
        trechos: dict[str, list[str]] = {}
        for msg in resposta.get("output") or []:
            for bloco in msg.get("content") or []:
                if bloco.get("type") != "output_text":
                    continue
                texto = bloco.get("text") or ""
                if texto:
                    partes.append(texto)
                for anotacao in bloco.get("annotations") or []:
                    url = anotacao.get("url") or ""
                    nome = ConhecimentoKA._documento(url)
                    if not nome:
                        continue
                    if nome not in documentos:
                        documentos.append(nome)
                        trechos[nome] = []
                    h = ConhecimentoKA._trecho_hash(url)
                    if h not in trechos[nome]:
                        trechos[nome].append(h)

        texto = "".join(partes).strip()
        usou_fonte = bool((resposta.get("custom_outputs") or {}).get("sources_used"))

        if not texto:
            return {"indisponivel": "a base de conhecimento não trouxe conteúdo para essa pergunta"}
        return {
            "resposta": texto,
            "documentos": documentos,
            # nome -> hashes das passagens citadas. O contrato do log pede
            # `trecho_hash` nao vazio, e o hash e a forma de dizer **qual**
            # passagem sustentou a resposta sem copiar a passagem para dentro da
            # tabela de log. Duas respostas que citam o mesmo trecho ficam
            # comparaveis; nenhuma delas guarda o texto da KB.
            "trechos": trechos,
            # o KA diz quando respondeu sem apoio de documento. Isso vira sinal
            # para o agente: sem fonte, a resposta é conhecimento geral do
            # modelo do KA, e não material da Aché.
            "apoiado_em_documento": usou_fonte,
        }

    @staticmethod
    def _trecho_hash(url: str) -> str:
        """sha256 do trecho que o KA embutiu no fragmento `#:~:text=` da URL."""
        marca = "#:~:text="
        bruto = unquote(url.split(marca, 1)[1]) if marca in url else url
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()

    @staticmethod
    def _documento(url: str) -> str:
        # a URL vem percent-encoded e com o trecho citado no fragmento
        limpa = unquote(url.split("#")[0])
        achado = _ARQUIVO.search(limpa + "#")
        return achado.group(1) if achado else ""
