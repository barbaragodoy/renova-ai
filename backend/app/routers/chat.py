"""Chat do propagandista: a resposta em cards sobre um médico.

O setor vem da identidade autenticada, pelo mesmo caminho das demais rotas do
portal, e nunca do corpo da requisição. A pergunta pode citar um setor que não
é do propagandista, e o backend ignora esse valor.

O texto da resposta não é escrito por modelo de linguagem. Como mudar qualquer
frase está em `backend/app/chat/como-alterar-a-resposta-do-chat.md`.
"""
import datetime as dt
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.app.auth.context import StatusContexto, resolver_contexto
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.agente.conhecimento import ConhecimentoKA
from backend.app.agente.ferramentas import Contexto
from backend.app.agente.modelo import ServingDatabricks
from backend.app.agente.orquestrador import Orquestrador
from backend.app.agente import registro
from backend.app.chat.executor import ExecutorDoPortal, get_executor
from backend.app.chat.perfil_medico import PerfilResponse, resolver_perfil
from backend.app.config import get_settings
from backend.app.llm.adapter import LLMError, LLMTimeoutError

logger = logging.getLogger(__name__)

router = APIRouter()


class PerguntaRequest(BaseModel):
    pergunta: str = Field(min_length=1, max_length=500)
    # Só usados quando a pergunta desce para o agente, para a linha de
    # `tb_agente_log` ter chave de idempotência estável. Sem `id_conversa`, cada
    # reenvio grava uma segunda linha.
    id_conversa: Optional[str] = None
    turno: int = Field(default=1, ge=1)


@router.post("/perfil-medico", response_model=PerfilResponse)
def perfil_medico(
    body: PerguntaRequest,
    authorization: Optional[str] = Header(None),
    executor=Depends(get_executor),
) -> PerfilResponse:
    """Devolve a resposta pronta para exibir, ou o status que o canal trata.

    Só `FORA_DO_ESCOPO` deve ser encaminhado ao motor de linguagem natural. Os
    demais status já trazem a mensagem escrita.
    """
    if not body.pergunta.strip():
        raise HTTPException(status_code=400, detail="pergunta vazia")

    email = resolver_email_autenticado(authorization, None)
    contexto = resolver_contexto(email)
    if contexto.status != StatusContexto.SETOR_RESOLVIDO:
        raise HTTPException(
            status_code=403,
            detail={"status": contexto.status, "mensagem": contexto.mensagem},
        )

    # `resolver_contexto` devolve SETOR_RESOLVIDO com o setor direto da coluna,
    # que aceita nulo. Sem esta guarda, um cadastro sem setor chegaria ao
    # resolvedor como se não houvesse identidade nenhuma, e aí o setor citado no
    # texto da pergunta passaria a escolher de quais dados a resposta sai.
    # Falhar fechado aqui é o único lugar onde dá para distinguir "não tem
    # identidade" de "tem identidade sem setor".
    if not (contexto.setor or "").strip():
        raise HTTPException(
            status_code=403,
            detail={
                "status": "SETOR_AUSENTE",
                "mensagem": "Seu cadastro está sem setor. Contate o administrador.",
            },
        )

    resposta = resolver_perfil(body.pergunta, executor, setor_autenticado=contexto.setor)

    # O agente entra **só** onde a rota determinística não sabe responder.
    #
    # Decisão de George em 20/08/2026: as duas convivem. As perguntas já
    # mapeadas continuam instantâneas, com os cards e as onze regras de texto
    # que vieram de erro em campo. O agente serve para o que o código não
    # cobre, e não para refazer o que já funciona.
    #
    # `FORA_DO_ESCOPO` é o único status que desce para cá. `PERFIL_PRONTO`,
    # `MEDICO_AMBIGUO` e `MEDICO_NAO_ENCONTRADO` já são respostas boas: a
    # primeira acertou, e as outras duas dizem a verdade em vez de gastar
    # segundos para dizer a mesma coisa mais devagar.
    if resposta.status != "FORA_DO_ESCOPO":
        return resposta
    return _tentar_o_agente(body, email, contexto, resposta)


def _tentar_o_agente(body: PerguntaRequest, email: str, contexto,
                     resposta_original: PerfilResponse):
    """Última tentativa antes de dizer que não sabe. Falha volta ao original."""
    settings = get_settings()
    ctx = Contexto(email=email, matricula=contexto.matricula or "", setor=contexto.setor)
    ts_inicio = dt.datetime.now(dt.timezone.utc)
    pergunta = body.pergunta.strip()
    try:
        modelo = ServingDatabricks(settings)
        orquestrador = Orquestrador(
            ctx,
            ExecutorDoPortal(),
            modelo,
            conhecimento=ConhecimentoKA(modelo, settings.databricks_server_hostname),
            # Sem `schema=`: nomes sem catálogo já resolvem certo nos dois lados
            # de `DATA_SOURCE` — ver `Ferramentas._qualificar`.
        )
        resultado = orquestrador.responder(pergunta)
    except (LLMError, LLMTimeoutError):
        logger.warning("agente indisponivel no fallback do chat", exc_info=True)
        return resposta_original
    except Exception:  # noqa: BLE001
        logger.exception("falha no fallback do chat para o agente")
        return resposta_original

    if not resultado.texto.strip():
        return resposta_original

    # Registro em `tb_agente_log`.
    #
    # Estava faltando, e a consequência era silenciosa: este é o **único**
    # caminho que o front usa para chegar ao agente, porque a tela chama
    # `POST /chat/perfil-medico` e não `POST /agente/perguntar`. Sem esta
    # chamada, nenhuma interação do agente chegava à tabela, e ela seguia com
    # zero linhas desde a criação. O gate G1 foi aprovado sobre o argumento de
    # que esse log alimenta todo o ciclo de aprendizado da Fase 3.
    #
    # `registrar` nunca levanta: uma falha de telemetria não pode trocar uma
    # resposta boa por um erro 500.
    registro.registrar(
        ExecutorDoPortal(),
        "tb_agente_log",
        resultado,
        ctx,
        id_conversa=body.id_conversa or str(uuid.uuid4()),
        turno=body.turno,
        ts_inicio=ts_inicio,
        # `portal` e nao `chat`: o dominio documentado da coluna e "portal,
        # chip, teste ou golden_set", e a tela do chat e o portal. Nao ha CHECK
        # nessa coluna, entao um valor fora do dominio passaria calado e sujaria
        # o agrupamento da Fase 3 sem ninguem perceber.
        origem="portal",
    )
    return PerfilResponse(status="RESPOSTA_DO_AGENTE", mensagem=resultado.texto)
