"""Passada N, independente: python data/scripts/descobrir_barreiras_acesso.py.

Consulta apenas a fonte, salva manifesto e extrai cada comentário distinto uma
vez. Reexecuções retomam as chamadas já gravadas em extracoes.jsonl.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from barreiras_comum import configuracao, consultar, extrair_distintos, gravar_jsonl, salvar_snapshot_sql_api

DESTINO = Path("docs/analises/barreiras_acesso")
SQL = """SELECT ID, UFCRM, CICLO, DATA_VISITA, VISITA_TIPO, COMENTARIOS
FROM dmn_produtividade_dev.pfv_tb.propagandistas_visitacao_medica
WHERE VISITA_EFETIVA='N'
  AND DATA_VISITA >= DATE '2026-01-01' AND DATA_VISITA < DATE '2027-01-01'
  AND upper(trim(COMENTARIOS)) <> 'PROFISSIONAIS NÃO VISITADOS ATÉ O FECHAMENTO'
ORDER BY ID"""
PROMPT = """Você analisa somente comentários de VISITAS NÃO REALIZADAS (VISITA_EFETIVA=N).
Descubra se o texto informa uma causa concreta que impediu acesso ou contato com o médico naquela visita.
Exemplos de causa: férias/licença/ausência do médico, agenda indisponível, atendimento já encerrado quando o representante chegou, recusa de visita, restrição de entrada, mudança ou fechamento de local.
Baixo potencial, falta de oportunidade prescritiva ou opinião sobre produto NÃO são causa de acesso por si só.
Não invente motivo a partir da flag N. Se houver apenas contexto sem causa de não realização, responda false.
Se houver causa, escreva-a de modo curto, sem nomes próprios nem inferências.
Responda EXCLUSIVAMENTE JSON válido, sem markdown: {"tem_barreira_acesso":true ou false,"barreira_bruta":"causa curta" ou null}.
Para false, barreira_bruta deve ser null."""


def carregar_snapshot(path: Path) -> list[dict]:
    dados = json.loads(path.read_text(encoding="utf-8"))
    nomes = [col["name"] for col in dados["schema"]]
    return [dict(zip(nomes, linha)) for linha in dados["rows"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-sql-api", type=Path,
                        help="resultado integral do SELECT acima, exportado pela SQL Statement API")
    parser.add_argument("--limite", type=int, help="limita chamadas distintas para inspeção")
    args = parser.parse_args()
    settings, modelo = configuracao()
    visitas = carregar_snapshot(args.snapshot_sql_api) if args.snapshot_sql_api else consultar(settings, SQL)
    if not args.snapshot_sql_api:
        salvar_snapshot_sql_api(DESTINO / "fonte_snapshot.json", visitas)
    if len(visitas) != len({str(v["ID"]) for v in visitas}):
        raise RuntimeError("IDs duplicados no manifesto de acesso")
    manifesto = [{"id": str(v["ID"]), "ufcrm": v["UFCRM"], "ciclo": v["CICLO"],
                  "data_visita": str(v["DATA_VISITA"]), "visita_tipo": v["VISITA_TIPO"],
                  "comentario_sha256": hashlib.sha256((v["COMENTARIOS"] or "").encode()).hexdigest()}
                 for v in visitas]
    gravar_jsonl(DESTINO / "manifesto_ids.jsonl", manifesto)
    textos = list(dict.fromkeys(v["COMENTARIOS"] for v in visitas
                               if v["COMENTARIOS"] and v["COMENTARIOS"].strip() not in ("", "-")))
    if args.limite is not None:
        textos = textos[:args.limite]
    resultados = extrair_distintos(modelo, textos, PROMPT, "tem_barreira_acesso",
                                   DESTINO / "extracoes.jsonl")
    por_texto = {r["comentario"]: r for r in resultados}
    por_texto_visitas = defaultdict(list)
    for visita in visitas:
        por_texto_visitas[visita["COMENTARIOS"]].append(visita)
    resumo = {"visitas_total": len(visitas), "comentarios_distintos": len(por_texto_visitas),
              "visitas_sem_conteudo_traco": sum(v["COMENTARIOS"].strip() == "-" for v in visitas),
              "chamadas_processadas": len(resultados),
              "tokens_entrada": sum(r["tokens_entrada"] for r in resultados),
              "tokens_saida": sum(r["tokens_saida"] for r in resultados)}
    estados = defaultdict(lambda: {"visitas": 0, "medicos": set(), "textos": 0})
    for texto, grupo in por_texto_visitas.items():
        if texto is None or texto.strip() in ("", "-"):
            estado = "SEM_CONTEUDO_REAL"
        elif texto in por_texto:
            r = por_texto[texto]
            estado = ("COM_BARREIRA" if r.get("estado") == "EXTRAIDO" and r.get("tem_barreira")
                      else "COM_CONTEUDO_SEM_BARREIRA" if r.get("estado") == "EXTRAIDO"
                      else r["estado"])
        else:
            continue
        estados[estado]["visitas"] += len(grupo)
        estados[estado]["medicos"].update(v["UFCRM"] for v in grupo)
        estados[estado]["textos"] += 1
    resumo["estados"] = {k: {"visitas": v["visitas"], "medicos": len(v["medicos"]),
                             "textos": v["textos"]} for k, v in estados.items()}
    (DESTINO / "resumo_automatico_antes_revisao.json").write_text(
        json.dumps(resumo, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(resumo, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
