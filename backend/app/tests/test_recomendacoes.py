"""
Testes dos endpoints GET /recomendacoes/entrada e /recomendacoes/revisao.
Usa banco local via SQLAlchemy (requer Docker rodando).
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.tests.apoio_sessao import CABECALHO
from backend.app.auth.context import ContextoResponse, StatusContexto
from backend.app.config import get_settings

CLIENT = TestClient(app)

# Este arquivo testa contra a seed do Postgres local (schema
# tb_recomendacoes_painel) — deve continuar passando independente do
# DATA_SOURCE configurado no .env real (que pode estar em 'databricks' para
# rodar a API/test_recomendacoes_integration.py contra o Databricks de
# verdade). Fixture compartilhada em conftest.py, mesmo padrão de test_context.py.
pytestmark = pytest.mark.usefixtures("forcar_data_source_local")

_CTX_VALIDO = ContextoResponse(
    status=StatusContexto.SETOR_RESOLVIDO,
    matricula="REP001",
    setor="SP_INTERIOR",
    cod_linha="CARDIO",
    nome="Ana Silva",
)

_CTX_NAO_ENCONTRADO = ContextoResponse(
    status=StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO,
    mensagem="Não encontrado.",
)


@pytest.mark.requer_banco
def test_lista_entrada_com_pendencias():
    """Integração real: busca recomendações de entrada (pode retornar vazio se tabela vazia)."""
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tipo"] == "ENTRADA_PAINEL"
    assert isinstance(data["recomendacoes"], list)


def test_lista_entrada_vazia():
    """Retorna lista vazia quando não há pendências."""
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.mappings.return_value.fetchall.return_value = []
            mock_eng.return_value.connect.return_value = mock_conn
            resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_propagandista_nao_encontrado():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_NAO_ENCONTRADO):
        resp = CLIENT.get("/recomendacoes/entrada", params={"email": "x@x.com"}, headers=CABECALHO)
    assert resp.status_code == 403


@pytest.mark.requer_banco
def test_limite_5_registros():
    """Nunca deve retornar mais de 5 recomendações."""
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    assert len(resp.json()["recomendacoes"]) <= 5


def test_entrada_nome_medico_nulo_aplica_fallback():
    """NOME_MEDICO vem nulo da fonte real para candidatos a ENTRADA_PAINEL
    ainda fora do painel (ver docs/context/known-issues.md) — o endpoint não
    pode responder 500, deve aplicar o fallback consultivo com o UFCRM."""
    row = {
        "id_recomendacao": "11111111-1111-1111-1111-111111111111",
        "nome_medico": None,
        "ufcrm": "SP00099",
        "posicao_ranking": 42,
        "soma_pontuacao": 100.0,
        "ciclo_referencia": "202607",
    }
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.mappings.return_value.fetchall.return_value = [row]
            mock_eng.return_value.connect.return_value = mock_conn
            resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    item = resp.json()["recomendacoes"][0]
    assert item["nome_medico"] == "Médico ainda não identificado (UFCRM SP00099)"


def _mock_engine_ciclo(ciclo_max: str, capturados: list):
    """Mocka _engine() distinguindo a query MAX(...) (resolução do ciclo
    mais recente) e a query de limite de painel (Sprint 6, só executada em
    /revisao) da query principal de listagem — permite verificar qual ciclo
    foi efetivamente usado no bind param, e se a query MAX chegou a ser
    executada. A query de limite responde um valor fixo (318) e nunca entra
    em `capturados`, mesmo tratamento da MAX(...) — só a query principal de
    listagem é capturada."""
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "perfil_portal" in sql.lower():
            result.fetchone.return_value = MagicMock(limite=318)
        elif "MAX(" in sql:
            result.fetchone.return_value = MagicMock(ciclo=ciclo_max)
        else:
            capturados.append(params)
            result.mappings.return_value.fetchall.return_value = []
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def test_entrada_sem_ciclo_usa_max_da_tabela():
    """Sem ?ciclo= explícito, usa MAX(ciclo_referencia) da própria tabela em
    vez do default estático settings.ciclo_referencia (known-issue: default
    fica obsoleto a cada rollover mensal de ciclo)."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_ciclo("202699", capturados)):
            resp = CLIENT.get("/recomendacoes/entrada", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    assert capturados[0]["ciclo"] == "202699"


def test_entrada_com_ciclo_explicito_nao_consulta_max():
    """Com ?ciclo= explícito, a query MAX(...) nem chega a ser executada —
    o parâmetro do chamador prevalece, mesma capacidade já usada por
    test_recomendacoes_integration.py e documentada no README."""
    capturados = []
    chamadas_max = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)

            def _exec(query, params=None):
                sql = str(query)
                if "MAX(" in sql:
                    chamadas_max.append(True)
                result = MagicMock()
                capturados.append(params)
                result.mappings.return_value.fetchall.return_value = []
                return result

            conn.execute.side_effect = _exec
            mock_eng.return_value.connect.return_value = conn
            resp = CLIENT.get(
                "/recomendacoes/entrada",
                params={"email": "ana.silva@ache.com.br", "ciclo": "202501"},
                headers=CABECALHO,
            )
    assert resp.status_code == 200
    assert chamadas_max == []
    assert capturados[0]["ciclo"] == "202501"


def test_revisao_sem_ciclo_usa_max_da_tabela():
    """Mesmo comportamento de test_entrada_sem_ciclo_usa_max_da_tabela,
    para /recomendacoes/revisao — a correção foi aplicada nos dois
    endpoints, o known-issue afetava ambos igualmente."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_ciclo("202699", capturados)):
            resp = CLIENT.get("/recomendacoes/revisao", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    assert capturados[0]["ciclo"] == "202699"


def test_revisao_com_ciclo_explicito_nao_consulta_max():
    chamadas_max = []
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine") as mock_eng:
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)

            def _exec(query, params=None):
                sql = str(query)
                result = MagicMock()
                if "perfil_portal" in sql.lower():
                    result.fetchone.return_value = MagicMock(limite=318)
                    return result
                if "MAX(" in sql:
                    chamadas_max.append(True)
                capturados.append(params)
                result.mappings.return_value.fetchall.return_value = []
                return result

            conn.execute.side_effect = _exec
            mock_eng.return_value.connect.return_value = conn
            resp = CLIENT.get(
                "/recomendacoes/revisao",
                params={"email": "ana.silva@ache.com.br", "ciclo": "202501"},
                headers=CABECALHO,
            )
    assert resp.status_code == 200
    assert chamadas_max == []
    assert capturados[0]["ciclo"] == "202501"


# ---------------------------------------------------------------------------
# GET /recomendacoes/desconsideradas — aba Arquivadas (consulta)
# ---------------------------------------------------------------------------

_ROW_DESCONSIDERADA = {
    "id_recomendacao": "22222222-2222-2222-2222-222222222222",
    "nome_medico": "Dr. Fulano",
    "ufcrm": "SP00042",
    "tipo_recomendacao": "ENTRADA_PAINEL",
    "motivo_recomendacao": None,
    "motivo_desconsideracao": "MEDICO_APOSENTADO",
    "bloquear_novas_recomendacoes": True,
    "data_desconsideracao": "2026-08-01T10:00:00+00:00",
    "ciclo_recomendacao": "202507",
}


def _mock_engine_desconsideradas(rows=None, captured=None):
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if captured is not None:
            captured.append({"sql": sql, "params": params})
        result.mappings.return_value.fetchall.return_value = rows or []
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def test_lista_desconsideradas_retorna_status_desconsiderada():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch(
            "backend.app.routers.recomendacoes._engine",
            _mock_engine_desconsideradas(rows=[_ROW_DESCONSIDERADA]),
        ):
            resp = CLIENT.get(
                "/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["recomendacoes"][0]
    assert item["motivo_desconsideracao"] == "MEDICO_APOSENTADO"
    assert item["bloquear_novas_recomendacoes"] is True


def test_lista_desconsideradas_com_bloqueio_nulo_nao_quebra():
    """Achado em teste de ponta a ponta (14/08/2026): registros legados
    (anteriores à obrigatoriedade de bloquear_novas_recomendacoes no
    contrato de POST /desconsiderar) têm esse campo NULL no banco — estado
    válido segundo o próprio comentário da coluna ("NULL = sem decisão").
    DesconsideradaItem.bloquear_novas_recomendacoes precisa ser Optional
    para não derrubar a listagem inteira com 500 por causa de uma única
    linha antiga."""
    row_com_bloqueio_nulo = dict(_ROW_DESCONSIDERADA, bloquear_novas_recomendacoes=None)
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch(
            "backend.app.routers.recomendacoes._engine",
            _mock_engine_desconsideradas(rows=[row_com_bloqueio_nulo]),
        ):
            resp = CLIENT.get(
                "/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO
            )
    assert resp.status_code == 200
    item = resp.json()["recomendacoes"][0]
    assert item["bloquear_novas_recomendacoes"] is None


def test_lista_desconsideradas_filtra_por_status_e_matricula_autenticada():
    """A query filtra status_recomendacao = 'DESCONSIDERADA' e usa a
    matrícula resolvida via contexto autenticado (nunca aceita de outro
    propagandista/input externo) — garante que não vaza dado de terceiro."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(captured=capturados)):
            resp = CLIENT.get(
                "/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO
            )
    assert resp.status_code == 200
    sql = capturados[0]["sql"]
    assert "DESCONSIDERADA" in sql
    assert capturados[0]["params"] == {"mat": "REP001"}


def test_lista_desconsideradas_ordenacao_desc_por_data():
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(captured=capturados)):
            resp = CLIENT.get(
                "/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO
            )
    assert resp.status_code == 200
    sql = capturados[0]["sql"]
    assert "ORDER BY data_desconsideracao DESC" in sql


def test_lista_desconsideradas_vazia_nao_da_erro():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(rows=[])):
            resp = CLIENT.get(
                "/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO
            )
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "recomendacoes": []}


def test_lista_desconsideradas_sem_limit():
    """Diferente de /entrada e /revisao, não deve haver LIMIT na query —
    é consulta de histórico completo, não sugestão priorizada."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_desconsideradas(captured=capturados)):
            resp = CLIENT.get(
                "/recomendacoes/desconsideradas", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO
            )
    assert resp.status_code == 200
    assert "LIMIT" not in capturados[0]["sql"]


@pytest.mark.requer_banco
def test_desconsideradas_integracao_real_nao_retorna_de_outro_propagandista():
    """Integração real: REP002 (bruno.melo@ache.com.br) não deve ver a
    recomendação desconsiderada do cenário fixo pertencente a REP001
    (data/scripts/10_popular_cenarios_desconsiderar.sql, cenário 2)."""
    ctx_rep002 = ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO,
        matricula="REP002",
        setor="SP_INTERIOR",
        cod_linha="SNC",
        nome="Bruno Melo",
    )
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=ctx_rep002):
        resp = CLIENT.get(
            "/recomendacoes/desconsideradas", params={"email": "bruno.melo@ache.com.br"}, headers=CABECALHO
        )
    assert resp.status_code == 200
    ids = [item["id_recomendacao"] for item in resp.json()["recomendacoes"]]
    assert "10000000-0000-0000-0000-000000000002" not in ids


# ---------------------------------------------------------------------------
# LEFT JOIN com tb_dim_medicos (especialidade/cidade/uf/meses_sem_visita)
# ---------------------------------------------------------------------------

def _mock_engine_capturando(capturados: list):
    """Mocka _engine() registrando o texto de toda query executada — usado
    para inspecionar se um fragmento SQL específico foi ou não solicitado,
    sem depender do resultado retornado (sempre lista vazia)."""
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        capturados.append(sql)
        result = MagicMock()
        if "MAX(" in sql:
            result.fetchone.return_value = MagicMock(ciclo="202507")
        else:
            result.mappings.return_value.fetchall.return_value = []
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


# ---------------------------------------------------------------------------
# Sprint 6 — limite de painel por propagandista (substitui o corte fixo 400)
# ---------------------------------------------------------------------------

@pytest.mark.requer_banco
def test_limite_painel_integracao_real_local():
    """Integração real contra a seed de data/scripts/13_create_tb_perfil_portal.sql:
    REP001 tem limite customizado (250), REP002 tem limite customizado acima
    de 400 (450, cobre o caso que o corte fixo antigo rejeitaria e o limite
    novo aceita), REP003 tem limite explicitamente NULL e REP004 não tem
    nenhuma linha em tb_perfil_portal — os dois últimos caem no mesmo
    default 318 via COALESCE. Também confirma, na mesma consulta, que dois
    propagandistas com limite customizado recebem valores diferentes entre
    si (250 != 450)."""
    from backend.app.routers.recomendacoes import _limite_painel, _schema

    col = _schema("local")
    limite_rep001 = _limite_painel("REP001", col)
    limite_rep002 = _limite_painel("REP002", col)

    assert limite_rep001 == 250
    assert limite_rep002 == 450
    assert limite_rep001 != limite_rep002
    assert _limite_painel("REP003", col) == 318
    assert _limite_painel("REP004", col) == 318


@pytest.mark.requer_banco
def test_limite_painel_padrao_vem_de_tb_renovai_parametros_nao_de_literal():
    """Fase 3.5 (26/08/2026): o 318 deixou de ser um literal no código —
    agora é lido de tb_renovai_parametros a cada chamada. Este teste muda o
    valor na tabela, confirma que o comportamento do endpoint acompanha a
    mudança sem qualquer alteração de código, e devolve o valor original no
    finally — outros testes desta suíte (ex.: test_limite_painel_
    integracao_real_local acima) dependem de LIMITE_PAINEL_PADRAO=318."""
    from sqlalchemy import text as sqltext

    from backend.app.routers.recomendacoes import _engine, _limite_painel, _schema

    col = _schema("local")
    engine = _engine()

    with engine.connect() as conn:
        original = conn.execute(
            sqltext("SELECT limite_painel_padrao FROM tb_renovai_parametros WHERE id = 1")
        ).scalar()

    assert original == 318, "pré-condição: seed local deve começar em 318"
    assert _limite_painel("REP004", col) == 318  # REP004 não personalizou

    try:
        with engine.connect() as conn:
            conn.execute(
                sqltext("UPDATE tb_renovai_parametros SET limite_painel_padrao = 500 WHERE id = 1")
            )
            conn.commit()

        # Mesmo propagandista sem personalização, mesmo código — só o dado
        # mudou. REP001 (personalizado, 250) continua 250: a mudança do
        # padrão não deveria afetar quem já tem valor próprio.
        assert _limite_painel("REP004", col) == 500
        assert _limite_painel("REP001", col) == 250
    finally:
        with engine.connect() as conn:
            conn.execute(
                sqltext("UPDATE tb_renovai_parametros SET limite_painel_padrao = 318 WHERE id = 1")
            )
            conn.commit()

    assert _limite_painel("REP004", col) == 318


def _mock_engine_limite(limite_por_matricula: dict, capturados: list):
    """Mocka _engine() respondendo à query de limite (tb_perfil_portal) com o
    valor configurado por matrícula, resolvendo o ciclo via MAX(...) e
    capturando os parâmetros da query principal de listagem — mesmo estilo
    de _mock_engine_ciclo, com um terceiro tipo de query distinguido pelo
    texto SQL."""
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "perfil_portal" in sql.lower():
            mat = params["mat"]
            result.fetchone.return_value = MagicMock(limite=limite_por_matricula[mat])
        elif "MAX(" in sql:
            result.fetchone.return_value = MagicMock(ciclo="202608")
        else:
            capturados.append(params)
            result.mappings.return_value.fetchall.return_value = []
        return result

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


def test_revisao_usa_limite_personalizado_no_filtro(monkeypatch):
    """Databricks é a fonte que tem QTD_MEDICOS_PAINEL_CICLO — o filtro de
    defesa em profundidade só existe nela (ver _schema()['local']). Propagandista
    com limite personalizado (450) deve ter esse valor, não 318 nem 400,
    passado como bind param :limite_painel."""
    monkeypatch.setenv("DATA_SOURCE", "databricks")
    get_settings.cache_clear()
    ctx_rep002 = ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO, matricula="REP002",
        setor="SP_INTERIOR", cod_linha="CARDIO", nome="Bruno Melo",
    )
    capturados = []
    try:
        with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=ctx_rep002):
            with patch(
                "backend.app.routers.recomendacoes._engine",
                _mock_engine_limite({"REP002": 450}, capturados),
            ):
                resp = CLIENT.get(
                    "/recomendacoes/revisao",
                    params={"email": "bruno.melo@ache.com.br", "ciclo": "202608"},
                    headers=CABECALHO,
                )
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 200
    assert capturados[0]["limite_painel"] == 450


def test_revisao_sem_personalizacao_usa_default_318(monkeypatch):
    """Propagandista sem linha em tb_perfil_portal (ou com limite_painel
    NULL) cai no default 318 — mesmo valor que o notebook de geração usa na
    fonte real via COALESCE."""
    monkeypatch.setenv("DATA_SOURCE", "databricks")
    get_settings.cache_clear()
    ctx_rep004 = ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO, matricula="REP004",
        setor="RJ_CAPITAL", cod_linha="CARDIO", nome="Diego Costa",
    )
    capturados = []
    try:
        with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=ctx_rep004):
            with patch(
                "backend.app.routers.recomendacoes._engine",
                _mock_engine_limite({"REP004": 318}, capturados),
            ):
                resp = CLIENT.get(
                    "/recomendacoes/revisao",
                    params={"email": "diego.costa@ache.com.br", "ciclo": "202608"},
                    headers=CABECALHO,
                )
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 200
    assert capturados[0]["limite_painel"] == 318


def test_revisao_dois_propagandistas_limites_diferentes_geram_filtros_diferentes(monkeypatch):
    """Teste comparativo: dois propagandistas com limites diferentes (250 e
    450) devem gerar bind params :limite_painel diferentes entre si na
    mesma execução — confirma que o filtro não está fixo em nenhum valor
    único (nem 400, nem 318), e sim resolvido por matrícula a cada chamada."""
    monkeypatch.setenv("DATA_SOURCE", "databricks")
    get_settings.cache_clear()
    ctx_rep001 = ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO, matricula="REP001",
        setor="SP_INTERIOR", cod_linha="CARDIO", nome="Ana Lima",
    )
    ctx_rep002 = ContextoResponse(
        status=StatusContexto.SETOR_RESOLVIDO, matricula="REP002",
        setor="SP_INTERIOR", cod_linha="CARDIO", nome="Bruno Melo",
    )
    limites = {"REP001": 250, "REP002": 450}
    resultados = {}
    try:
        for mat, ctx in (("REP001", ctx_rep001), ("REP002", ctx_rep002)):
            capturados = []
            with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=ctx):
                with patch(
                    "backend.app.routers.recomendacoes._engine",
                    _mock_engine_limite(limites, capturados),
                ):
                    resp = CLIENT.get(
                        "/recomendacoes/revisao",
                        params={"email": "x@ache.com.br", "ciclo": "202608"},
                        headers=CABECALHO,
                    )
            assert resp.status_code == 200
            resultados[mat] = capturados[0]["limite_painel"]
    finally:
        get_settings.cache_clear()
    assert resultados["REP001"] == 250
    assert resultados["REP002"] == 450
    assert resultados["REP001"] != resultados["REP002"]


def test_entrada_nao_tem_filtro_de_limite_painel():
    """/entrada não ganhou filtro de limite (Fase 0 não indicou necessidade
    — sempre foi assim, mesmo antes do corte fixo 400 existir só em
    /revisao). Confirma que a query de /entrada não referencia
    limite_painel nem tb_perfil_portal."""
    capturados = []
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_capturando(capturados)):
            resp = CLIENT.get(
                "/recomendacoes/entrada",
                params={"email": "ana.silva@ache.com.br", "ciclo": "202608"},
                headers=CABECALHO,
            )
    assert resp.status_code == 200
    sql_entrada = "\n".join(capturados)
    assert "limite_painel" not in sql_entrada
    assert "perfil_portal" not in sql_entrada.lower()


def test_meses_sem_visita_so_aparece_em_revisao_e_desconsideradas(monkeypatch):
    """meses_sem_visita nunca é solicitado em /entrada (sem sentido
    semântico para ENTRADA_PAINEL — ver known-issues.md e o docstring de
    _fragmento_meses_sem_visita) — só em /revisao (cálculo direto, sem
    CASE, já que o endpoint só lista REVISAO_PAINEL) e /desconsideradas
    (com CASE, já que essa lista mistura os dois tipos). Força
    DATA_SOURCE=databricks (mockado — nunca conecta de verdade) para
    exercitar o fragmento condicional, que fica vazio no Postgres local
    (onde a suíte normalmente roda, via forcar_data_source_local)."""
    monkeypatch.setenv("DATA_SOURCE", "databricks")
    get_settings.cache_clear()

    capturas = {}
    for nome, caminho in (
        ("entrada", "/recomendacoes/entrada"),
        ("revisao", "/recomendacoes/revisao"),
        ("desconsideradas", "/recomendacoes/desconsideradas"),
    ):
        capturados = []
        with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
            with patch("backend.app.routers.recomendacoes._engine", _mock_engine_capturando(capturados)):
                resp = CLIENT.get(caminho, params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
        assert resp.status_code == 200
        capturas[nome] = "\n".join(capturados)

    assert "meses_sem_visita" not in capturas["entrada"]

    assert "meses_sem_visita" in capturas["revisao"]
    assert "CASE WHEN" not in capturas["revisao"]

    assert "meses_sem_visita" in capturas["desconsideradas"]
    assert "CASE WHEN" in capturas["desconsideradas"]
