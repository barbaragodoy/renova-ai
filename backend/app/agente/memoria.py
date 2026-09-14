"""A memória de conversa, e por que ela mora aqui e não no modelo.

O modelo não guarda nada entre chamadas: toda "memória" de LLM é alguém
reenviando o histórico junto com a pergunta. Este módulo é esse alguém. Ele
existe porque o teste de 27/08/2026 mostrou o custo da ausência: o agente
oferecia opções e, na mensagem seguinte, tratava a escolha como conversa nova.
"Quero a lista de pendências", escolhida entre as opções que ele mesmo deu,
voltava "não encontrei ninguém".

Três autores escrevem na mesma janela: a resposta determinística, o agente e
as mensagens fixas de borda. A memória é uma só, indexada por `id_conversa`,
para que o agente saiba o que os outros dois disseram.

O armazenamento é em processo, num dicionário com trava. Isso basta porque o
portal roda num único container e a conversa é curta e efêmera: perder o
histórico num restart custa uma pergunta reformulada, não um dado. Se um dia
houver mais de uma réplica, isto vira tabela; a interface não muda.

O limite de turnos existe pela janela do modelo e pelo custo: cada turno
guardado é reenviado em toda pergunta seguinte da mesma conversa.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

MAX_TURNOS = 12          # pares pergunta/resposta reenviados ao modelo
TTL_SEGUNDOS = 60 * 60   # conversa parada some depois de uma hora
MAX_CONVERSAS = 500      # teto de conversas simultâneas guardadas

_trava = threading.Lock()
_conversas: dict[str, dict] = {}


def _limpar_vencidas(agora: float) -> None:
    vencidas = [k for k, v in _conversas.items() if agora - v["tocada_em"] > TTL_SEGUNDOS]
    for k in vencidas:
        del _conversas[k]


def _conter_no_teto() -> None:
    """Sob pressão, cai a conversa parada há mais tempo, nunca a mais recente.

    Chamada depois da inserção, e não antes: a revisão independente de
    31/08/2026 mostrou que a limpeza antes da inserção deixava o dicionário
    estabilizar em 501 conversas com o teto declarado de 500.
    """
    while len(_conversas) > MAX_CONVERSAS:
        mais_antiga = min(_conversas, key=lambda k: _conversas[k]["tocada_em"])
        del _conversas[mais_antiga]


def registrar(id_conversa: str, papel: str, texto: str) -> None:
    """Anota um turno. `papel` é "user" ou "assistant", no vocabulário do modelo."""
    if not id_conversa or not (texto or "").strip():
        return
    agora = time.time()
    with _trava:
        _limpar_vencidas(agora)
        conversa = _conversas.setdefault(id_conversa, {"turnos": [], "tocada_em": agora})
        conversa["turnos"].append({"role": papel, "content": texto.strip()})
        conversa["tocada_em"] = agora
        excesso = len(conversa["turnos"]) - MAX_TURNOS * 2
        if excesso > 0:
            del conversa["turnos"][:excesso]
        _conter_no_teto()


def historico(id_conversa: str) -> list[dict]:
    """Os turnos da conversa, prontos para entrar entre o system e a pergunta.

    O TTL vale também na leitura: uma conversa parada além do prazo é
    descartada aqui, em vez de revivida pelo toque. Sem isso, a leitura
    atualizava `tocada_em` e a conversa vencida nunca expirava de fato.
    Achado da segunda rodada da revisão independente de 31/08/2026.
    """
    if not id_conversa:
        return []
    agora = time.time()
    with _trava:
        conversa = _conversas.get(id_conversa)
        if not conversa:
            return []
        if agora - conversa["tocada_em"] > TTL_SEGUNDOS:
            del _conversas[id_conversa]
            return []
        conversa["tocada_em"] = agora
        return list(conversa["turnos"])


def esquecer(id_conversa: str) -> None:
    with _trava:
        _conversas.pop(id_conversa, None)
        _travas_por_conversa.pop(id_conversa, None)


_travas_por_conversa: dict[str, threading.Lock] = {}


def _conter_travas(exceto: str) -> None:
    """Remove toda trava morta: sem conversa viva, sem uso neste instante.

    O invariante é de pertencimento, não de número: o registro só guarda
    travas de conversas vivas ou em voo. Como `_conversas` já é limitado por
    `MAX_CONVERSAS`, o registro fica limitado por consequência, sem teto
    próprio. A quinta rodada da revisão de 31/08/2026 mostrou por que um teto
    numérico aqui era o contrato errado: com 500 conversas vivas, a trava 501
    em voo é legítima e não há o que remover.

    Trava em uso nunca é removida, nem a da chave sendo pedida agora
    (`exceto`): removê-la recém-criada reabriria a corrida que a
    reconferência de `conversa()` fecha.
    """
    mortas = [k for k, tr in _travas_por_conversa.items()
              if k != exceto and k not in _conversas and not tr.locked()]
    for k in mortas:
        del _travas_por_conversa[k]


@contextmanager
def conversa(id_conversa: str):
    """Seção crítica de uma conversa: ler histórico, perguntar e gravar.

    Sem ela, duas requisições da mesma conversa podiam terminar fora de ordem
    e gravar `user A, user B, assistant B, assistant A`. Conversa é sequencial
    por natureza; conversas diferentes continuam em paralelo. O custo é a
    segunda requisição da mesma conversa esperar a primeira, limitada pelo
    timeout do modelo.

    A aquisição reconfere o registro depois de obter a trava. A quarta rodada
    da revisão de 31/08/2026 provou a janela: a contenção podia remover uma
    trava desbloqueada entre a devolução ao chamador e o `acquire`, e duas
    requisições da mesma conversa seguiam juntas, cada uma com um objeto.
    Depois do `acquire`, `locked()` é verdadeiro e a contenção não a remove
    mais; se a reconferência achar outro objeto no registro, solta e tenta de
    novo.
    """
    while True:
        with _trava:
            tr = _travas_por_conversa.setdefault(id_conversa, threading.Lock())
            _conter_travas(exceto=id_conversa)
        tr.acquire()
        with _trava:
            if _travas_por_conversa.get(id_conversa) is tr:
                break
        tr.release()
    try:
        yield
    finally:
        tr.release()
