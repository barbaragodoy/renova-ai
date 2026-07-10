"""
Simulação local do Databricks Genie usando LangChain + SQLAlchemy + LLM adapter.
Recebe pergunta em linguagem natural + contexto do propagandista e retorna
resposta em texto, SQL gerado e status.
"""
import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text

from backend.app.config import get_settings
from backend.app.llm.adapter import (
    LLMAdapter,
    LLMEmptyResponseError,
    LLMError,
    LLMTimeoutError,
    get_llm_provider,
)

_RULES_PATH = Path(__file__).parent / "intent_rules.json"

SCHEMA_RESUMIDO = """
-- tb_ranking_medicos: setor, cod_linha, ufcrm, nome_medico, soma_pontuacao, posicao_ranking, ciclo_referencia
-- tb_painel_medico: setor, ufcrm, nome_medico, especialidade, data_inclusao, ativo, ciclo_referencia
-- tb_prescricoes_geral: codigo_medico, ufcrm, nome_medico, especialidade, nome_medicacao, fabricante, quantidade, data_prescricao, setor
-- tb_recomendacoes_painel: id_recomendacao, rep_matricula, setor, cod_linha, ufcrm, nome_medico, tipo_recomendacao, status_recomendacao, posicao_ranking, soma_pontuacao, motivo_revisao, ciclo_referencia, data_geracao
-- tb_visitacao_medica: setor, ufcrm, data_visita, visita_efetiva, ciclo_referencia
-- tb_hierarquia_gd: gd_matricula, gd_email, gd_nome, rep_matricula, setor
"""

REGRAS_CONTEXTO = """
Regras de negócio obrigatórias:
- Corte de entrada: posicao_ranking <= 100 (simula <= 400 em produção)
- Corte de revisão: posicao_ranking > 100
- Médico sem visita efetiva há > 5 meses = critério de revisão
- Nunca expor dados da tabela tb_propagandistas nas respostas
- Limite de 5 sugestões por retorno
- Ciclo de referência padrão: {ciclo}
- Responda sempre em português brasileiro
"""


def _load_rules() -> dict:
    with open(_RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _classify_intent(pergunta: str, rules: dict) -> str:
    pergunta_lower = pergunta.lower()
    for kw in rules.get("TOTAL_GERAL", {}).get("palavras_chave", []):
        if kw in pergunta_lower:
            return "TOTAL_GERAL"
    return "OPERACIONAL"


def _extract_period(pergunta: str, rules: dict) -> Optional[str]:
    pattern = rules.get("periodo", {}).get("periodo_regex", "")
    if not pattern:
        return None
    match = re.search(pattern, pergunta, re.IGNORECASE)
    return match.group(0) if match else None


def _build_period_clause(periodo_str: Optional[str]) -> str:
    if periodo_str:
        return f"-- Filtro de período detectado: {periodo_str}. Aplique no campo data_prescricao ou data_visita conforme contexto."
    ano = date.today().year
    return f"-- Período: YTD (ano corrente). Use data_prescricao >= '{ano}-01-01' ou data_visita >= '{ano}-01-01' conforme contexto."


def _build_system_prompt(intent: str, setor: Optional[str], period_clause: str, ciclo: str) -> str:
    filtro_setor = (
        f"-- Filtro de setor OBRIGATÓRIO: WHERE setor = '{setor}'" if intent == "OPERACIONAL" and setor else ""
    )
    regras = REGRAS_CONTEXTO.format(ciclo=ciclo)
    return f"""Você é um assistente de análise de dados farmacêuticos da Aché.
Gere apenas SQL válido para PostgreSQL com base no schema abaixo.
Retorne SOMENTE o SQL, sem explicações, sem markdown, sem blocos de código.

Schema disponível:
{SCHEMA_RESUMIDO}

{regras}
{filtro_setor}
{period_clause}

Intenção classificada: {intent}
"""


def _build_synthesis_prompt(pergunta: str, sql: str, resultado: list[dict]) -> str:
    amostra = resultado[:10] if resultado else []
    return f"""Pergunta do usuário: {pergunta}

SQL executado:
{sql}

Resultado (primeiras {len(amostra)} linhas):
{json.dumps(amostra, ensure_ascii=False, default=str)}

Com base nesses dados, responda a pergunta do usuário de forma clara e objetiva em português.
Não mencione o SQL. Não invente dados além do resultado acima.
Se o resultado estiver vazio, informe que não há dados para o período ou filtro solicitado.
"""


async def consultar(
    pergunta: str,
    setor: Optional[str] = None,
    matricula: Optional[str] = None,
    periodo: Optional[str] = None,
    llm: Optional[LLMAdapter] = None,
) -> dict:
    """
    Retorna: {"resposta_texto": str, "sql_gerado": str, "status": str}
    status: OK | GENIE_TIMEOUT | GENIE_ERROR | EMPTY_RESPONSE | CONTEXT_ERROR
    """
    settings = get_settings()
    if llm is None:
        llm = get_llm_provider(settings)

    try:
        rules = _load_rules()
    except Exception as exc:
        return {"resposta_texto": "", "sql_gerado": "", "status": "CONTEXT_ERROR", "detalhe": str(exc)}

    intent = _classify_intent(pergunta, rules)
    periodo_detectado = periodo or _extract_period(pergunta, rules)
    period_clause = _build_period_clause(periodo_detectado)
    ciclo = settings.ciclo_referencia

    system_prompt = _build_system_prompt(intent, setor, period_clause, ciclo)

    # Etapa 1: gerar SQL
    try:
        sql_raw = await llm.complete(system_prompt, pergunta)
    except LLMTimeoutError:
        return {"resposta_texto": "", "sql_gerado": "", "status": "GENIE_TIMEOUT"}
    except LLMEmptyResponseError:
        return {"resposta_texto": "", "sql_gerado": "", "status": "EMPTY_RESPONSE"}
    except LLMError as exc:
        return {"resposta_texto": "", "sql_gerado": "", "status": "GENIE_ERROR", "detalhe": str(exc)}

    sql = sql_raw.strip().strip(";")

    # Etapa 2: executar SQL
    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).mappings().fetchall()
        resultado = [dict(r) for r in rows]
    except Exception as exc:
        return {
            "resposta_texto": "",
            "sql_gerado": sql,
            "status": "GENIE_ERROR",
            "detalhe": f"Erro ao executar SQL: {exc}",
        }

    # Etapa 3: sintetizar resposta
    synthesis_prompt = _build_synthesis_prompt(pergunta, sql, resultado)
    try:
        resposta_texto = await llm.complete(
            "Você é um assistente de dados da Aché. Responda em português, de forma clara e objetiva.",
            synthesis_prompt,
        )
    except LLMTimeoutError:
        return {"resposta_texto": "", "sql_gerado": sql, "status": "GENIE_TIMEOUT"}
    except LLMEmptyResponseError:
        return {"resposta_texto": "", "sql_gerado": sql, "status": "EMPTY_RESPONSE"}
    except LLMError as exc:
        return {"resposta_texto": "", "sql_gerado": sql, "status": "GENIE_ERROR", "detalhe": str(exc)}

    return {"resposta_texto": resposta_texto, "sql_gerado": sql, "status": "OK"}
