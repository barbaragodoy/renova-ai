# -*- coding: utf-8 -*-
"""
Contrato dos campos JSON de tb_agente_log e da chave de idempotencia da escrita.
Fechado antes da T1.2 gravar a primeira linha. Sem Spark e sem rede.

**Copia de**
`databricks-ped-ache/03-genie-consultivo/agente-fase0/contrato_log.py`, o
arquivo que passou pelo gate G1. Esta copia existe porque o portal nao alcanca
o repositorio do Databricks e o modulo nao tem dependencia nenhuma.

Os dois precisam mudar juntos. O escritor do portal e hoje o unico produtor de
linha em `tb_agente_log`, entao uma divergencia aparece primeiro aqui, mas o
notebook da Fase 0 e a versao que o G1 aprovou.
"""

import decimal
import hashlib
import json
import math

# Achado 6 da segunda rodada do G1: `verificacao_numeros` e `chamadas_modelo` nasceram como
# JSON livre. Texto livre dentro de coluna de auditoria vira formato diferente por versao do
# orquestrador, e a Fase 3 nao consegue reprocessar o que nao sabe ler. O contrato entra antes
# da primeira gravacao, quando ainda nao custa nada.
VERSAO_CONTRATO = 1

# Um item por numero que apareceu na resposta. `chamada` amarra o numero a chamada especifica
# que o autorizou, e nao so a ferramenta: a mesma ferramenta pode ser chamada duas vezes na
# mesma interacao com parametros diferentes, e o hash global do resultado nao distingue as
# duas. Sem isso a auditoria da T1.2 nao fecha.
CAMPOS_VERIFICACAO = ("numero", "ferramenta", "chamada_id", "campo", "resultado_hash", "confere")

# Uma entrada por chamada ao modelo. Decisao D10: custo auditavel, e nao projetado.
CAMPOS_CHAMADA = ("chamada_id", "endpoint", "modelo", "tokens_entrada", "tokens_saida",
                  "tokens_cache", "tarifa_entrada", "tarifa_saida", "moeda", "custo")


class ContratoInvalido(ValueError):
    pass


# Achado 2 da segunda rodada do G1: a primeira versao so conferia presenca de campo. Isso
# aceitava `confere="false"` como texto, que e verdadeiro em Python e aprovava a verificacao;
# aceitava token e custo negativos; e aceitava `chamada_id` repetido. Os quatro defeitos foram
# reproduzidos em execucao direta em 19/08 antes de escrever isto.
TEXTO, INTEIRO, DECIMAL, BOOLEANO = "texto", "inteiro", "decimal", "booleano"

CAMPOS_VERIFICACAO = {
    "numero": TEXTO, "ferramenta": TEXTO, "chamada_id": TEXTO, "campo": TEXTO,
    "resultado_hash": TEXTO, "confere": BOOLEANO,
}
CAMPOS_CHAMADA = {
    "chamada_id": TEXTO, "endpoint": TEXTO, "modelo": TEXTO, "tokens_entrada": INTEIRO,
    "tokens_saida": INTEIRO, "tokens_cache": INTEIRO, "tarifa_entrada": DECIMAL,
    "tarifa_saida": DECIMAL, "moeda": TEXTO, "custo": DECIMAL,
}
CAMPOS_FERRAMENTA = {
    "chamada_id": TEXTO, "ferramenta": TEXTO, "parametros": TEXTO,
    "resultado_hash": TEXTO, "linhas": INTEIRO, "latencia_ms": INTEIRO, "sucesso": BOOLEANO,
}
CAMPOS_DOCUMENTO = {"documento": TEXTO, "trecho_hash": TEXTO}


def _validar_valor(nome, campo, valor, tipo):
    if tipo is BOOLEANO:
        if not isinstance(valor, bool):
            raise ContratoInvalido(
                f"{nome}.{campo} precisa ser booleano, veio {type(valor).__name__} ({valor!r}). "
                f"Texto nao vazio como 'false' seria lido como verdadeiro.")
        return
    if tipo is TEXTO:
        if not isinstance(valor, str) or not valor.strip():
            raise ContratoInvalido(f"{nome}.{campo} precisa ser texto nao vazio, veio {valor!r}")
        return
    # `Decimal` entra aqui em 19/08. A primeira versao so aceitava int e float, e
    # recusava justamente o tipo que a coluna `decimal(12,6)` pede: tarifa e custo em
    # float acumulam erro de arredondamento na soma, e `custo_total` soma chamada por
    # chamada. Reproduzido na primeira gravacao real da T1.2.
    if isinstance(valor, bool) or not isinstance(valor, (int, float, decimal.Decimal)):
        raise ContratoInvalido(f"{nome}.{campo} precisa ser numero, veio {valor!r}")
    if tipo is INTEIRO and not isinstance(valor, int):
        # `1.0` passava por `float(...).is_integer()`. Contagem de token que chega como
        # decimal denuncia calculo errado a montante, e aceitar esconde o defeito.
        raise ContratoInvalido(f"{nome}.{campo} precisa ser inteiro, veio {valor!r}")
    if math.isnan(valor) or math.isinf(valor):
        # NaN passava pela checagem de negativo, porque toda comparacao com NaN e falsa.
        raise ContratoInvalido(f"{nome}.{campo} precisa ser numero finito, veio {valor!r}")
    if valor < 0:
        raise ContratoInvalido(f"{nome}.{campo} nao pode ser negativo, veio {valor!r}")


def _validar_lista(itens, campos, nome, chave_unica=None):
    if not isinstance(itens, list):
        raise ContratoInvalido(f"{nome} precisa ser uma lista, veio {type(itens).__name__}")
    vistos = set()
    for i, item in enumerate(itens):
        if not isinstance(item, dict):
            raise ContratoInvalido(f"{nome}[{i}] precisa ser objeto")
        faltando = [c for c in campos if c not in item]
        if faltando:
            raise ContratoInvalido(f"{nome}[{i}] sem os campos {faltando}")
        sobrando = [c for c in item if c not in campos]
        if sobrando:
            raise ContratoInvalido(f"{nome}[{i}] com campos nao previstos {sobrando}")
        for campo, tipo in campos.items():
            _validar_valor(f"{nome}[{i}]", campo, item[campo], tipo)
        if chave_unica:
            valor = item[chave_unica]
            if valor in vistos:
                raise ContratoInvalido(f"{nome} com {chave_unica} repetido: {valor!r}")
            vistos.add(valor)
    return itens


def validar_lista_de_texto(itens, nome):
    """Lista de texto nao vazio. `numeros_exibidos` entrava sem nenhuma checagem."""
    if not isinstance(itens, list):
        raise ContratoInvalido(f"{nome} precisa ser uma lista, veio {type(itens).__name__}")
    for i, item in enumerate(itens):
        if not isinstance(item, str) or not item.strip():
            raise ContratoInvalido(f"{nome}[{i}] precisa ser texto nao vazio, veio {item!r}")
    return itens


def _serializar_decimal(valor):
    """`Decimal` vira texto no JSON, nunca float.

    O JSON nao tem tipo decimal. Converter para float aqui reintroduziria o erro
    de arredondamento que o `Decimal` existe para evitar, e o custo por chamada
    e justamente o que a decisao D10 quer auditavel. Texto preserva o valor
    exato e quem le reconstroi com `Decimal(...)`.
    """
    if isinstance(valor, decimal.Decimal):
        return str(valor)
    raise TypeError(f"{type(valor).__name__} nao e serializavel no contrato do log")


def _empacotar(chave, itens):
    return json.dumps({"versao": VERSAO_CONTRATO, chave: itens},
                      default=_serializar_decimal,
                      ensure_ascii=False, sort_keys=True)


def serializar_ferramentas(chamadas):
    """Uma entrada por chamada de ferramenta. E o objeto que a verificacao aponta."""
    return _empacotar("ferramentas",
                      _validar_lista(chamadas, CAMPOS_FERRAMENTA, "ferramentas", "chamada_id"))


def serializar_verificacao(itens):
    """Valida e serializa a evidencia da verificacao do compositor."""
    return _empacotar("itens", _validar_lista(itens, CAMPOS_VERIFICACAO, "verificacao_numeros"))


def serializar_chamadas(chamadas):
    """Valida e serializa o detalhe de custo por chamada ao modelo."""
    return _empacotar("chamadas",
                      _validar_lista(chamadas, CAMPOS_CHAMADA, "chamadas_modelo", "chamada_id"))


def serializar_documentos(documentos):
    """Documentos da KB citados na resposta de conhecimento."""
    return _empacotar("documentos",
                      _validar_lista(documentos, CAMPOS_DOCUMENTO, "documentos_citados"))


def conferir_coerencia(verificacao, ferramentas, chamadas_modelo, numeros_exibidos,
                       tokens_entrada, tokens_saida, custo, moeda):
    """
    Invariantes entre as colunas. Sozinha, cada lista pode estar bem formada e o conjunto
    mentir: numero exibido que nao aparece na verificacao, verificacao apontando para chamada
    de ferramenta que nao existe, e token ou custo agregado que nao bate com a soma das
    chamadas. Achado 2 da segunda rodada do G1.
    """
    por_id = {f["chamada_id"]: f for f in ferramentas}
    for item in verificacao:
        chamada = por_id.get(item["chamada_id"])
        if chamada is None:
            raise ContratoInvalido(
                f"verificacao aponta para a chamada {item['chamada_id']!r}, que nao esta em "
                f"ferramentas")
        # Conferir so a existencia do identificador deixava a verificacao afirmar uma
        # ferramenta e um hash que nao sao os da chamada apontada, o que e exatamente o tipo de
        # inconsistencia que a auditoria da T1.2 precisa poder descartar.
        if item["ferramenta"] != chamada["ferramenta"]:
            raise ContratoInvalido(
                f"verificacao diz ferramenta {item['ferramenta']!r}, mas a chamada "
                f"{item['chamada_id']!r} e de {chamada['ferramenta']!r}")
        if item["resultado_hash"] != chamada["resultado_hash"]:
            raise ContratoInvalido(
                f"verificacao traz resultado_hash diferente do que a chamada "
                f"{item['chamada_id']!r} registrou")
        if not chamada["sucesso"]:
            raise ContratoInvalido(
                f"verificacao apoia-se na chamada {item['chamada_id']!r}, que falhou")
    if sorted(numeros_exibidos) != sorted(i["numero"] for i in verificacao):
        raise ContratoInvalido(
            "numeros_exibidos e os numeros verificados divergem: todo numero que apareceu na "
            "resposta precisa ter uma linha de verificacao")
    # Interacao servida so por funcao governada nao chama modelo: os agregados sao nulos, e
    # comparar nulo com zero reprovaria o caminho mais comum da via 1.
    if not chamadas_modelo:
        if (tokens_entrada, tokens_saida, custo, moeda) != (None, None, None, None):
            raise ContratoInvalido(
                "interacao sem chamada ao modelo nao pode ter token nem custo agregado")
        return
    soma_entrada = sum(c["tokens_entrada"] for c in chamadas_modelo)
    soma_saida = sum(c["tokens_saida"] for c in chamadas_modelo)
    if (tokens_entrada, tokens_saida) != (soma_entrada, soma_saida):
        raise ContratoInvalido(
            f"tokens agregados ({tokens_entrada}, {tokens_saida}) nao batem com a soma das "
            f"chamadas ({soma_entrada}, {soma_saida})")
    soma_custo, moeda_calculada = custo_total(chamadas_modelo)
    if (soma_custo, moeda_calculada) != (custo, moeda):
        raise ContratoInvalido(
            f"custo agregado ({custo} {moeda}) nao bate com a soma das chamadas "
            f"({soma_custo} {moeda_calculada})")


def custo_total(chamadas):
    """Soma o custo das chamadas, exigindo moeda unica. Moeda misturada e erro, nao media."""
    if not chamadas:
        return None, None
    moedas = {c["moeda"] for c in chamadas}
    if len(moedas) > 1:
        raise ContratoInvalido(f"chamadas em mais de uma moeda: {sorted(moedas)}")
    return sum(c["custo"] for c in chamadas), moedas.pop()


def verificacao_aprovada(itens):
    """Falso se algum numero exibido nao foi confirmado no retorno de alguma ferramenta."""
    for i, item in enumerate(itens):
        _validar_valor("verificacao_numeros[%d]" % i, "confere", item.get("confere"), BOOLEANO)
    return all(item["confere"] for item in itens)


def id_interacao(id_conversa, turno, pergunta_original):
    """
    Chave de idempotencia deterministica.

    A primeira versao concatenava com `|`, e a chave colidia quando o proprio dado continha o
    separador: conversa `conv|1` com turno `2` dava a mesma chave que conversa `conv` com turno
    `1|2`. Reproduzido em 19/08. Agora a serializacao e canonica e sem ambiguidade.
    """
    # `int(turno)` colapsava `2`, `"2"` e `2.9` na mesma chave. O turno vem como inteiro do
    # orquestrador; qualquer outra coisa e defeito de quem chama, nao valor a converter.
    if isinstance(turno, bool) or not isinstance(turno, int):
        raise ContratoInvalido(f"turno precisa ser inteiro, veio {turno!r}")
    origem = json.dumps([str(id_conversa), turno, str(pergunta_original)],
                        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(origem.encode("utf-8")).hexdigest()
