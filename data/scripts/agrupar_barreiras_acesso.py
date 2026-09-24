"""Consolida apenas extrações N em barreiras candidatas de acesso.

As regras abaixo foram definidas após ler as barreiras brutas do lote N.
Textos sem encaixe ficam explícitos em OUTROS_A_REVISAR.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from barreiras_comum import configuracao, consultar, ler_jsonl, gravar_jsonl
from descobrir_barreiras_acesso import SQL, PROMPT, carregar_snapshot

DESTINO = Path("docs/analises/barreiras_acesso")

# Revisão dos 189 textos marcados false após a extração. Só entram aqui casos
# em que o próprio comentário informa uma causa; locais isolados e baixo
# potencial continuam sem barreira de acesso.
REVISOES_MANUAIS = {
    "DR FEZ UMA CIRURGIA NO DENTE.": "Afastamento por saúde",
    "CONSULTIVO FECHADO SEM NENHUMA MENSAGEM INFORMATIVA DO MOTIVO": "Local de atendimento fechado",
    "DRA NAO ATENDEU NA SEMANA": "Ausência sem causa mais específica",
    "CONGRESSO": "Viagem ou congresso",
    "PREVISAO DE RETORNO NO FIM DE JULHO": "Ausência sem causa mais específica",
    "MÉDICA GANHOU O BEBÊ .": "Licença parental",
    "BAIXO POTENCIAL E MÉDICO NÃO LOCALIZADO": "Mudança de local ou localização desconhecida",
    "NAO LOCALIZADO": "Mudança de local ou localização desconhecida",
    "DR FICA EM CIDADE QUE A LINHA NAO VISITA. COM BAIXO POTENCIAL PARA LINHA .": "Fora da área de atendimento do setor",
    "DRA ATENDE NO HOSPITAL ESTADUAL. FORA DO BRICK.": "Fora da área de atendimento do setor",
    "MEDICO BAIXO POTENCIAL, NÃO ENCONTRADO": "Mudança de local ou localização desconhecida",
    "DRA ATENDE CDU. FORA DO BRICK.": "Fora da área de atendimento do setor",
    "DIFÍCIL ACESSO A SANTA CASA, POUCA OPORTUNIDADE": "Restrição institucional ou física de acesso",
    "MEDICO BAIXO POTENCIAL , ESTA DIMINUNDO OS ATENDIMENTOS DEVIDO PROBLEMAS DE SAUDE": "Afastamento por saúde",
    "PLANTONISTA NOTURNO DE FINAIS DE SEMANA.": "Agenda ou horário incompatível",
    "DR RECEBE SOMENTE PROPAGANDA DE PRODUTOS RELACIONADOS CO. ESPECIALIDADE": "Recusa ou limitação para receber representantes",
    "NÃO GOSTA DE RECEBER REPRESENTANTES": "Recusa ou limitação para receber representantes",
    "MORA NOS ESTADOS UNIDOS": "Mudança de local ou localização desconhecida",
    "PROFISSIONAL DE LICENÇA MÉDICA": "Afastamento por saúde",
    "MÉDICA DE LICENÇA MÉDICA, ESTÁ COM RECÉM NASCIDO": "Licença parental",
    "DRA MACHUCOU O TENDÃO DE AQUILES, SEM PREVISÃO DE VOLTA": "Afastamento por saúde",
}

SEM_CONTEUDO = {
    "-", "NADA A RELATAR", "RUNNER É O FOCO", "FOCO EM PRODUTOS PED",
    "FOCO EM PRODUTOS PEDIATRICOS", "DEIXADO APORTE AGS",
    "DEIXADO AGS", "DEIXADO AGS PARA LEMBRANCA", "DEIXADO AGS PARA LEMBRAR MARCAS",
    "DEIXADO MATERIAL DE TRABALHO", "REVISAO DO PORTFOLIO BIO",
    "EXCLUIR", "PUXAR RETORNO", "TRABALHAR RETORNO", "VOLTAR PARA PASSAR GRADE",
}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def categoria(barreira: str) -> str:
    b = normalizar(barreira)
    if re.search(r"^medic[oa] nao atendeu( na visita| na clinica)?$|^medic[oa] nao pode atender$", b):
        return "SEM_CAUSA_CONCRETA"
    if re.search(r"falec|luto|obito", b):
        return "Luto ou falecimento familiar"
    if "maternidade" in b or "paternidade" in b or "gestante" in b and "licenca" in b:
        return "Licença parental"
    if re.search(r"doent|internad|atestado|tratamento de saude|problema de saude|licenca medica|licenca saude|afastad.*(saude|cirurgia|medic|acidente|fratura|sintoma)|recupera.*cirurgia|operad", b):
        return "Afastamento por saúde"
    if re.search(r"licenca|afastad", b):
        return "Licença ou afastamento sem causa informada"
    if re.search(r"ferias|recesso", b):
        return "Férias ou recesso"
    if re.search(r"congresso|viag|viaj|fora da cidade|exterior|evento cientifico|em portugal", b):
        return "Viagem ou congresso"
    if re.search(r"brick|setor|territorio|nao elegivel|fora da area|fora da linha", b):
        return "Fora da área de atendimento do setor"
    if "agenda bloqueada" in b or "bloqueio da agenda" in b:
        return "Agenda ou horário incompatível"
    if re.search(r"dificil acesso|sem acessibilidade|sem acesso|acesso negad|restri|proibid|nao permite|nao autoriza|bloque|visitas suspensas|alvara|somente em uti|interno na instituicao", b):
        return "Restrição institucional ou física de acesso"
    if re.search(r"recus|nao recebe|nao acei|representantes nao|nao atende representante|nao atende propaganda|nao atende propagandista|nao gosta de atender representante|sem tempo para receber|atende apenas representantes|atende so.*representante|nao retornou atendimento a representante|nao retomou atendimento a representante", b):
        return "Recusa ou limitação para receber representantes"
    if re.search(r"aposent|nao retomou atendimentos|suspendeu os atendimentos", b):
        return "Atendimento profissional interrompido"
    if re.search(r"mudou|mudanca|nao atende mais|deixou de atender|saiu da clinica|saiu da unidade|novo endereco|localizad|endereco desconhec|endereco inexistente|sem endereco|nao encontrado|nao encontrada|sem local|nao atende no local|nao atende na cidade|nao trabalha mais|mora em outra cidade|nao atende na ubs|exonerou|atendendo em outro municipio|atendendo apenas em outro local|atendendo somente em|foi atender.*outro local|nao esta na cidade|sem posto fixo", b):
        return "Mudança de local ou localização desconhecida"
    if re.search(r"clinica.*fechad|consultorio.*fechad|hospital.*fechad|unidade.*fechad|local.*fechad|estabelecimento.*fechad|falta de energia", b):
        return "Local de atendimento fechado"
    if re.search(r"agenda|agend|atendimento.*(cancelad|encerrad|finalizad|suspens|desmarc)|cancelou|desmarcou|horario|sem paciente|nao atendendo|nao atende no dia|nao atende hoje|nao vai atender|alteracao do dia|alterou dia|atendendo.*outro local|plantao|plantonista|em cirurgia|cirurgias|compromisso|muitos pacientes|excesso de pacientes|atendimento ja|sem tempo", b):
        return "Agenda ou horário incompatível"
    if re.search(r"ausen|nao estava|nao se encontr|nao comparec|fora do local|nao presente|indisponivel|retorna|retorno|saiu mais cedo|nao atendeu hoje", b):
        return "Ausência sem causa mais específica"
    return "OUTROS_A_REVISAR"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-sql-api", type=Path)
    args = parser.parse_args()
    if args.snapshot_sql_api:
        visitas = carregar_snapshot(args.snapshot_sql_api)
    else:
        settings, _ = configuracao()
        visitas = consultar(settings, SQL)
    extracoes_lidas = ler_jsonl(DESTINO / "extracoes.jsonl")
    extracoes = {r["comentario"]: r for r in extracoes_lidas if r.get("chave")}
    grupos: dict[str, dict] = defaultdict(lambda: {"visitas": 0, "medicos": set(),
                                                   "comentarios": set(), "exemplos": []})
    revisao = []
    estados = defaultdict(lambda: {"visitas": 0, "medicos": set(), "comentarios": set()})
    for visita in visitas:
        texto = visita["COMENTARIOS"]
        extracao = extracoes.get(texto)
        if texto is None or normalizar(texto).strip(" .") in {normalizar(x) for x in SEM_CONTEUDO}:
            estado, nome = "SEM_CONTEUDO_REAL", None
        elif texto in REVISOES_MANUAIS:
            estado, nome = "COM_BARREIRA", REVISOES_MANUAIS[texto]
            revisao.append({"id": str(visita["ID"]), "comentario": texto,
                            "decisao": nome, "origem": "falso_negativo_revisado"})
        elif not extracao or extracao.get("estado") != "EXTRAIDO":
            estado, nome = (extracao or {}).get("estado", "NAO_CLASSIFICADO_ERRO_CHAMADA"), None
        elif not extracao.get("tem_barreira"):
            estado, nome = "COM_CONTEUDO_SEM_BARREIRA", None
        else:
            nome = categoria(extracao["barreira_bruta"])
            estado = "COM_CONTEUDO_SEM_BARREIRA" if nome == "SEM_CAUSA_CONCRETA" else "COM_BARREIRA"
        est = estados[estado]
        est["visitas"] += 1
        est["medicos"].add(visita["UFCRM"])
        est["comentarios"].add(texto)
        if estado != "COM_BARREIRA":
            if nome == "SEM_CAUSA_CONCRETA":
                revisao.append({"id": str(visita["ID"]), "barreira_bruta": extracao["barreira_bruta"],
                                "comentario": texto, "decisao": estado, "origem": "falso_positivo_revisado"})
            continue
        grupo = grupos[nome]
        grupo["visitas"] += 1
        grupo["medicos"].add(visita["UFCRM"])
        grupo["comentarios"].add(texto)
        if texto not in grupo["exemplos"]:
            grupo["exemplos"].append(texto)
        if nome == "OUTROS_A_REVISAR":
            revisao.append({"id": str(visita["ID"]), "barreira_bruta": extracao["barreira_bruta"],
                            "comentario": texto})
    saida = [{"barreira": nome, "visitas": g["visitas"], "medicos_distintos": len(g["medicos"]),
              "comentarios_distintos": len(g["comentarios"]), "exemplos": g["exemplos"][:5]}
             for nome, g in grupos.items()]
    saida.sort(key=lambda item: (-item["visitas"], item["barreira"]))
    (DESTINO / "barreiras_candidatas.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2) + "\n")
    gravar_jsonl(DESTINO / "revisao_residual.jsonl", revisao)
    por_chave = {r["chave"]: r for r in extracoes_lidas}
    resumo = {"visitas": len(visitas), "comentarios_distintos": len({v["COMENTARIOS"] for v in visitas}),
              "chamadas_reais_incluindo_teste_inicial": len(por_chave),
              "tokens_entrada_reais": sum(r["tokens_entrada"] for r in por_chave.values()),
              "tokens_saida_reais": sum(r["tokens_saida"] for r in por_chave.values()),
              "estados": {nome: {"visitas": g["visitas"], "medicos_distintos": len(g["medicos"]),
                                  "comentarios_distintos": len(g["comentarios"])}
                          for nome, g in estados.items()}}
    (DESTINO / "resumo_final.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + "\n")
    for item in saida:
        print(item["visitas"], item["medicos_distintos"], item["barreira"])
    print("revisao_residual", len(revisao))
    print("resumo_final", json.dumps(resumo, ensure_ascii=False))


if __name__ == "__main__":
    main()
