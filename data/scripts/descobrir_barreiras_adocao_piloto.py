"""Passada S, somente piloto: python data/scripts/descobrir_barreiras_adocao_piloto.py.

Este script tem limite rígido de 150 textos distintos. Não há caminho de
execução que processe o restante do recorte ou a base completa.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from barreiras_comum import configuracao, consultar, extrair_distintos, gravar_jsonl, salvar_snapshot_sql_api

DESTINO = Path("docs/analises/barreiras_adocao_piloto")
SQL = """SELECT ID, UFCRM, SETOR, CICLO, DATA_VISITA, VISITA_TIPO, COMENTARIOS
FROM dmn_produtividade_dev.pfv_tb.propagandistas_visitacao_medica
WHERE VISITA_EFETIVA='S' AND CICLO IN ('202607','202608')
  AND pmod(xxhash64(ID),100000)<800 ORDER BY ID"""
PROMPT_PRETESTE = """Você analisa somente comentários de VISITAS REALIZADAS (VISITA_EFETIVA=S).
Descubra se o texto relata obstáculo concreto para o médico adotar ou prescrever uma marca/produto apresentado.
Exemplos: médico não lembra a marca nas oportunidades, prefere concorrente, considera custo alto, tem dúvida ou receio de eficácia/segurança, ainda não tem experiência clínica e isso impede a adoção.
Não transforme simples ação do propagandista (reforço, apresentação, amostra), característica de paciente, oportunidade positiva, elogio de custo-benefício ou ausência neutra de feedback em barreira.
Não deduza barreira só porque o texto não informa prescrição. Erros de digitação não invalidam uma barreira clara.
Se houver obstáculo, escreva a causa curta e fiel ao texto, sem nomes próprios. Não use categorias predefinidas.
Responda EXCLUSIVAMENTE JSON válido, sem markdown: {"tem_barreira_adocao":true ou false,"barreira_bruta":"obstáculo curto" ou null}.
Para false, barreira_bruta deve ser null."""
PROMPT_INICIAL = """Você analisa somente comentários de VISITAS REALIZADAS (VISITA_EFETIVA=S).
Descubra se o texto relata obstáculo concreto para o médico adotar ou prescrever uma marca/produto apresentado.
Exemplos: médico não lembra a marca nas oportunidades, prefere concorrente, considera custo alto, tem dúvida ou receio de eficácia/segurança, ainda não tem experiência clínica e isso impede a adoção.
Não transforme simples ação do propagandista (reforço, apresentação, amostra), característica de paciente, oportunidade positiva, elogio de custo-benefício ou ausência neutra de feedback em barreira.
Não deduza barreira só porque o texto não informa prescrição ou diz apenas que o médico não prescreve algo. Exemplo: “não prescreve CBD; perguntou preço de outro produto; preço é importante” não prova objeção de preço nem causa da não prescrição. Erros de digitação não invalidam uma barreira clara.
Se houver obstáculo, escreva a causa curta e fiel ao texto, sem nomes próprios. Não use categorias predefinidas.
Responda EXCLUSIVAMENTE JSON válido, sem markdown e sem blocos de código: {"tem_barreira_adocao":true ou false,"barreira_bruta":"obstáculo curto" ou null}.
Para false, barreira_bruta deve ser null."""
PROMPT_AJUSTE_1 = """Você analisa somente comentários de VISITAS REALIZADAS (VISITA_EFETIVA=S).
Descubra se o texto relata obstáculo concreto para o médico adotar ou prescrever uma marca/produto apresentado.
Exemplos: médico não lembra a marca nas oportunidades, prefere concorrente, considera custo alto, tem dúvida ou receio de eficácia/segurança, ainda não tem experiência clínica e isso impede a adoção.
Não transforme simples ação do propagandista (reforço, apresentação, foco em preço, amostra), característica de paciente, oportunidade positiva, elogio de custo-benefício ou ausência neutra de feedback em barreira.
Não deduza barreira só porque o texto não informa prescrição, diz que o médico não prescreve algo ou menciona marca concorrente sem explicar a causa. Exemplo: “não prescreve CBD; perguntou preço de outro produto; preço é importante” não prova objeção de preço. Escolher outra molécula para uma indicação diferente também não prova obstáculo. Se a farmácia troca por genérico depois de o médico prescrever a marca, isso não é barreira de adoção PELO MÉDICO. Erros de digitação não invalidam uma barreira clara.
Se houver obstáculo, escreva a causa curta e fiel ao texto, sem nomes próprios. Não use categorias predefinidas.
Responda EXCLUSIVAMENTE JSON válido, sem markdown e sem blocos de código: {"tem_barreira_adocao":true ou false,"barreira_bruta":"obstáculo curto" ou null}.
Para false, barreira_bruta deve ser null."""
PROMPT = """Você analisa somente comentários de VISITAS REALIZADAS (VISITA_EFETIVA=S).
Descubra se o texto relata obstáculo concreto para o médico adotar ou prescrever uma marca/produto apresentado.
Exemplos: médico não lembra a marca nas oportunidades, declara preferência por concorrente com motivo, considera custo alto, tem dúvida ou receio de eficácia/segurança, ainda não tem experiência clínica e isso impede a adoção.
Não transforme simples ação do propagandista (reforço, apresentação, foco em preço, amostra), característica de paciente, oportunidade positiva, elogio de custo-benefício ou ausência neutra de feedback em barreira.
Não deduza barreira só porque o texto não informa prescrição, diz que o médico não prescreve algo ou menciona marca concorrente sem explicar a causa. Exemplos para responder false: “não prescreve CBD; perguntou preço de outro produto; preço é importante”; “não explicou por que prescreve concorrente, mas confia na nossa marca”; “usa nosso produto em casos leves e outra molécula em casos graves”. Se a farmácia troca por genérico depois de o médico prescrever a marca, isso não é barreira de adoção PELO MÉDICO. Erros de digitação não invalidam uma barreira clara.
Se houver obstáculo, escreva a causa curta e fiel ao texto, sem nomes próprios. Não use categorias predefinidas.
Responda EXCLUSIVAMENTE JSON válido, sem markdown e sem blocos de código: {"tem_barreira_adocao":true ou false,"barreira_bruta":"obstáculo curto" ou null}.
Para false, barreira_bruta deve ser null."""
PROMPT_AJUSTE_2 = PROMPT.replace(
    "declara preferência por concorrente com motivo", "prefere concorrente"
)


def carregar_snapshot(path: Path) -> list[dict]:
    dados = json.loads(path.read_text(encoding="utf-8"))
    nomes = [col["name"] for col in dados["schema"]]
    return [dict(zip(nomes, linha)) for linha in dados["rows"]]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-sql-api", type=Path,
                        help="resultado integral do SELECT acima, exportado pela SQL Statement API")
    parser.add_argument("--limite", type=int, default=150,
                        help="até 150 textos do piloto, para checagem inicial")
    parser.add_argument("--revisao", action="store_true",
                        help="reavalia até 20 textos já incluídos no piloto, sem ampliar o universo")
    parser.add_argument("--revisao-final", action="store_true",
                        help="reavalia dois falsos positivos persistentes dentro do mesmo piloto")
    args = parser.parse_args()
    if not 1 <= args.limite <= 150:
        raise ValueError("piloto limitado a no máximo 150 comentários")
    settings, modelo = configuracao()
    visitas = carregar_snapshot(args.snapshot_sql_api) if args.snapshot_sql_api else consultar(settings, SQL)
    if not args.snapshot_sql_api:
        salvar_snapshot_sql_api(DESTINO / "fonte_snapshot.json", visitas)
    if len(visitas) != len({str(v["ID"]) for v in visitas}):
        raise RuntimeError("IDs duplicados no recorte S")
    textos = list(dict.fromkeys(v["COMENTARIOS"] for v in visitas))
    if len(visitas) > 20000 or len(textos) > 20000:
        raise RuntimeError("recorte S inesperadamente grande; interrompido")
    manifesto = [{"id": str(v["ID"]), "ufcrm": v["UFCRM"], "setor": v["SETOR"],
                  "ciclo": v["CICLO"], "data_visita": str(v["DATA_VISITA"]),
                  "comentario_sha256": hashlib.sha256((v["COMENTARIOS"] or "").encode()).hexdigest()}
                 for v in visitas]
    gravar_jsonl(DESTINO / "manifesto_ids.jsonl", manifesto)
    universo_piloto = sorted(textos, key=lambda c: hashlib.sha256(c.encode()).hexdigest())[:150]
    if args.revisao_final:
        piloto = [c for c in universo_piloto if "CLAVULIN" in c.upper()
                  or "PREFERE OUTRAS MOLECULAS" in c.upper()]
        if len(piloto) != 2:
            raise RuntimeError("dois casos de revisão final esperados")
        arquivo_extracoes = DESTINO / "extracoes_ajuste_final.jsonl"
        arquivo_resumo = DESTINO / "resumo_ajuste_final.json"
    elif args.revisao:
        alvos = [c for c in universo_piloto if any(x in c.upper() for x in
                 ("PRECO PRA ELE É IMPORTANTE", "FOCO EM PREÇO", "CLAVULIN",
                  "TROCAM A MARCA", "SUBSTITUIÇÃO POR", "PREFERE OUTRAS MOLECULAS"))]
        piloto = list(dict.fromkeys(alvos + universo_piloto[:20]))[:20]
        arquivo_extracoes = DESTINO / "extracoes_ajuste.jsonl"
        arquivo_resumo = DESTINO / "resumo_ajuste.json"
    else:
        piloto = universo_piloto[:args.limite]
        arquivo_extracoes = DESTINO / "extracoes_piloto.jsonl"
        arquivo_resumo = DESTINO / "resumo_piloto.json"
        gravar_jsonl(DESTINO / "manifesto_piloto.jsonl",
                     [{"comentario_sha256": hashlib.sha256(c.encode()).hexdigest()} for c in piloto])
    prompt_usado = PROMPT if args.revisao_final else PROMPT_AJUSTE_1 if args.revisao else PROMPT_INICIAL
    resultados = extrair_distintos(modelo, piloto, prompt_usado, "tem_barreira_adocao", arquivo_extracoes)
    freq = Counter(v["COMENTARIOS"] for v in visitas)
    resumo = {"visitas_recorte": len(visitas), "comentarios_distintos_recorte": len(textos),
              "visitas_com_texto_repetido": sum(n for n in freq.values() if n > 1),
              "chamadas_piloto": len(resultados),
              "tokens_entrada": sum(r["tokens_entrada"] for r in resultados),
              "tokens_saida": sum(r["tokens_saida"] for r in resultados),
              "estados": dict(Counter(r["estado"] for r in resultados))}
    arquivo_resumo.write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(resumo, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
