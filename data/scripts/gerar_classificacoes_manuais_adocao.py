"""Gera o rastro da revisão humana dos 250 textos mais frequentes da passada S.

As decisões abaixo foram tomadas por leitura individual em 20/09/2026. Os
índices são validados contra o ranking determinístico antes da gravação.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


DESTINO = Path("docs/analises/barreiras_adocao_piloto")

# Anotações operacionais, listas de produtos e ações do propagandista sem
# relato factual atribuível ao médico.
SEM_CONTEUDO_RANKS = {
    1, 2, 4, 6, 7, 10, 11, 12, 13, 14, 16, 17, 18, 21, 23, 25, 27, 28, 30,
    33, 34, 36, 37, 39, 41, 42, 44, 45, 48, 49, 50, 51, 53, 56, 57, 61, 62,
    63, 65, 67, 69, 70, 75, 77, 78, 79, 80, 84, 86, 88, 90, 92, 93, 95, 97,
    100, 101, 105, 106, 107, 109, 111, 114, 118, 119, 120, 126, 128, 130,
    134, 135, 136, 137, 141, 146, 147, 148, 150, 151, 153, 156, 157, 159,
    160, 162, 163, 164, 165, 169, 174, 175, 176, 181, 184, 186, 187, 188,
    190, 191, 193, 195, 196, 197, 198, 201, 202, 204, 205, 206, 210, 212,
    214, 216, 217, 218, 219, 220, 222, 223, 225, 227, 228, 233, 236, 237,
    240, 241, 242, 243, 244, 245, 248, 249,
}

# Barreiras lidas no texto, sem aplicar taxonomia prévia.
BARREIRAS_POR_RANK = {
    60: "marcas concorrentes permanecem mais lembradas e custo direciona prescrições para alternativas",
    66: "pacientes não têm condição de pagar medicamentos de custo elevado",
    85: "dificuldade de lembrar a marca e hábito de não realizar o tratamento",
    91: "preocupação com falta do produto impede retomar a prescrição",
    104: "dúvida sobre o receituário e dificuldade dos pacientes para localizar o produto",
    145: "dificuldade de lembrar a marca e hábito de não realizar o tratamento",
    158: "médica não se habituou à família de produtos",
    224: "médicos seguem protocolo antigo de suplementação",
}


def main() -> None:
    dados = json.loads((DESTINO / "fonte_snapshot.json").read_text(encoding="utf-8"))
    nomes = [c["name"] for c in dados["schema"]]
    visitas = [dict(zip(nomes, linha)) for linha in dados["rows"]]
    frequencias = Counter(v["COMENTARIOS"] for v in visitas)
    ranking = sorted(
        frequencias.items(),
        key=lambda x: (-x[1], hashlib.sha256(x[0].encode()).hexdigest()),
    )[:250]
    if len(ranking) != 250 or min(n for _, n in ranking) < 2:
        raise RuntimeError("ranking dos 250 textos mais frequentes mudou")
    if SEM_CONTEUDO_RANKS & BARREIRAS_POR_RANK.keys():
        raise RuntimeError("rank recebeu duas decisões manuais")

    saida = []
    for rank, (comentario, visitas_texto) in enumerate(ranking, 1):
        if rank in BARREIRAS_POR_RANK:
            decisao = "COM_BARREIRA"
            barreira = BARREIRAS_POR_RANK[rank]
            justificativa = f"O comentário declara obstáculo concreto: {barreira}."
        elif rank in SEM_CONTEUDO_RANKS:
            decisao = "SEM_CONTEUDO_REAL"
            barreira = None
            justificativa = (
                "Anotação operacional, lista de produtos ou ação do propagandista, "
                "sem relato factual do médico que permita avaliar adoção."
            )
        else:
            decisao = "COM_CONTEUDO_SEM_BARREIRA"
            barreira = None
            justificativa = (
                "Há relato factual ou feedback, mas não há causa concreta que impeça "
                "o médico de adotar ou prescrever."
            )
        saida.append({
            "rank_frequencia": rank,
            "comentario_sha256": hashlib.sha256(comentario.encode()).hexdigest(),
            "texto": comentario,
            "visitas": visitas_texto,
            "decisao": decisao,
            "tem_barreira_adocao": decisao == "COM_BARREIRA",
            "barreira_bruta": barreira,
            "justificativa": justificativa,
            "revisor": "revisao_humana",
            "data_revisao": "2026-09-20",
        })

    destino = DESTINO / "classificacoes_manuais.jsonl"
    with destino.open("w", encoding="utf-8") as arquivo:
        for item in saida:
            arquivo.write(json.dumps(item, ensure_ascii=False) + "\n")
    resumo = Counter(x["decisao"] for x in saida)
    print(json.dumps({"arquivo": str(destino), "textos": len(saida),
                      "visitas_representadas": sum(x["visitas"] for x in saida),
                      "decisoes": dict(resumo)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
