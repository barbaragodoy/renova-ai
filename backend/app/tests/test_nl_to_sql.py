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


def _mock_create_engine(ciclo_max: str, limite_painel_padrao: int = 300):
    """Substitui create_engine (usado por _ciclo_mais_recente(),
    _limite_painel() e pela execução do SQL gerado) — distingue as
    consultas por string matching no SQL, mesmo padrão de
    test_recomendacoes.py.

    `limite_painel_padrao` (tb_renovai_parametros, via `.scalar()`) é o
    único limite desde 18/09/2026. Uma consulta a tb_perfil_portal aqui é
    defeito: a personalização por propagandista saiu."""

    def _factory(*args, **kwargs):
        mock_eng = MagicMock()
        conn = MagicMock()
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)

        def _exec(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "tb_renovai_parametros" in sql:
                result.scalar.return_value = limite_painel_padrao
            elif "tb_perfil_portal" in sql:
                raise AssertionError(
                    "tb_perfil_portal não deve mais ser consultada para o limite do painel"
                )
            elif "MAX(" in sql:
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


# ---------------------------------------------------------------------------
# Sprint 6 — limite de painel e janela de visita dinâmicos (Fase 0 confirmou
# valores fixos em texto livre no prompt: "posicao_ranking <= 100 (simula <=
# 400 em produção)" e "sem visita efetiva há > 5 meses" — REGRAS_CONTEXTO
# agora usa {limite_painel}/{sem_visita_meses} interpolados, nunca mais
# literais).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consultar_injeta_o_limite_unico_no_prompt():
    """O prompt reflete o valor de tb_renovai_parametros, não 100 nem 400
    fixos, e não passa por tb_perfil_portal."""
    llm = _LLMFake()
    with patch("backend.app.genie.nl_to_sql.create_engine", side_effect=_mock_create_engine("202608", limite_painel_padrao=300)):
        resultado = await nl_to_sql.consultar(
            "Quantas recomendações tenho pendentes?", matricula="REP002", llm=llm
        )
    assert resultado["status"] == "OK"
    prompt = llm.chamadas[0]
    assert "posicao_ranking <= 300" in prompt
    assert "posicao_ranking > 300" in prompt
    assert "<= 100" not in prompt
    assert "<= 400" not in prompt


@pytest.mark.asyncio
async def test_consultar_dois_propagandistas_recebem_o_mesmo_limite():
    """O oposto do que valia até 18/09/2026: matrículas diferentes, mesmo
    limite no prompt."""
    llm1 = _LLMFake()
    with patch("backend.app.genie.nl_to_sql.create_engine", side_effect=_mock_create_engine("202608")):
        await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", matricula="REP001", llm=llm1)

    llm2 = _LLMFake()
    with patch("backend.app.genie.nl_to_sql.create_engine", side_effect=_mock_create_engine("202608")):
        await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", matricula="REP002", llm=llm2)

    assert "posicao_ranking <= 300" in llm1.chamadas[0]
    assert "posicao_ranking <= 300" in llm2.chamadas[0]


@pytest.mark.asyncio
async def test_consultar_sem_matricula_usa_default_sem_consultar_perfil_portal():
    """Sem matrícula (não deveria ocorrer em uso normal — prescricoes.py
    sempre resolve contexto antes de chamar consultar() — mas o helper não
    deve quebrar), cai no default de tb_renovai_parametros sem consultar
    tb_perfil_portal (não haveria matrícula para filtrar).

    Diferente de antes da Fase 3.5 (26/08/2026): o default deixou de ser um
    318 literal em Python, então uma consulta a tb_renovai_parametros
    sempre acontece — o que este teste não faz mais é pular o banco
    inteiro, e sim pular especificamente a consulta a tb_perfil_portal."""
    llm = _LLMFake()
    with patch(
        "backend.app.genie.nl_to_sql.create_engine",
        side_effect=_mock_create_engine("202608", limite_painel_padrao=318),
    ):
        resultado = await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", llm=llm)
    assert resultado["status"] == "OK"
    assert "posicao_ranking <= 318" in llm.chamadas[0]


@pytest.mark.asyncio
async def test_consultar_default_reflete_tb_renovai_parametros_nao_literal():
    """Fase 3.5 (26/08/2026): muda o valor de tb_renovai_parametros (mock) e
    confirma que o prompt acompanha — sem matrícula, então sem
    personalização de tb_perfil_portal para mascarar o efeito."""
    llm = _LLMFake()
    with patch(
        "backend.app.genie.nl_to_sql.create_engine",
        side_effect=_mock_create_engine("202608", limite_painel_padrao=500),
    ):
        resultado = await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", llm=llm)
    assert resultado["status"] == "OK"
    assert "posicao_ranking <= 500" in llm.chamadas[0]
    assert "posicao_ranking <= 318" not in llm.chamadas[0]


@pytest.mark.asyncio
async def test_consultar_janela_de_visita_reflete_settings_sem_visita_meses():
    """A janela de visita no prompt deve refletir settings.sem_visita_meses
    (3, Sprint 6) — nunca mais o valor antigo de 5 meses fixo no texto."""
    llm = _LLMFake()
    with patch("backend.app.genie.nl_to_sql.create_engine", side_effect=_mock_create_engine("202608")):
        resultado = await nl_to_sql.consultar("Quantas recomendações tenho pendentes?", llm=llm)
    assert resultado["status"] == "OK"
    prompt = llm.chamadas[0]
    assert "há > 3 meses" in prompt
    assert "há > 5 meses" not in prompt
