"""Infraestrutura genérica para extração offline; não contém dados de nenhuma passada."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from backend.app.agente.modelo import ServingDatabricks  # noqa: E402
from backend.app.config import Settings  # noqa: E402
from backend.app.db.databricks_connection import get_engine  # noqa: E402


def configuracao():
    settings = Settings(data_source="databricks", llm_timeout_seconds=90)
    modelo = ServingDatabricks(settings, endpoint="databricks-claude-sonnet-5")
    if modelo._endpoint != "databricks-claude-sonnet-5":
        raise RuntimeError("endpoint inesperado")
    return settings, modelo


def consultar(settings, sql: str) -> list[dict]:
    if not sql.lstrip().upper().startswith("SELECT "):
        raise ValueError("somente SELECT é permitido")
    with get_engine(settings).connect() as conn:
        return [dict(row) for row in conn.execute(text(sql)).mappings()]


def salvar_snapshot_sql_api(path: Path, linhas: list[dict]) -> None:
    """Guarda a mesma forma consumida por --snapshot-sql-api."""
    path.parent.mkdir(parents=True, exist_ok=True)
    colunas = list(linhas[0]) if linhas else []
    dados = {"schema": [{"name": nome} for nome in colunas],
             "rows": [[linha.get(nome) for nome in colunas] for linha in linhas]}
    path.write_text(json.dumps(dados, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def gravar_jsonl(path: Path, linhas: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as arquivo:
        for linha in linhas:
            arquivo.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")


def ler_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as arquivo:
        return [json.loads(linha) for linha in arquivo if linha.strip()]


def chave(prompt: str, comentario: str) -> str:
    return hashlib.sha256((prompt + "\0" + comentario).encode()).hexdigest()


def interpretar_resposta(resultado: dict, campo: str) -> dict:
    """Aceita JSON puro, bloco Markdown integral ou bloco text do endpoint.

    Outros desvios seguem explicitamente sem classificação por erro de formato.
    A resposta original nunca é substituída.
    """
    bruto = resultado.get("resposta_bruta")
    formato = "json"
    if isinstance(bruto, list):
        partes = [p.get("text") for p in bruto if isinstance(p, dict) and p.get("type") == "text"]
        if len(partes) != 1:
            resultado["estado"] = "NAO_CLASSIFICADO_ERRO_FORMATO"
            resultado["erro_formato"] = "resposta sem bloco text único"
            return resultado
        bruto = partes[0]
        formato = "bloco_text"
    if isinstance(bruto, str):
        match = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", bruto, re.S | re.I)
        if match:
            bruto = match.group(1)
            formato = "markdown_json" if formato == "json" else "bloco_text_markdown_json"
    try:
        parsed = json.loads(bruto)
        if (not isinstance(parsed, dict) or type(parsed.get(campo)) is not bool
                or (parsed[campo] and not isinstance(parsed.get("barreira_bruta"), str))
                or (not parsed[campo] and parsed.get("barreira_bruta") is not None)):
            raise ValueError("campos incompatíveis")
        resultado["estado"] = "EXTRAIDO"
        resultado["tem_barreira"] = parsed[campo]
        resultado["barreira_bruta"] = parsed["barreira_bruta"]
        resultado["formato_recebido"] = formato
        resultado.pop("erro_formato", None)
    except (ValueError, TypeError, KeyError) as exc:
        resultado["estado"] = "NAO_CLASSIFICADO_ERRO_FORMATO"
        resultado["erro_formato"] = str(exc)
    return resultado


def _chamada(modelo: ServingDatabricks, prompt: str, comentario: str,
             campo: str) -> dict:
    mensagens = [{"role": "system", "content": prompt},
                 {"role": "user", "content": comentario}]
    for tentativa in range(3):
        try:
            volta = modelo.extrair_estruturado(mensagens, max_tokens=160)
            bruto = volta.mensagem.get("content")
            resultado = {
                "chave": chave(prompt, comentario), "comentario": comentario,
                "resposta_bruta": bruto, "tokens_entrada": volta.tokens_entrada,
                "tokens_saida": volta.tokens_saida, "modelo": volta.modelo,
            }
            return interpretar_resposta(resultado, campo)
        except Exception as exc:  # erro de rede/modelo fica explícito no resultado
            if tentativa == 2:
                return {"chave": chave(prompt, comentario), "comentario": comentario,
                        "estado": "NAO_CLASSIFICADO_ERRO_CHAMADA", "erro": str(exc),
                        "tokens_entrada": 0, "tokens_saida": 0}
            time.sleep(2 ** tentativa)
    raise AssertionError("inalcançável")


def extrair_distintos(modelo: ServingDatabricks, comentarios: list[str],
                      prompt: str, campo: str, destino: Path,
                      trabalhadores: int = 6) -> list[dict]:
    existentes = {r["chave"]: r for r in ler_jsonl(destino)}
    corrigidos = []
    for item in existentes.values():
        if item.get("estado") == "NAO_CLASSIFICADO_ERRO_FORMATO":
            novo = interpretar_resposta(dict(item), campo)
            if novo["estado"] == "EXTRAIDO":
                novo["reprocessamento_local"] = True
                corrigidos.append(novo)
                existentes[novo["chave"]] = novo
    unicos = list(dict.fromkeys(comentarios))
    pendentes = [c for c in unicos if chave(prompt, c) not in existentes]
    destino.parent.mkdir(parents=True, exist_ok=True)
    if pendentes:
        modelo._obter_token()  # evita corrida de autenticação entre as threads
    with ThreadPoolExecutor(max_workers=trabalhadores) as pool, destino.open("a", encoding="utf-8") as arquivo:
        for corrigido in corrigidos:
            arquivo.write(json.dumps(corrigido, ensure_ascii=False) + "\n")
        futuros = [pool.submit(_chamada, modelo, prompt, c, campo) for c in pendentes]
        for indice, futuro in enumerate(as_completed(futuros), 1):
            resultado = futuro.result()
            arquivo.write(json.dumps(resultado, ensure_ascii=False) + "\n")
            arquivo.flush()
            existentes[resultado["chave"]] = resultado
            if indice % 50 == 0:
                print(f"{indice}/{len(pendentes)} chamadas novas concluídas", flush=True)
    return [existentes[chave(prompt, c)] for c in unicos]
