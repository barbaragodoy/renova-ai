"""Escrita idempotente em `tb_agente_log`, pelo executor SQL do portal.

O escritor da Fase 0, `agente-fase0/escritor_log.py`, monta um DataFrame e
executa o MERGE por Spark. O portal nao tem Spark: ele fala com o warehouse por
SQLAlchemy. Este modulo faz a mesma coisa com SQL parametrizado.

**A troca de Spark por SQL apaga uma classe inteira de defeito.** O escritor da
Fase 0 precisa de uma view temporaria como origem do MERGE, e o comentario de la
registra duas versoes quebradas do nome dessa view: nome fixo se sobrescrevia
entre gravacoes concorrentes, e nome derivado da chave se sobrescrevia entre uma
repeticao e a original. Aqui a origem e um `SELECT` de literais dentro do proprio
comando, entao nao existe objeto intermediario para duas execucoes disputarem.

O MERGE nao tem `WHEN MATCHED`, de proposito e pelo mesmo motivo da Fase 0:
reenvio da mesma interacao e operacao sem efeito, e nao atualizacao. A resposta
ja registrada e a que valeu para o usuario, e reescrever apagaria a evidencia do
que ele viu.

O contrato e `contrato_log.py`, copia do arquivo que passou pelo G1.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from decimal import Decimal
from typing import Any

from backend.app.agente import contrato_log, intencao

logger = logging.getLogger(__name__)

CHAVE = "id_interacao"
VERSAO_ESQUEMA = 2
VIAS = ("via_1", "via_2", "conhecimento", "recusa")

# Marcador para citacao sem passagem identificada. Texto declarado, e nao hash,
# para nao se confundir com um hash de passagem real na auditoria.
SEM_TRECHO = "SEM_TRECHO"

# nome da coluna -> tipo SQL para o CAST da origem. Sem o CAST, uma interacao
# comum, em que a maioria das colunas e nula, faria o Databricks nao saber o
# tipo do literal NULL e recusar o MERGE.
COLUNAS: dict[str, str] = {
    "id_interacao": "STRING", "id_conversa": "STRING", "turno": "INT",
    "ts_inicio": "TIMESTAMP", "ts_fim": "TIMESTAMP", "dt_referencia": "DATE",
    "origem": "STRING", "rep_matricula": "STRING", "setor": "STRING", "cod_linha": "STRING",
    "pergunta_original": "STRING", "via": "STRING", "ferramentas": "STRING",
    "sql_gerado": "STRING", "sql_hash": "STRING", "resultado_hash": "STRING",
    "resultado_linhas": "INT", "resposta_texto": "STRING", "numeros_exibidos": "STRING",
    "documentos_citados": "STRING", "kb_versao": "STRING", "modelo_endpoint": "STRING",
    "tokens_entrada": "INT", "tokens_saida": "INT", "latencia_total_ms": "INT",
    "latencia_modelo_ms": "INT", "latencia_consulta_ms": "INT", "sucesso": "BOOLEAN",
    "erro_tipo": "STRING", "erro_mensagem": "STRING", "versao_esquema": "INT",
    "intencao_normalizada": "STRING", "intencao_hash": "STRING",
    "versao_normalizador": "STRING", "verificacao_numeros": "STRING",
    "verificacao_aprovada": "BOOLEAN", "chamadas_modelo": "STRING",
    "custo_total": "DECIMAL(12,6)", "custo_moeda": "STRING",
}


# Nomes de tipo do Databricks/Spark SQL que o Postgres não reconhece (STRING,
# INT) — o resto (TIMESTAMP, DATE, BOOLEAN, DECIMAL) é válido nos dois.
# Achado em teste de fumaça real (26/08/2026): sem isto, todo CAST(:x AS
# STRING) falhava contra Postgres local com "type string does not exist",
# o que quebrava toda gravação em tb_agente_log — ou seja, toda interação
# real com o chat/agente, não só um caso de borda.
_TIPOS_POSTGRES = {"STRING": "TEXT", "INT": "INTEGER"}


def sql_merge(tabela: str) -> str:
    from backend.app.config import get_settings

    databricks = get_settings().data_source.lower() == "databricks"

    def _tipo(tipo: str) -> str:
        return tipo if databricks else _TIPOS_POSTGRES.get(tipo, tipo)

    origem = ",\n           ".join(f"CAST(:{c} AS {_tipo(tipo)}) AS {c}" for c, tipo in COLUNAS.items())
    nomes = ", ".join(COLUNAS)
    valores = ", ".join(f"o.{c}" for c in COLUNAS)
    return (f"MERGE INTO {tabela} AS d\n"
            f"USING (SELECT {origem}) AS o\n"
            f"ON d.{CHAVE} = o.{CHAVE}\n"
            f"WHEN NOT MATCHED THEN INSERT ({nomes}) VALUES ({valores})")


def montar(resposta, ctx, id_conversa: str, turno: int, ts_inicio: dt.datetime,
           origem: str = "portal", kb_versao: str | None = None) -> dict[str, Any]:
    """Monta a linha a partir do que o orquestrador coletou, validando o contrato."""
    if resposta.via not in VIAS:
        raise contrato_log.ContratoInvalido(
            f"via {resposta.via!r} fora do dominio {VIAS}. A restricao existe tambem na tabela, "
            f"e gravar aqui falharia depois de ja ter feito o trabalho.")

    veredito = resposta.veredito
    itens = list(getattr(veredito, "itens", []) or [])
    numeros = [i["numero"] for i in itens]

    ferramentas = [{
        "chamada_id": c.chamada_id, "ferramenta": c.ferramenta, "parametros": c.parametros,
        "resultado_hash": c.resultado_hash, "linhas": len(c.linhas),
        "latencia_ms": c.latencia_ms, "sucesso": c.sucesso,
    } for c in resposta.chamadas]

    chamadas_modelo = [dict(c) for c in resposta.chamadas_modelo]
    tokens_entrada = sum(c["tokens_entrada"] for c in chamadas_modelo) if chamadas_modelo else None
    tokens_saida = sum(c["tokens_saida"] for c in chamadas_modelo) if chamadas_modelo else None
    custo, moeda = contrato_log.custo_total(chamadas_modelo)

    normalizada = intencao.normalizar(resposta.pergunta, _nomes(resposta.chamadas))
    # Uma entrada por passagem citada, e nao por documento: o KA cita mais de
    # um trecho do mesmo arquivo numa resposta.
    #
    # Quando nao ha hash de passagem, o campo recebe o marcador SEM_TRECHO e nao
    # um hash do nome do arquivo. O contrato exige texto nao vazio, mas gravar
    # um hash ali faria a evidencia mentir: quem auditar leria um hash de
    # passagem onde nunca houve passagem. Achado do julgamento independente de
    # 20/08.
    trechos = getattr(resposta, "trechos_citados", {}) or {}
    documentos = []
    for d in resposta.documentos_citados:
        hashes = trechos.get(d) or []
        if isinstance(hashes, str):
            hashes = [hashes]
        for h in (hashes or [SEM_TRECHO]):
            documentos.append({"documento": d, "trecho_hash": h})

    contrato_log.conferir_coerencia(itens, ferramentas, chamadas_modelo, numeros,
                                    tokens_entrada, tokens_saida, custo, moeda)

    agora = dt.datetime.now(dt.timezone.utc)
    linha = {
        "id_interacao": contrato_log.id_interacao(id_conversa, turno, resposta.pergunta),
        "id_conversa": id_conversa, "turno": turno,
        "ts_inicio": ts_inicio, "ts_fim": agora,
        # o dia da interacao no fuso de Sao Paulo e a chave de expurgo da T1B.4
        "dt_referencia": (agora - dt.timedelta(hours=3)).date(),
        "origem": origem,
        "rep_matricula": ctx.matricula or None, "setor": ctx.setor, "cod_linha": ctx.linha,
        "pergunta_original": resposta.pergunta, "via": resposta.via,
        "ferramentas": contrato_log.serializar_ferramentas(ferramentas),
        # a via 2 nao existe ainda: sem SQL gerado, nao ha consulta unica cujo
        # resultado descrever, e inventar um agregado das varias chamadas da
        # via 1 daria um numero que nao corresponde a consulta nenhuma
        "sql_gerado": None, "sql_hash": None,
        "resultado_hash": None, "resultado_linhas": None,
        "resposta_texto": resposta.texto,
        "numeros_exibidos": contrato_log._empacotar("numeros", numeros),
        "documentos_citados": contrato_log.serializar_documentos(documentos),
        "kb_versao": kb_versao,
        "modelo_endpoint": (chamadas_modelo[0]["endpoint"] if chamadas_modelo else None),
        "tokens_entrada": tokens_entrada, "tokens_saida": tokens_saida,
        "latencia_total_ms": resposta.ms,
        "latencia_modelo_ms": resposta.ms_modelo,
        "latencia_consulta_ms": resposta.ms_consulta,
        # degradar e falhar do ponto de vista do usuario: ele recebeu menos do
        # que o agente tentou entregar
        "sucesso": not resposta.degradada,
        "erro_tipo": ("verificacao_degradou" if resposta.degradada else None),
        "erro_mensagem": (resposta.motivo_degradacao or None) if resposta.degradada else None,
        "versao_esquema": VERSAO_ESQUEMA,
        "intencao_normalizada": normalizada,
        "intencao_hash": intencao.hash_da_intencao(normalizada),
        "versao_normalizador": intencao.VERSAO,
        "verificacao_numeros": contrato_log.serializar_verificacao(itens),
        "verificacao_aprovada": contrato_log.verificacao_aprovada(itens),
        "chamadas_modelo": contrato_log.serializar_chamadas(chamadas_modelo),
        "custo_total": custo, "custo_moeda": moeda,
    }
    return {c: linha.get(c) for c in COLUNAS}


def _nomes(chamadas) -> list[str]:
    nomes: list[str] = []
    for ch in chamadas:
        for l in ch.linhas:
            n = l.get("NOME_MEDICO") if isinstance(l, dict) else None
            if n and n not in nomes:
                nomes.append(n)
    return nomes


def gravar(executor, tabela: str, linha: dict[str, Any]) -> str:
    """Executa o MERGE. Devolve o id_interacao."""
    executor.query(sql_merge(tabela), _para_sql(linha))
    return linha["id_interacao"]


def _para_sql(linha: dict[str, Any]) -> dict[str, Any]:
    """Decimal vai como texto: o driver nao tem tipo proprio e o CAST resolve."""
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in linha.items()}


def registrar(executor, tabela, resposta, ctx, id_conversa, turno, ts_inicio,
              origem="portal", kb_versao=None) -> str | None:
    """Monta e grava, **sem nunca derrubar a resposta do usuario**.

    O log e para nos. Uma falha aqui vira aviso no log da aplicacao e a resposta
    segue para quem perguntou. O caminho contrario, deixar a excecao subir,
    trocaria uma interacao boa por um erro 500 por causa de telemetria.
    """
    try:
        return gravar(executor, tabela, montar(resposta, ctx, id_conversa, turno, ts_inicio,
                                               origem, kb_versao))
    except contrato_log.ContratoInvalido:
        logger.exception("agente: linha de log recusada pelo contrato, interacao nao registrada")
    except Exception:  # noqa: BLE001
        logger.exception("agente: falha ao gravar em %s", tabela)
    return None
