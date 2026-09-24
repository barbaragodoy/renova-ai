"""Reprocessa somente resíduos de formato da escala S com teto maior."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from barreiras_comum import configuracao, interpretar_resposta, ler_jsonl, chave
from descobrir_barreiras_adocao_piloto import PROMPT


DESTINO = Path("docs/analises/barreiras_adocao_piloto")
PRINCIPAL = DESTINO / "extracoes_escala_individual.jsonl"
AUDITORIA = DESTINO / "extracoes_escala_retry_formato.jsonl"


def chamar(modelo, comentario: str) -> dict:
    volta = modelo.extrair_estruturado(
        [{"role": "system", "content": PROMPT},
         {"role": "user", "content": comentario}],
        max_tokens=1600,
    )
    return interpretar_resposta({
        "chave": chave(PROMPT, comentario), "comentario": comentario,
        "resposta_bruta": volta.mensagem.get("content"),
        "tokens_entrada": volta.tokens_entrada, "tokens_saida": volta.tokens_saida,
        "modelo": volta.modelo,
    }, "tem_barreira_adocao")


def main() -> None:
    latest = {x["chave"]: x for x in ler_jsonl(PRINCIPAL)}
    pendentes = [x["comentario"] for x in latest.values() if x["estado"] != "EXTRAIDO"]
    if len(pendentes) > 50:
        raise RuntimeError("resíduo de formato inesperadamente grande")
    _, modelo = configuracao()
    modelo._obter_token()
    resultados = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futuros = [pool.submit(chamar, modelo, comentario) for comentario in pendentes]
        for futuro in as_completed(futuros):
            resultados.append(futuro.result())
    with AUDITORIA.open("a", encoding="utf-8") as audit, PRINCIPAL.open("a", encoding="utf-8") as principal:
        for item in resultados:
            linha = json.dumps(item, ensure_ascii=False) + "\n"
            audit.write(linha)
            principal.write(linha)
    print(json.dumps({
        "reprocessados": len(resultados),
        "extraidos": sum(x["estado"] == "EXTRAIDO" for x in resultados),
        "tokens_entrada": sum(x["tokens_entrada"] for x in resultados),
        "tokens_saida": sum(x["tokens_saida"] for x in resultados),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
