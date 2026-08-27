"""Rota do agente da via 1.

O caminho de identidade é o mesmo de `routers/chat.py`, e de propósito: o setor
sai da sessão autenticada e falha fechado quando o cadastro não tem setor. A
diferença é o que acontece depois, porque aqui quem escolhe a consulta é o
modelo, e não uma árvore de decisão escrita à mão.

Esta rota não substitui `POST /chat/perfil-medico`. Aquela responde em cards,
com texto determinístico, e continua sendo o caminho da tela de perfil. Esta
responde em texto para pergunta aberta.
"""
import datetime as dt
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import json
import logging

from backend.app.agente.conhecimento import ConhecimentoKA
from backend.app.agente.ferramentas import Contexto
from backend.app.agente.modelo import ServingDatabricks
from backend.app.agente.orquestrador import Orquestrador
from backend.app.agente import registro
from backend.app.auth.context import StatusContexto, resolver_contexto
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.chat.executor import ExecutorDoPortal
from backend.app.config import get_settings
from backend.app.llm.adapter import LLMError, LLMTimeoutError

logger = logging.getLogger(__name__)

router = APIRouter()


class PerguntaRequest(BaseModel):
    pergunta: str = Field(min_length=1, max_length=500)
    # A chave de idempotencia do log e o trio (id_conversa, turno, pergunta).
    # Quando o cliente nao manda `id_conversa`, cada requisicao ganha um
    # identificador novo e um reenvio grava uma segunda linha. Isso e limitacao
    # conhecida: idempotencia de ponta a ponta exige que o front mantenha o
    # identificador da conversa entre tentativas.
    id_conversa: Optional[str] = None
    turno: int = Field(default=1, ge=1)


class EnriquecerRequest(BaseModel):
    """O card já foi desenhado. Isto pede o que a KB tem sobre esse médico."""
    ufcrm: str = Field(min_length=3, max_length=20)


class RespostaEnriquecimento(BaseModel):
    texto: str
    documentos: list[str] = []
    perfil: str = ""
    disponivel: bool = True


class RespostaAgente(BaseModel):
    resposta: str
    ferramentas: list[str]
    documentos: list[str] = []
    degradada: bool


@router.post("/perguntar", response_model=RespostaAgente)
def perguntar(body: PerguntaRequest, authorization: Optional[str] = Header(None)) -> RespostaAgente:
    if not body.pergunta.strip():
        raise HTTPException(status_code=400, detail="pergunta vazia")

    email = resolver_email_autenticado(authorization, None)
    contexto = resolver_contexto(email)
    if contexto.status != StatusContexto.SETOR_RESOLVIDO:
        raise HTTPException(status_code=403,
                            detail={"status": contexto.status, "mensagem": contexto.mensagem})

    # Mesma guarda do chat: identidade sem setor não pode cair no caminho em que
    # o texto da pergunta escolheria de onde o dado sai. Aqui isso nem seria
    # possível, porque nenhuma ferramenta aceita setor, mas a consulta sem setor
    # devolveria o país inteiro. Falhar fechado é a resposta certa nos dois casos.
    if not (contexto.setor or "").strip():
        raise HTTPException(status_code=403, detail={
            "status": "SETOR_AUSENTE",
            "mensagem": "Seu cadastro está sem setor. Contate o administrador.",
        })

    settings = get_settings()
    modelo = ServingDatabricks(settings)
    orquestrador = Orquestrador(
        # `ContextoResponse` não tem e-mail nem linha. O e-mail é o que entrou
        # na resolução, e a linha não existe na `tb_propagandistas`, conforme o
        # comentário de `auth/context.py`. O agente não precisa dela: a linha do
        # profissional vem de `vw_agente_medico.LINHA_PRODUTO`, no próprio dado.
        Contexto(email=email, matricula=contexto.matricula or "", setor=contexto.setor),
        ExecutorDoPortal(),
        modelo,
        conhecimento=ConhecimentoKA(modelo, settings.databricks_server_hostname),
        # Sem `schema=`: nomes sem catálogo já resolvem certo nos dois lados de
        # `DATA_SOURCE` (Postgres local via `search_path`, Databricks via
        # `catalog`/`schema` de `connect_args`) — ver `Ferramentas._qualificar`.
    )

    ts_inicio = dt.datetime.now(dt.timezone.utc)
    try:
        resultado = orquestrador.responder(body.pergunta.strip())
    except LLMTimeoutError as exc:
        raise HTTPException(status_code=504, detail="O agente não respondeu no tempo limite.") from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail="O agente está indisponível agora.") from exc

    # Registro em tb_agente_log. `registrar` nunca levanta: log e para nos, e
    # uma falha aqui viraria erro 500 numa interacao que deu certo para quem
    # perguntou.
    registro.registrar(
        ExecutorDoPortal(),
        "tb_agente_log",
        resultado,
        Contexto(email=email, matricula=contexto.matricula or "", setor=contexto.setor),
        id_conversa=body.id_conversa or str(uuid.uuid4()),
        turno=body.turno,
        ts_inicio=ts_inicio,
    )

    return RespostaAgente(
        resposta=resultado.texto,
        ferramentas=resultado.ferramentas_usadas,
        documentos=resultado.documentos_citados,
        degradada=resultado.degradada,
    )


@router.post("/enriquecer", response_model=RespostaEnriquecimento)
def enriquecer(body: EnriquecerRequest,
               authorization: Optional[str] = Header(None)) -> RespostaEnriquecimento:
    """O que a base de conhecimento acrescenta ao card, buscado depois dele.

    **Por que é uma rota separada.** O card sai de código determinístico e chega
    instantâneo. A busca na base leva de dez a vinte segundos. Se as duas
    viajassem juntas, o propagandista esperaria vinte segundos para ver o que já
    estava pronto no primeiro. Separando, ele lê o card na hora e o
    enriquecimento aparece embaixo quando chega.

    **Por que lê de tabela e não pergunta à base.** A pergunta tem quatro
    respostas possíveis, uma por perfil de comunicação, servindo 765.474
    médicos. `tb_agente_persona` guarda as quatro, geradas uma vez quando a KB
    muda, e esta rota vira uma leitura.

    Falha nunca vira erro. Volta `disponivel = false` e a tela simplesmente não
    mostra a seção.
    """
    email = resolver_email_autenticado(authorization, None)
    contexto = resolver_contexto(email)
    if contexto.status != StatusContexto.SETOR_RESOLVIDO or not (contexto.setor or "").strip():
        raise HTTPException(status_code=403, detail={"status": contexto.status,
                                                     "mensagem": contexto.mensagem})

    executor = ExecutorDoPortal()

    # Uma consulta só: o perfil do médico e o texto pronto na mesma ida ao
    # banco. Medido em 20/08/2026, o custo da consulta é indistinguível de um
    # `SELECT 1`, ou seja, é só a ida e volta.
    #
    # Sem qualificação de catálogo: nomes sem `acheinfo_dev.renovai.` já
    # resolvem certo nos dois lados de `DATA_SOURCE` (Postgres local via
    # `search_path`, Databricks via `catalog`/`schema` de `connect_args`).
    linha = executor.query(
        """
        SELECT s.perfil_efetivo, p.texto, p.documentos
        FROM vw_segmentacao_efetiva s
        LEFT JOIN tb_agente_persona p
               ON upper(p.perfil) = upper(s.perfil_efetivo)
        WHERE s.setor = :setor AND s.ufcrm = :ufcrm
        """,
        {"setor": contexto.setor, "ufcrm": body.ufcrm.strip().upper()},
    )
    if not linha:
        return RespostaEnriquecimento(texto="", disponivel=False)

    escolhido = (linha[0].get("perfil_efetivo") or "").strip()
    texto = (linha[0].get("texto") or "").strip()

    # `A DEFINIR` é o valor de quem ainda não foi segmentado, e são 225.439
    # médicos. Mostrar texto de perfil para quem não tem perfil seria dar
    # orientação genérica com cara de recomendação.
    if not escolhido or escolhido.upper() == "A DEFINIR":
        return RespostaEnriquecimento(texto="", disponivel=False)

    if not texto:
        # A geração ainda não rodou para este perfil, ou a KB mudou e a tabela
        # está sendo refeita. Não cair para a chamada ao vivo à base: seriam os
        # mesmos 8 a 18 segundos que esta tabela existe para evitar.
        logger.warning("tb_agente_persona sem texto para o perfil %s", escolhido)
        return RespostaEnriquecimento(texto="", disponivel=False)

    documentos: list[str] = []
    try:
        documentos = (json.loads(linha[0].get("documentos") or "{}") or {}).get("documentos") or []
    except (TypeError, ValueError):
        documentos = []

    return RespostaEnriquecimento(
        texto=texto,
        documentos=documentos,
        perfil=escolhido,
    )
