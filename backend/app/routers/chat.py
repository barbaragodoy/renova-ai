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

from backend.app.auth.context import (
    StatusContexto,
    coluna_identidade_para_auth_mode,
    resolver_contexto,
)
from backend.app.auth.jwt_auth import resolver_email_autenticado
from backend.app.agente.conhecimento import ConhecimentoKA
from backend.app.agente.ferramentas import Contexto
from backend.app.agente.modelo import ServingDatabricks
from backend.app.agente import memoria
from backend.app.agente.orquestrador import Orquestrador
from backend.app.agente import registro
from backend.app.chat.executor import ExecutorDoPortal, get_executor
from backend.app.chat.perfil_medico import Card, PerfilResponse, resolver_perfil
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
    contexto = resolver_contexto(
        email,
        coluna_identidade=coluna_identidade_para_auth_mode(),
    )
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
    # Descem para o agente: `FORA_DO_ESCOPO`, que sempre foi dele, e
    # `NAO_IMPLEMENTADO`, que era o beco onde morria a continuação da conversa.
    # O teste de 30/08/2026 mostrou o estrago: "Ordenar produtos da linha para
    # um médico específico", sugestão oferecida pelo próprio agente, casava com
    # a palavra-chave "produtos" do roteador e voltava "ainda não sei responder"
    # sem nunca chegar a quem tinha a ferramenta para responder.
    #
    # `PERFIL_PRONTO`, `MEDICO_AMBIGUO` e `MEDICO_NAO_ENCONTRADO` continuam
    # respondendo na hora: a primeira acertou, e as outras duas dizem a verdade
    # sobre um identificador explícito em vez de gastar segundos para dizer a
    # mesma coisa mais devagar.
    if resposta.status not in ("FORA_DO_ESCOPO", "NAO_IMPLEMENTADO"):
        # A resposta determinística também entra na memória: são três autores
        # na mesma janela, e o agente precisa saber o que os outros disseram
        # quando a conversa continuar com ele.
        chave = _chave_da_memoria(email, body.id_conversa)
        if chave and resposta.mensagem:
            # Sob a mesma trava do ciclo do agente: sem ela, uma resposta
            # determinística podia intercalar os turnos com uma requisição ao
            # agente em voo na mesma conversa. Achado da terceira rodada da
            # revisão de 31/08/2026.
            with memoria.conversa(chave):
                memoria.registrar(chave, "user", body.pergunta.strip())
                memoria.registrar(chave, "assistant", _texto_para_memoria(resposta))
        return resposta
    return _tentar_o_agente(body, email, contexto, resposta)


def _texto_para_memoria(resposta: PerfilResponse) -> str:
    """A mensagem mais as opções dos cards, no turno guardado.

    Em `MEDICO_AMBIGUO` os nomes oferecidos vivem só nos cards; guardar apenas
    "Qual delas?" deixaria "quero a segunda opção" sem referência no histórico.
    Achado da segunda rodada da revisão independente de 31/08/2026.
    """
    itens: list[str] = []
    for card in resposta.cards or []:
        if getattr(card, "type", "") == "suggestions":
            itens.extend(i for i in (card.items or []) if i)
    if not itens:
        return resposta.mensagem
    return resposta.mensagem + "\nOpções oferecidas: " + " | ".join(itens)


def _chave_da_memoria(email: str, id_conversa: str | None) -> str:
    """A chave combina a identidade autenticada com o id que o cliente enviou.

    O `id_conversa` vem do navegador e qualquer cliente autenticado pode
    escrever o valor que quiser. Sozinho, ele deixaria um usuário ler o
    histórico de outro que usasse o mesmo id, de propósito ou por azar.
    Prefixado pelo e-mail da sessão, o pior caso vira ler a própria conversa.
    Achado da revisão independente de 31/08/2026.
    """
    limpo = (id_conversa or "").strip()
    return f"{email}|{limpo}" if limpo else ""


def _com_memoria(chave: str, resposta: PerfilResponse) -> PerfilResponse:
    """Grava a resposta de recuo antes de devolvê-la, para o turno do usuário
    já registrado não ficar sem par no histórico."""
    if chave and resposta.mensagem:
        memoria.registrar(chave, "assistant", resposta.mensagem)
    return resposta


def _tentar_o_agente(body: PerguntaRequest, email: str, contexto,
                     resposta_original: PerfilResponse):
    """Última tentativa antes de dizer que não sabe. Falha volta ao original."""
    ts_inicio = dt.datetime.now(dt.timezone.utc)
    pergunta = body.pergunta.strip()
    chave = _chave_da_memoria(email, body.id_conversa)
    if not chave:
        # Sem id de conversa não há memória nem ordem a proteger, e criar
        # trava por requisição vazaria uma entrada no registro a cada chamada.
        return _perguntar_ao_agente_travado(body, contexto, chave, pergunta,
                                            resposta_original, ts_inicio, email)
    # A trava por conversa faz o ciclo ler, perguntar ao modelo e gravar ser
    # sequencial dentro da mesma conversa. Sem ela, duas requisições cruzadas
    # gravavam os turnos fora de ordem. Conversas diferentes seguem paralelas.
    with memoria.conversa(chave):
        return _perguntar_ao_agente_travado(body, contexto, chave, pergunta,
                                            resposta_original, ts_inicio, email)


def _perguntar_ao_agente_travado(body: PerguntaRequest, contexto, chave: str,
                                 pergunta: str, resposta_original: PerfilResponse,
                                 ts_inicio, email: str):
    """O ciclo da conversa com o agente, já sob a trava da conversa.

    A memória é lida sob a chave que combina a identidade autenticada com o id
    do cliente. Sem `id_conversa` não há o que lembrar. O turno do usuário é
    gravado antes da ida ao modelo, para as perguntas ficarem na ordem de
    chegada.
    """
    settings = get_settings()
    ctx = Contexto(email=email, matricula=contexto.matricula or "", setor=contexto.setor)
    historico = memoria.historico(chave)
    if chave:
        memoria.registrar(chave, "user", pergunta)
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
        resultado = orquestrador.responder(pergunta, historico=historico)
    except (LLMError, LLMTimeoutError):
        logger.warning("agente indisponivel no fallback do chat", exc_info=True)
        return _com_memoria(chave, resposta_original)
    except Exception:  # noqa: BLE001
        logger.exception("falha no fallback do chat para o agente")
        return _com_memoria(chave, resposta_original)

    if not resultado.texto.strip():
        return _com_memoria(chave, resposta_original)

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
    if chave:
        # As sugestões entram no turno guardado, ainda que saiam do texto da
        # tela: sem elas, "quero a segunda opção" não teria a que se referir
        # no histórico. Achado da revisão independente de 31/08/2026.
        guardado = resultado.texto
        if resultado.sugestoes:
            guardado += "\nSugestões oferecidas: " + " | ".join(resultado.sugestoes)
        memoria.registrar(chave, "assistant", guardado)

    # As sugestões da regra 8 viram o mesmo card que o fluxo determinístico já
    # usa, e o front já renderiza como botão. Clique em botão volta como
    # pergunta e, com o histórico acima, o agente sabe do que se trata.
    cards = [Card(type="suggestions", items=resultado.sugestoes)] if resultado.sugestoes else []
    return PerfilResponse(status="RESPOSTA_DO_AGENTE", mensagem=resultado.texto, cards=cards)
