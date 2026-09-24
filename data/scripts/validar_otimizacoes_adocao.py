"""Valida otimizações da passada S contra o piloto individual de 150 textos.

Não contém caminho de escala. As saídas ficam separadas da passada N e podem
ser retomadas sem repetir chamadas já registradas.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from barreiras_comum import chave, gravar_jsonl, ler_jsonl
from descobrir_barreiras_adocao_piloto import (
    PROMPT,
    PROMPT_AJUSTE_1,
    PROMPT_INICIAL,
    configuracao,
)
from backend.app.agente.modelo import ServingDatabricks


DESTINO = Path("docs/analises/barreiras_adocao_piloto")
ENDPOINT_SONNET = "databricks-claude-sonnet-5"
ENDPOINT_LLAMA = "databricks-llama-4-maverick"
ARQUIVO_LOTE = DESTINO / "extracoes_validacao_lote_sonnet_max4000.jsonl"
ARQUIVO_LLAMA = DESTINO / "extracoes_validacao_llama.jsonl"

PROMPT_LOTE = PROMPT + """

Você receberá comentários numerados. Classifique cada comentário de modo
independente, usando exatamente as regras acima. Responda EXCLUSIVAMENTE com
um array JSON válido, na mesma ordem e com um objeto por item:
[{"id":1,"tem_barreira_adocao":true ou false,"barreira_bruta":"obstáculo curto" ou null}]
Não pule, funda ou renumere itens."""

PROMPT_LLAMA = """Você analisa somente comentários de VISITAS REALIZADAS (VISITA_EFETIVA=S).
Decida se o texto relata obstáculo concreto para o médico adotar ou prescrever uma marca/produto apresentado.
São barreiras: médico não lembra a marca nas oportunidades; preferência por concorrente quando o motivo é declarado; custo alto declarado como obstáculo; dúvida ou receio de eficácia/segurança; falta de experiência clínica que impede a adoção.
Responda false para simples ação do propagandista (reforço, apresentação, foco em preço, amostra), característica de paciente, oportunidade positiva, elogio de custo-benefício, ausência neutra de feedback ou simples falta de informação sobre prescrição.
Não deduza barreira quando o texto apenas diz que o médico não prescreve algo ou cita concorrente sem explicar a causa. Também responda false para: foco do propagandista em preço sem objeção do médico; troca por genérico feita pela farmácia depois da prescrição; uso de outra molécula em intensidade de dor diferente.
Erros de digitação não invalidam uma barreira clara.
Responda EXCLUSIVAMENTE JSON válido, sem markdown e sem blocos de código: {"tem_barreira_adocao":true ou false}."""


def _snapshot() -> list[dict]:
    dados = json.loads((DESTINO / "fonte_snapshot.json").read_text(encoding="utf-8"))
    nomes = [c["name"] for c in dados["schema"]]
    return [dict(zip(nomes, linha)) for linha in dados["rows"]]


def _piloto(visitas: list[dict]) -> list[str]:
    textos = list(dict.fromkeys(v["COMENTARIOS"] for v in visitas))
    return sorted(textos, key=lambda c: hashlib.sha256(c.encode()).hexdigest())[:150]


def _linhas(nome: str) -> list[dict]:
    return ler_jsonl(DESTINO / nome)


def construir_gabarito(piloto: list[str]) -> list[dict]:
    """Reconstrói a última decisão individual validada para cada texto."""
    todas = [r for nome in ("extracoes_piloto.jsonl", "extracoes_ajuste.jsonl",
                            "extracoes_ajuste_final.jsonl") for r in _linhas(nome)]
    por_chave = {r["chave"]: r for r in todas}
    alvos = [c for c in piloto if any(x in c.upper() for x in
             ("PRECO PRA ELE É IMPORTANTE", "FOCO EM PREÇO", "CLAVULIN",
              "TROCAM A MARCA", "SUBSTITUIÇÃO POR", "PREFERE OUTRAS MOLECULAS"))]
    ajuste = set(list(dict.fromkeys(alvos + piloto[:20]))[:20])
    finais = {c for c in piloto if "CLAVULIN" in c.upper()
              or "PREFERE OUTRAS MOLECULAS" in c.upper()}
    saida = []
    for comentario in piloto:
        prompt = PROMPT if comentario in finais else PROMPT_AJUSTE_1 if comentario in ajuste else PROMPT_INICIAL
        resposta = por_chave.get(chave(prompt, comentario))
        if not resposta or resposta.get("estado") != "EXTRAIDO":
            raise RuntimeError("gabarito individual incompleto")
        saida.append({
            "comentario_sha256": hashlib.sha256(comentario.encode()).hexdigest(),
            "comentario": comentario,
            "tem_barreira_adocao": resposta["tem_barreira"],
            "barreira_bruta": resposta.get("barreira_bruta"),
            "versao_validada": "final" if comentario in finais else "ajuste_1" if comentario in ajuste else "inicial",
        })
    gravar_jsonl(DESTINO / "gabarito_piloto.jsonl", saida)
    return saida


def _texto_resposta(content) -> str:
    if isinstance(content, list):
        partes = [p.get("text") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        if len(partes) != 1:
            raise ValueError("resposta sem bloco de texto único")
        content = partes[0]
    if not isinstance(content, str):
        raise ValueError("conteúdo da resposta não é texto")
    bloco = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", content, re.S | re.I)
    return bloco.group(1) if bloco else content


def _chamar_com_retry(modelo, mensagens, max_tokens):
    for tentativa in range(3):
        try:
            return modelo.extrair_estruturado(mensagens, max_tokens=max_tokens)
        except Exception:
            if tentativa == 2:
                raise
            time.sleep(2 ** tentativa)
    raise AssertionError("inalcançável")


def validar_lote(modelo: ServingDatabricks, gabarito: list[dict]) -> list[dict]:
    existentes = {r["lote_sha256"]: r for r in ler_jsonl(ARQUIVO_LOTE)}
    chamadas = []
    for inicio in range(0, len(gabarito), 20):
        itens = gabarito[inicio:inicio + 20]
        texto = "\n\n".join(f"[{i}] {x['comentario']}" for i, x in enumerate(itens, 1))
        lote_sha = hashlib.sha256(texto.encode()).hexdigest()
        if lote_sha not in existentes:
            try:
                volta = _chamar_com_retry(
                    modelo,
                    [{"role": "system", "content": PROMPT_LOTE},
                     {"role": "user", "content": texto}],
                    4000,
                )
                registro = {
                    "lote_sha256": lote_sha, "inicio": inicio, "quantidade": len(itens),
                    "resposta_bruta": volta.mensagem.get("content"),
                    "tokens_entrada": volta.tokens_entrada, "tokens_saida": volta.tokens_saida,
                    "modelo": volta.modelo,
                }
                try:
                    parsed = json.loads(_texto_resposta(registro["resposta_bruta"]))
                    if not isinstance(parsed, list) or len(parsed) != len(itens):
                        raise ValueError("array com quantidade incorreta")
                    por_id = {x.get("id"): x for x in parsed if isinstance(x, dict)}
                    if set(por_id) != set(range(1, len(itens) + 1)):
                        raise ValueError("ids ausentes, repetidos ou fora do lote")
                    for i, item in por_id.items():
                        if type(item.get("tem_barreira_adocao")) is not bool:
                            raise ValueError(f"booleano inválido no id {i}")
                        barreira = item.get("barreira_bruta")
                        if (item["tem_barreira_adocao"] and not isinstance(barreira, str)) or (
                                not item["tem_barreira_adocao"] and barreira is not None):
                            raise ValueError(f"barreira_bruta incompatível no id {i}")
                    registro["classificacoes"] = [por_id[i] for i in range(1, len(itens) + 1)]
                    registro["estado"] = "EXTRAIDO"
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    registro["estado"] = "NAO_CLASSIFICADO_ERRO_FORMATO"
                    registro["erro_formato"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                registro = {"lote_sha256": lote_sha, "inicio": inicio,
                            "quantidade": len(itens), "estado": "NAO_CLASSIFICADO_ERRO_CHAMADA",
                            "erro": str(exc), "tokens_entrada": 0, "tokens_saida": 0}
            with ARQUIVO_LOTE.open("a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
            existentes[lote_sha] = registro
        chamadas.append(existentes[lote_sha])

    comparacoes = []
    for chamada in chamadas:
        inicio = chamada["inicio"]
        for deslocamento in range(chamada["quantidade"]):
            ouro = gabarito[inicio + deslocamento]
            classificacao = (chamada.get("classificacoes") or [None] * chamada["quantidade"])[deslocamento]
            lote_valor = classificacao.get("tem_barreira_adocao") if classificacao else None
            comparacoes.append({
                "comentario_sha256": ouro["comentario_sha256"], "posicao_lote": deslocamento + 1,
                "gabarito": ouro["tem_barreira_adocao"], "lote": lote_valor,
                "diverge": lote_valor != ouro["tem_barreira_adocao"],
                "estado_lote": chamada["estado"],
            })
    return comparacoes


def _chamada_llama(modelo, item: dict) -> dict:
    comentario = item["comentario"]
    call_key = chave(PROMPT_LLAMA + "\0" + ENDPOINT_LLAMA, comentario)
    try:
        volta = _chamar_com_retry(
            modelo,
            [{"role": "system", "content": PROMPT_LLAMA},
             {"role": "user", "content": comentario}],
            48,
        )
        registro = {
            "chave": call_key, "comentario_sha256": item["comentario_sha256"],
            "comentario": comentario, "resposta_bruta": volta.mensagem.get("content"),
            "tokens_entrada": volta.tokens_entrada, "tokens_saida": volta.tokens_saida,
            "modelo": volta.modelo,
        }
        try:
            parsed = json.loads(_texto_resposta(registro["resposta_bruta"]))
            if not isinstance(parsed, dict) or type(parsed.get("tem_barreira_adocao")) is not bool:
                raise ValueError("campo tem_barreira_adocao ausente ou inválido")
            registro["tem_barreira_adocao"] = parsed["tem_barreira_adocao"]
            registro["estado"] = "EXTRAIDO"
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            registro["estado"] = "NAO_CLASSIFICADO_ERRO_FORMATO"
            registro["erro_formato"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        registro = {"chave": call_key, "comentario_sha256": item["comentario_sha256"],
                    "comentario": comentario, "estado": "NAO_CLASSIFICADO_ERRO_CHAMADA",
                    "erro": str(exc), "tokens_entrada": 0, "tokens_saida": 0}
    return registro


def validar_llama(settings, gabarito: list[dict]) -> list[dict]:
    modelo = ServingDatabricks(settings, endpoint=ENDPOINT_LLAMA)
    existentes = {r["chave"]: r for r in ler_jsonl(ARQUIVO_LLAMA)}
    pendentes = [item for item in gabarito
                 if chave(PROMPT_LLAMA + "\0" + ENDPOINT_LLAMA, item["comentario"]) not in existentes]
    if pendentes:
        modelo._obter_token()
        with ThreadPoolExecutor(max_workers=6) as pool, ARQUIVO_LLAMA.open("a", encoding="utf-8") as arquivo:
            futuros = {pool.submit(_chamada_llama, modelo, item): item for item in pendentes}
            for indice, futuro in enumerate(as_completed(futuros), 1):
                registro = futuro.result()
                arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
                arquivo.flush()
                existentes[registro["chave"]] = registro
                if indice % 25 == 0:
                    print(f"llama: {indice}/{len(pendentes)} chamadas novas", flush=True)
    comparacoes = []
    for ouro in gabarito:
        registro = existentes[chave(PROMPT_LLAMA + "\0" + ENDPOINT_LLAMA, ouro["comentario"])]
        valor = registro.get("tem_barreira_adocao")
        dificil = any(x in ouro["comentario"].upper() for x in
                      ("FOCO EM PREÇO", "SUBSTITUIÇÃO POR", "CLAVULIN", "PREFERE OUTRAS MOLECULAS"))
        comparacoes.append({
            "comentario_sha256": ouro["comentario_sha256"], "gabarito": ouro["tem_barreira_adocao"],
            "llama": valor, "concorda": valor == ouro["tem_barreira_adocao"],
            "caso_dificil": dificil, "estado_llama": registro["estado"],
        })
    return comparacoes


def main() -> None:
    settings, sonnet = configuracao()
    if sonnet._endpoint != ENDPOINT_SONNET:
        raise RuntimeError("endpoint Sonnet inesperado")
    gabarito = construir_gabarito(_piloto(_snapshot()))
    lote = validar_lote(sonnet, gabarito)
    llama = validar_llama(settings, gabarito)
    lote_chamadas = {r["lote_sha256"]: r for r in ler_jsonl(ARQUIVO_LOTE)}
    llama_chamadas = {r["chave"]: r for r in ler_jsonl(ARQUIVO_LLAMA)}
    por_posicao = {}
    for posicao in range(1, 21):
        itens = [x for x in lote if x["posicao_lote"] == posicao]
        if itens:
            por_posicao[str(posicao)] = {"n": len(itens), "divergencias": sum(x["diverge"] for x in itens)}
    dificeis = [x for x in llama if x["caso_dificil"]]
    resumo = {
        "gabarito": {"n": len(gabarito), "barreiras": sum(x["tem_barreira_adocao"] for x in gabarito)},
        "sonnet_lote": {
            "chamadas": len(lote_chamadas), "resultados": len(lote),
            "divergencias": sum(x["diverge"] for x in lote), "por_posicao": por_posicao,
            "tokens_entrada": sum(x["tokens_entrada"] for x in lote_chamadas.values()),
            "tokens_saida": sum(x["tokens_saida"] for x in lote_chamadas.values()),
            "estados": {s: sum(x["estado"] == s for x in lote_chamadas.values())
                        for s in sorted({x["estado"] for x in lote_chamadas.values()})},
        },
        "llama_filtro": {
            "resultados": len(llama), "concordancias": sum(x["concorda"] for x in llama),
            "taxa_concordancia": sum(x["concorda"] for x in llama) / len(llama),
            "falsos_negativos": sum(x["gabarito"] and x["llama"] is False for x in llama),
            "falsos_positivos": sum(not x["gabarito"] and x["llama"] is True for x in llama),
            "casos_dificeis": len(dificeis), "concordancias_dificeis": sum(x["concorda"] for x in dificeis),
            "taxa_concordancia_dificeis": sum(x["concorda"] for x in dificeis) / len(dificeis),
            "tokens_entrada": sum(x["tokens_entrada"] for x in llama_chamadas.values()),
            "tokens_saida": sum(x["tokens_saida"] for x in llama_chamadas.values()),
            "estados": {s: sum(x["estado"] == s for x in llama_chamadas.values())
                        for s in sorted({x["estado"] for x in llama_chamadas.values()})},
        },
    }
    (DESTINO / "resumo_validacoes_otimizacoes.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gravar_jsonl(DESTINO / "comparacao_lote_sonnet.jsonl", lote)
    gravar_jsonl(DESTINO / "comparacao_llama.jsonl", llama)
    print(json.dumps(resumo, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
