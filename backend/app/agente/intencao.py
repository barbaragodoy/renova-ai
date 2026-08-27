"""Forma canonica da pergunta, para agrupar ocorrencias na fila de candidatas (T3.1).

Nao e o SQL, e o comentario da coluna diz por que: SQL parecido nao significa
intencao igual, e intencao igual pode gerar SQL diferente.

O que a normalizacao faz e apagar o que varia entre duas perguntas que pedem a
mesma coisa: caixa, acento, pontuacao, espaco, e sobretudo **a entidade
concreta**. "como abordar o dr loester?" e "como abordar a dra silva?" sao a
mesma intencao com medicos diferentes, e sem trocar o nome por marcador elas
nunca cairiam no mesmo grupo.

A versao viaja com a linha do log, em `versao_normalizador`. Sem ela, um
reagrupamento futuro nao sabe sob qual criterio a linha antiga foi classificada,
e comparar contagem de ocorrencias entre versoes daria numero sem sentido.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

VERSAO = "1"

# UFCRM como MG0027247, CRM solto, codigo de setor. Vem antes do numero generico
# porque `\d+` os quebraria em pedacos.
_UFCRM = re.compile(r"\b[A-Z]{2}\s?\d{4,9}\b", re.IGNORECASE)
_CODIGO = re.compile(r"\b\d{7,}\b")
_NUMERO = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_ESPACO = re.compile(r"\s+")
_PONTUACAO = re.compile(r"[^\w\s<>]", re.UNICODE)

# Tratamento, vocativo e artigo nao mudam a intencao e mudam o texto. O artigo
# entra porque a concordancia de genero separava dois grupos identicos: "vou
# visitar o <medico>" e "vou visitar a <medico>" sao a mesma pergunta.
_RUIDO = frozenset((
    "dr", "dra", "doutor", "doutora", "sr", "sra", "pfv", "obrigado", "obrigada",
    "o", "a", "os", "as", "um", "uma", "ao", "aos", "as",
))


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(pergunta: str, entidades: list[str] | None = None) -> str:
    """`entidades` sao os nomes que as ferramentas resolveram nesta interacao.

    Sem elas, "como abordar o dr loester?" e "como abordar a dra silva?" ficam
    em grupos diferentes, e a fila de candidatas da T3.1 nunca junta a pergunta
    mais comum do campo. O orquestrador passa os nomes que apareceram no
    retorno de `buscar_medico` e `perfil_do_medico`, entao a troca usa o dado
    resolvido e nao um palpite sobre qual palavra e nome proprio.

    A troca e por palavra inteira e do nome mais longo para o mais curto, para
    "LOESTER DA SILVA NEIVA JUNIOR" nao virar quatro marcadores soltos.
    """
    t = _sem_acento(pergunta or "").lower()
    for nome in sorted({_sem_acento(e or "").lower().strip() for e in (entidades or []) if e},
                       key=len, reverse=True):
        if len(nome) < 3:
            continue
        t = re.sub(rf"\b{re.escape(nome)}\b", " <medico> ", t)
        # o propagandista costuma escrever so o primeiro nome ou so o sobrenome
        for parte in nome.split():
            if len(parte) >= 4:
                t = re.sub(rf"\b{re.escape(parte)}\b", " <medico> ", t)
    t = _UFCRM.sub(" <ufcrm> ", t)
    t = _CODIGO.sub(" <codigo> ", t)
    t = _PONTUACAO.sub(" ", t)
    t = _NUMERO.sub(" <n> ", t)
    palavras = [p for p in _ESPACO.split(t) if p and p not in _RUIDO]
    # nome composto vira varios marcadores seguidos; colapsa em um
    saida = []
    for p in palavras:
        if p == "<medico>" and saida and saida[-1] == "<medico>":
            continue
        saida.append(p)
    return " ".join(saida).strip()


def hash_da_intencao(intencao_normalizada: str) -> str:
    return hashlib.sha256((intencao_normalizada or "").encode("utf-8")).hexdigest()
