"""
Testes de backend/app/genie/nl_to_sql.py.

Cobertura mínima, focada na regressão do ciclo: até esta correção, o prompt
do Genie sempre usava settings.ciclo_referencia (valor estático, obsoleto a
cada rollover de ciclo — ver docs/context/known-issues.md), sem nenhum
mecanismo de override. Mesmo bug já corrigido em
routers/recomendacoes.py:/entrada e /revisao via _ciclo_mais_recente().
"""
from unittest.mock import MagicMock, patch

import pytest

from backend.app.genie import nl_to_sql


class _LLMFake:
    """Substitui LLMAdapter: primeira chamada (geração de SQL) devolve um
    SELECT trivial, a segunda (síntese da resposta) devolve texto fixo.
    Guarda os prompts recebidos para inspeção pelo teste."""

    def __init__(self):
        self.chamadas = []

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.chamadas.append(system_prompt)
        if len(self.chamadas) == 1:
            return "SELECT 1"
        return "Resposta simulada."


def _mock_create_engine(ciclo_max: str):
    """Substitui create_engine (usado tanto por _ciclo_mais_recente() quanto
    pela execução do SQL gerado, linha 151) — distingue as duas consultas
    por string matching no SQL, mesmo padrão de test_recomendacoes.py."""

    def _factory(*args, **kwargs):
        mock_eng = MagicMock()
        conn = MagicMock()
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)

        def _exec(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "MAX(" in sql:
                result.fetchone.return_value = MagicMock(ciclo=ciclo_max)
            else:
                result.mappings.return_value.fetchall.return_value = []
            return result

        conn.execute.side_effect = _exec
        mock_eng.connect.return_value = conn
        return mock_eng

    return _factory


@pytest.mark.asyncio
async def test_consultar_usa_ciclo_maximo_da_tabela_nao_valor_fixo():
    """Regressão: o prompt do Genie deve refletir MAX(ciclo_referencia),
    nunca mais o default estático settings.ciclo_referencia. Usa um valor
    de MAX deliberadamente diferente do default estático ("202608" vs.
    "202507" em config.py) para provar que não é coincidência."""
    llm = _LLMFake()
    with patch("backend.app.genie.nl_to_sql.create_engine", side_effect=_mock_create_engine("202608")):
        resultado = await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", llm=llm)

    assert resultado["status"] == "OK"
    prompt_geracao_sql = llm.chamadas[0]
    assert "Ciclo de referência padrão: 202608" in prompt_geracao_sql
    assert "Ciclo de referência padrão: 202507" not in prompt_geracao_sql


@pytest.mark.asyncio
async def test_consultar_reflete_mudanca_de_ciclo_entre_chamadas():
    """Sem parâmetro de override, duas chamadas em momentos diferentes devem
    refletir o ciclo corrente de cada uma — não um valor fixo herdado do
    settings nem cacheado entre chamadas."""
    llm1 = _LLMFake()
    with patch("backend.app.genie.nl_to_sql.create_engine", side_effect=_mock_create_engine("202607")):
        await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", llm=llm1)
    assert "Ciclo de referência padrão: 202607" in llm1.chamadas[0]

    llm2 = _LLMFake()
    with patch("backend.app.genie.nl_to_sql.create_engine", side_effect=_mock_create_engine("202608")):
        await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", llm=llm2)
    assert "Ciclo de referência padrão: 202608" in llm2.chamadas[0]
