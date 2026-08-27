"""As regras de composição, e o verificador que as torna barreira e não pedido.

Três das quatro regras de número da T1.2 já são cumpridas pela superfície de
dados, e não por instrução ao modelo:

- **Número absoluto de prescrição não é exibido.** As views não devolvem
  volume. `vw_agente_participacao` expõe só percentual e `vw_agente_produtos`
  usa o volume para ordenar sem publicá-lo. Não existe o número para o modelo
  exibir mesmo que queira.
- **A palavra "mercado" não aparece.** A coluna se chama `AGRUPAMENTO` na
  view. O modelo não lê a palavra em lugar nenhum.
- **O setor é do propagandista.** Nenhuma ferramenta aceita setor como
  parâmetro.

A quarta é a que precisa de código: **todo número exibido tem que existir
literalmente no retorno de alguma ferramenta desta mesma interação.** É o que
`conferir_numeros` faz. Um modelo que arredonda 3,6% para 4% está inventando
dado, e a diferença entre citar e inventar não dá para pedir por prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


PALAVRAS_PROIBIDAS = ("mercado", "mercados")

# Números soltos, nunca colados em letra. Isso deixa de fora UFCRM como
# MG0027247 e nome de produto com número.
_NUMERO = re.compile(r"(?<![A-Za-zÀ-ÿ0-9])(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)(?![A-Za-zÀ-ÿ0-9])")

# Sequência longa de dígitos sem separador não é número escrito por gente, é
# código. O setor tem 12 dígitos e cairia como número inventado, porque nenhuma
# ferramenta o devolve: o setor entra no SQL e nunca no retorno. A referência do
# ciclo tem 6 dígitos e continua sendo tratada como número, que é o certo,
# porque as ferramentas a devolvem e a regra 4 manda declará-la.
TAMANHO_DE_CODIGO = 7


def _e_codigo(bruto: str) -> bool:
    return bruto.isdigit() and len(bruto) >= TAMANHO_DE_CODIGO


# Marcador de lista ordenada no início da linha: "1. ", "2) ", "- 3. ".
# É numeração de texto, não afirmação sobre o dado.
_MARCADOR_DE_LISTA = re.compile(r"(?m)^[\s\-\*•]*\d+[.)]\s+")


def sem_marcadores_de_lista(texto: str) -> str:
    """Tira a numeração da lista antes de procurar número no texto.

    Sem isso, uma resposta com seis itens numerados era acusada de inventar o
    3 e o 5, porque 1 e 2 são livres e 6 casava com a contagem de linhas. Pior:
    a degradação removia os itens 3 e 5, e a lista perdia dois profissionais em
    silêncio. Um verificador que apaga resposta correta é pior do que a falha
    que ele existe para pegar.
    """
    return _MARCADOR_DE_LISTA.sub("", texto or "")

# Números que o texto pode usar sem estar em retorno de ferramenta: são
# aritmética de linguagem, não afirmação sobre o dado.
_LIVRES = {Decimal(0), Decimal(1), Decimal(2)}


@dataclass
class Chamada:
    """Uma chamada de ferramenta, com o que o contrato do log exige dela.

    `chamada_id` existe porque a mesma ferramenta pode ser chamada duas vezes na
    mesma interacao com parametros diferentes, e o hash do resultado nao
    distingue as duas. Sem ele, a auditoria nao sabe qual chamada sustentou
    qual numero.
    """
    chamada_id: str
    ferramenta: str
    linhas: list[dict] = field(default_factory=list)
    resultado_hash: str = ""
    parametros: str = "{}"
    latencia_ms: int = 0
    sucesso: bool = True


@dataclass
class Veredito:
    aprovado: bool
    numeros_sem_origem: list[str] = field(default_factory=list)
    palavras_proibidas: list[str] = field(default_factory=list)
    # uma linha por numero exibido, ligando o numero a chamada e ao campo que o
    # autorizou. E o que vai para `verificacao_numeros` em tb_agente_log.
    itens: list[dict] = field(default_factory=list)

    @property
    def numeros_exibidos(self) -> list[str]:
        """Construido a partir da proveniencia, e nao do texto.

        O contrato exige que todo numero em `numeros_exibidos` tenha linha de
        verificacao. Derivar um do outro torna a invariante verdadeira por
        construcao, em vez de por conferencia.
        """
        return [i["numero"] for i in self.itens]

    @property
    def motivo(self) -> str:
        partes = []
        if self.numeros_sem_origem:
            partes.append("números sem origem em ferramenta: " + ", ".join(self.numeros_sem_origem))
        if self.palavras_proibidas:
            partes.append("palavras proibidas: " + ", ".join(self.palavras_proibidas))
        return "; ".join(partes)


def _para_decimal(bruto: str) -> Decimal | None:
    """Aceita 3,6 e 3.6 e 1.234,5 como o mesmo tipo de coisa."""
    t = bruto.strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _canonico(v: Decimal) -> str:
    """Sem zeros à direita, para 3,60 e 3,6 baterem."""
    return str(v.normalize())


def universo_de_numeros(retornos: Iterable[tuple[str, list[dict[str, Any]]]]) -> set[str]:
    """Tudo que o modelo tem permissão de escrever como número.

    Entram os valores devolvidos pelas ferramentas e a **contagem de linhas**
    de cada retorno. A contagem entra porque contar a lista que a ferramenta
    devolveu é afirmação verificável, não invenção: se a busca trouxe três
    médicos, dizer "três médicos" é fiel.
    """
    universo: set[str] = {_canonico(v) for v in _LIVRES}
    for _, linhas in retornos:
        universo.add(_canonico(Decimal(len(linhas))))
        for linha in linhas:
            for valor in linha.values():
                if isinstance(valor, bool) or valor is None:
                    continue
                if isinstance(valor, (int, float, Decimal)):
                    d = _para_decimal(str(valor))
                    if d is not None:
                        universo.add(_canonico(d))
                        # o modelo costuma escrever o percentual arredondado a
                        # zero casas quando a origem é inteira em valor
                        if d == d.to_integral_value():
                            universo.add(_canonico(d.to_integral_value()))
                elif isinstance(valor, str):
                    for m in _NUMERO.finditer(valor):
                        if _e_codigo(m.group(1)):
                            continue
                        d = _para_decimal(m.group(1))
                        if d is not None:
                            universo.add(_canonico(d))
    return universo


CONTAGEM_DE_LINHAS = "<contagem_de_linhas>"
ARGUMENTO = "<argumento>"


def _procurar_origem(valor: Decimal, chamadas: Iterable[Chamada]):
    """Qual chamada e qual campo autorizam este numero. Primeira que servir.

    So chamada com sucesso conta: o contrato recusa verificacao apoiada em
    chamada que falhou, e com razao. Numero tirado de retorno de erro nao e
    dado, e coincidencia.
    """
    alvo = _canonico(valor)
    for ch in chamadas:
        if not ch.sucesso:
            continue
        if _canonico(Decimal(len(ch.linhas))) == alvo:
            return ch, CONTAGEM_DE_LINHAS
        for linha in ch.linhas:
            for campo, bruto in linha.items():
                if isinstance(bruto, bool) or bruto is None:
                    continue
                if isinstance(bruto, (int, float, Decimal)):
                    d = _para_decimal(str(bruto))
                    if d is not None and (_canonico(d) == alvo or
                                          (d == d.to_integral_value() and
                                           _canonico(d.to_integral_value()) == alvo)):
                        return ch, campo
                elif isinstance(bruto, str):
                    for m in _NUMERO.finditer(bruto):
                        if _e_codigo(m.group(1)):
                            continue
                        d = _para_decimal(m.group(1))
                        if d is not None and _canonico(d) == alvo:
                            return ch, campo
    # O argumento que o modelo passou para a ferramenta é origem legítima:
    # "sem visita há mais de 4 meses" é fiel quando 4 foi o filtro pedido, mesmo
    # que nenhuma linha devolvida tenha exatamente 4. Fica por último para um
    # valor realmente devolvido ter preferência como proveniência.
    #
    # Isso já existia e foi perdido ao trocar as tuplas de retorno pelos
    # registros de chamada: o universo passou a ignorar os argumentos, e a frase
    # com o número do filtro voltava a ser removida. Achado do julgamento
    # independente de 20/08.
    for ch in chamadas:
        if not ch.sucesso:
            continue
        for m in _NUMERO.finditer(ch.parametros or ""):
            if _e_codigo(m.group(1)):
                continue
            d = _para_decimal(m.group(1))
            if d is not None and _canonico(d) == alvo:
                return ch, ARGUMENTO
    return None, ""


def verificar(texto: str, chamadas: Iterable[Chamada]) -> Veredito:
    """Confere cada numero do texto e registra qual chamada o autorizou."""
    chamadas = list(chamadas)
    sem_origem: list[str] = []
    itens: list[dict] = []
    vistos: set[str] = set()

    for m in _NUMERO.finditer(sem_marcadores_de_lista(texto)):
        bruto = m.group(1)
        if _e_codigo(bruto):
            continue
        d = _para_decimal(bruto)
        if d is None:
            continue
        ch, campo = _procurar_origem(d, chamadas)
        if ch is not None:
            if bruto not in vistos:
                vistos.add(bruto)
                itens.append({
                    "numero": bruto, "ferramenta": ch.ferramenta,
                    "chamada_id": ch.chamada_id, "campo": campo,
                    "resultado_hash": ch.resultado_hash, "confere": True,
                })
        elif d not in _LIVRES:
            sem_origem.append(bruto)

    baixo = (texto or "").lower()
    proibidas = [p for p in PALAVRAS_PROIBIDAS if re.search(rf"\b{p}\b", baixo)]

    return Veredito(
        aprovado=not sem_origem and not proibidas,
        numeros_sem_origem=sorted(set(sem_origem)),
        palavras_proibidas=proibidas,
        itens=itens,
    )


def conferir_numeros(texto: str, retornos: Iterable[tuple[str, list[dict[str, Any]]]]) -> Veredito:
    """Forma antiga, sem proveniencia. Mantida para os testes que so olham o veredito."""
    chamadas = [Chamada(chamada_id=f"c{i}", ferramenta=nome, linhas=linhas)
                for i, (nome, linhas) in enumerate(retornos)]
    return verificar(texto, chamadas)


def degradar(texto: str, veredito: Veredito) -> str:
    """Tira as frases que carregam número sem origem, mantendo o resto.

    A T1.2 manda degradar para resposta sem o número, não recusar a resposta
    inteira. Uma frase de abordagem que não cita número continua útil.
    """
    if veredito.aprovado:
        return texto
    ruins = set(veredito.numeros_sem_origem)
    mantidas = []
    for frase in re.split(r"(?<=[.!?\n])\s+", texto or ""):
        alvo = sem_marcadores_de_lista(frase)
        if any(re.search(rf"(?<![A-Za-zÀ-ÿ0-9]){re.escape(n)}(?![A-Za-zÀ-ÿ0-9])", alvo) for n in ruins):
            continue
        mantidas.append(frase)
    limpo = " ".join(p.strip() for p in mantidas if p.strip()).strip()
    return limpo


MENSAGEM_SEM_RESPOSTA_CONFIAVEL = (
    "Não consegui montar uma resposta confiável para isso agora. "
    "Prefiro não responder a arriscar um número que não veio da base."
)

MENSAGEM_FORA_DE_ESCOPO = (
    "Isso está fora do que eu consigo responder. "
    "Eu trabalho com o seu painel: profissionais, visitas, participação e produtos da sua linha."
)


INSTRUCAO = """Você apoia um propagandista farmacêutico da Aché durante o trabalho de campo.

COMO RESPONDER
- Responda em português do Brasil, direto, no tom de um colega experiente.
- Vá ao ponto. Sem saudação, sem repetir a pergunta, sem oferecer ajuda extra no fim.
- Quando a pergunta for sobre um profissional, use buscar_medico primeiro para
  obter o UFCRM, e depois as outras ferramentas com esse UFCRM.
- Combine as ferramentas que a pergunta pedir. Uma pergunta sobre abordagem
  costuma precisar do perfil, dos produtos e da participação.

REGRAS QUE NÃO TÊM EXCEÇÃO
1. Todo número que você escrever tem que aparecer literalmente em algum
   retorno de ferramenta desta conversa. Não arredonde, não converta, não
   estime, não some. Copie a forma exata que a ferramenta devolveu, inclusive
   a vírgula decimal e o sinal de percentual: se veio "3,6%", escreva 3,6% e
   nunca 3.6% nem 3,6 por cento.
2. Nunca escreva a palavra "mercado". Diga "agrupamento" ou nomeie a categoria.
3. Conteúdo clínico é sempre uso observado, nunca indicação. Escreva "o que se
   observa na prescrição dele" e nunca "o indicado para".
4. Ao usar dado do painel, encerre com "Dados de <valor>." onde <valor> é o
   conteúdo do campo CICLO_REFERENCIA ou REFERENCIA que a ferramenta devolveu.
   Nunca escreva ali o nome da ferramenta nem uma descrição da busca.
5. Se a ferramenta não devolveu nada, diga que não encontrou. Nunca preencha
   a lacuna com conhecimento próprio. Na busca de conhecimento, antes de
   desistir, tente uma segunda vez com o termo completado ou corrigido.
   Quando usar conteúdo da base de conhecimento, diga de onde veio, citando o
   documento que a ferramenta devolveu em "documentos".
6. Se a pergunta não for sobre o painel, sobre visitas, sobre participação ou
   sobre produtos da linha, recuse com honestidade e diga o que você faz.
7. Nunca elogie um profissional que a recomendação manda tirar do painel.
"""
