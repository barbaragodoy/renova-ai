"""Escala aprovada da passada S no recorte de 9.571 comentários distintos.

Combina somente decisões da passada de adoção: revisão manual dos textos mais
frequentes, corte curto validado, gabarito individual do piloto e novas
chamadas individuais ao Sonnet. Não lê nem grava artefatos da passada N.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from barreiras_comum import configuracao, extrair_distintos, gravar_jsonl, ler_jsonl
from descobrir_barreiras_adocao_piloto import PROMPT


DESTINO = Path("docs/analises/barreiras_adocao_piloto")
EXTRACOES = DESTINO / "extracoes_escala_individual.jsonl"

SEM_CONTEUDO_EXATOS = {
    "", "-", "RELEMBREI", "RELEMBREI MARCAS", "VISITA REMOTA", "VISITA REMOTO",
    "SEM COMENTARIOS", "NAO FEZ COMENTARIOS", "FOCO PRODUTO ALVO",
    "REFORCO DE MARCAS", "REFORCO MARCAS", "PECA PROMOCIONAL", "VISITA EXPOSITIVA",
    "RECALL DAS MARCAS", "REUNIAO MEDICA", "ENTREGA DE MATERIAL SOLICITADO",
    "VISITA RESTRITA", "FALEI DE NOSSA LINHA", "FALEI DE TODA A LINHA",
    "FOCO NOVAMOX", "FOCO NAUTEX E PROVANCE", "TRABALHADO PACIENTE COM TDM",
    "REFORCO DAS MARCAS PRESCRITAS", "EDISTRIDE E TREZOR", "ANALGESIA TORMIV ODG",
    "AQUARELA AXONIUM", "EXODUS E TOLREST", "OPT COM TD GRADE", "FOCO AUDIT",
    "FOCO ANTIBIOTICOS", "FOCO EM NAUTEX", "FOCO BUSONID", "FOCO ATBS NO CPV",
    "REUNIAO NO SERVICO", "REUNIAO FUNDACAO IDEIA FERTIL",
}

# Casos factuais encontrados na leitura integral dos 99 textos curtos. Eles
# dispensam modelo, mas não podem ser fundidos com ausência de conteúdo.
CURTOS_COM_CONTEUDO = {
    "SOLICITOU MOTORE", "NÃO QUIZ AMOSTRAS", "OPPRTUNIDADE FUSOR",
    "PARCERIA , CUPONS", "ETIRA SAINDO", "DR NAO LOCALIZADO",
    "FICOU DE PRESCREVER", "OPT COM TD GRAD3", "OPT COM TD GRAEE",
    "MAIS APOIO NAUCLOZ",
}


def carregar_snapshot() -> list[dict]:
    dados = json.loads((DESTINO / "fonte_snapshot.json").read_text(encoding="utf-8"))
    nomes = [c["name"] for c in dados["schema"]]
    return [dict(zip(nomes, linha)) for linha in dados["rows"]]


def normalizar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto.upper())
                         if unicodedata.category(c) != "Mn")
    return re.sub(r" +", " ", re.sub(r"[^A-Z0-9 ]+", " ", sem_acento)).strip()


def resultado_manual(item: dict, origem: str) -> dict:
    return {
        "comentario_sha256": item["comentario_sha256"],
        "comentario": item.get("texto") or item.get("comentario"),
        "estado": "DECISAO_SEM_MODELO",
        "classe": item["decisao"],
        "tem_barreira": item["tem_barreira_adocao"],
        "barreira_bruta": item.get("barreira_bruta"),
        "origem_decisao": origem,
        "tokens_entrada": 0,
        "tokens_saida": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trabalhadores", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.trabalhadores <= 24:
        raise ValueError("trabalhadores deve estar entre 1 e 24")

    visitas = carregar_snapshot()
    textos = list(dict.fromkeys(v["COMENTARIOS"] for v in visitas))
    if len(visitas) != 9940 or len(textos) != 9571:
        raise RuntimeError("recorte aprovado mudou; escala interrompida")

    manuais = {x["texto"]: x for x in ler_jsonl(DESTINO / "classificacoes_manuais.jsonl")}
    gabarito = {x["comentario"]: x for x in ler_jsonl(DESTINO / "gabarito_piloto.jsonl")}
    if len(manuais) != 250 or len(gabarito) != 150:
        raise RuntimeError("artefatos validados incompletos")
    curtos = {x for x in textos if len(x.strip()) < 20}
    if len(curtos) != 99:
        raise RuntimeError("universo do corte de 20 caracteres mudou")

    elegiveis = [x for x in textos if x not in manuais and x not in curtos]
    pendentes_modelo = [x for x in elegiveis if x not in gabarito]
    if len(elegiveis) != 9247 or len(pendentes_modelo) != 9101:
        raise RuntimeError("partição da escala não corresponde à validação")

    _, modelo = configuracao()
    extraidos = extrair_distintos(
        modelo, pendentes_modelo, PROMPT, "tem_barreira_adocao", EXTRACOES,
        trabalhadores=args.trabalhadores,
    )
    por_texto_modelo = {x["comentario"]: x for x in extraidos}

    resultados = []
    for comentario in textos:
        sha = hashlib.sha256(comentario.encode()).hexdigest()
        if comentario in manuais:
            resultados.append(resultado_manual(manuais[comentario], "CLASSIFICACAO_MANUAL_TOP_250"))
            continue
        if comentario in curtos:
            com_conteudo = comentario in CURTOS_COM_CONTEUDO
            resultados.append({
                "comentario_sha256": sha, "comentario": comentario,
                "estado": "DECISAO_SEM_MODELO",
                "classe": "COM_CONTEUDO_SEM_BARREIRA" if com_conteudo else "SEM_CONTEUDO_REAL",
                "tem_barreira": False, "barreira_bruta": None,
                "origem_decisao": "REVISAO_MANUAL_CORTE_20",
                "tokens_entrada": 0, "tokens_saida": 0,
            })
            continue
        if comentario in gabarito:
            item = gabarito[comentario]
            tem = item["tem_barreira_adocao"]
            classe = "COM_BARREIRA" if tem else (
                "SEM_CONTEUDO_REAL" if normalizar(comentario) in SEM_CONTEUDO_EXATOS
                else "COM_CONTEUDO_SEM_BARREIRA")
            resultados.append({
                "comentario_sha256": sha, "comentario": comentario,
                "estado": "EXTRAIDO", "classe": classe, "tem_barreira": tem,
                "barreira_bruta": item.get("barreira_bruta"),
                "origem_decisao": "GABARITO_PILOTO_INDIVIDUAL",
                "tokens_entrada": 0, "tokens_saida": 0,
            })
            continue
        item = por_texto_modelo[comentario]
        if item["estado"] != "EXTRAIDO":
            resultados.append({
                "comentario_sha256": sha, "comentario": comentario,
                "estado": item["estado"], "classe": "NAO_CLASSIFICADO_ERRO",
                "tem_barreira": None, "barreira_bruta": None,
                "origem_decisao": "SONNET_INDIVIDUAL", "tokens_entrada": item["tokens_entrada"],
                "tokens_saida": item["tokens_saida"], "erro": item.get("erro") or item.get("erro_formato"),
            })
        else:
            tem = item["tem_barreira"]
            classe = "COM_BARREIRA" if tem else (
                "SEM_CONTEUDO_REAL" if normalizar(comentario) in SEM_CONTEUDO_EXATOS
                else "COM_CONTEUDO_SEM_BARREIRA")
            resultados.append({
                "comentario_sha256": sha, "comentario": comentario,
                "estado": "EXTRAIDO", "classe": classe, "tem_barreira": tem,
                "barreira_bruta": item.get("barreira_bruta"),
                "origem_decisao": "SONNET_INDIVIDUAL", "tokens_entrada": item["tokens_entrada"],
                "tokens_saida": item["tokens_saida"],
            })

    gravar_jsonl(DESTINO / "resultados_completos.jsonl", resultados)
    frequencias = Counter(v["COMENTARIOS"] for v in visitas)
    resumo = {
        "visitas": len(visitas), "comentarios_distintos": len(textos),
        "decisoes_manuais_top_250": len(manuais), "textos_curtos": len(curtos),
        "gabarito_piloto_reaproveitado": sum(x in gabarito for x in elegiveis),
        "chamadas_novas_esperadas": len(pendentes_modelo),
        "estados_textos": dict(Counter(x["classe"] for x in resultados)),
        "estados_visitas": dict(Counter({classe: sum(frequencias[x["comentario"]]
                                                       for x in resultados if x["classe"] == classe)
                                          for classe in {x["classe"] for x in resultados}})),
        "tokens_entrada_escala": sum(x["tokens_entrada"] for x in extraidos),
        "tokens_saida_escala": sum(x["tokens_saida"] for x in extraidos),
    }
    (DESTINO / "resumo_escala.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
