"""
Testes de integração dos endpoints GET /recomendacoes/entrada e /revisao
contra o Databricks REAL (tb_recomendacoes_painel_historico), via OAuth M2M
do Service Principal sp-renovai-genie-api-poc.

Só rodam com DATA_SOURCE=databricks no .env (preenchido com
DATABRICKS_CLIENT_SECRET real) — em qualquer outro valor de DATA_SOURCE,
são pulados (skip), para não quebrar `pytest` local/CI sem credenciais.
Mesmo padrão de test_context_integration.py.

HISTÓRICO — bloqueio de STATUS_RECOMENDACAO RESOLVIDO em 2026-07-30 (ver
docs/context/known-issues.md): a fonte real hoje tem 100% das linhas com
STATUS_RECOMENDACAO = 'PENDENTE'. Os testes de conteúdo (ordenação, filtro
de painel > 400) buscam um REP_MATRICULA explicitamente elegível via query
direta à fonte (_rep_elegivel), em vez de um e-mail aleatório — um e-mail
aleatório continuaria podendo cair numa lista vazia (nem todo propagandista
tem recomendação pendente de um tipo específico no ciclo). Também resolvem
o ciclo real dinamicamente (MAX(CICLO_RECOMENDACAO)) em vez de depender do
default estático CICLO_REFERENCIA em config.py/.env, que fica desatualizado
a cada rollover mensal de ciclo — descoberto em 2026-07-30 (default
'202507' vs. ciclo real '202607' na fonte).

HISTÓRICO — NOME_MEDICO nulo em ENTRADA_PAINEL RESOLVIDO NA ORIGEM em
2026-07-31 (ver docs/context/known-issues.md): Hugo corrigiu via COALESCE
com a tabela dimensional ranking_medicos_renovache_dim_medicos. O fallback
em routers/recomendacoes.py permanece como defesa em profundidade
permanente, mas não é mais exigido nos testes de conteúdo — ver
test_entrada_ordenada_por_soma_pontuacao_desc.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.config import get_settings
from backend.app.db.databricks_connection import get_engine
from backend.app.main import app

pytestmark = pytest.mark.skipif(
    get_settings().data_source.lower() != "databricks",
    reason="Requer DATA_SOURCE=databricks e credenciais reais do SP no .env.",
)

CLIENT = TestClient(app)

EMAIL_INEXISTENTE = "fulano.naoexiste.recomendacoes@ache.com.br"


def _um_email_real(dominio: str = "ache.com.br") -> str:
    """Busca um e-mail real na tb_propagandistas, igual test_context_integration.py."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT rep_email FROM tb_propagandistas WHERE rep_email LIKE :padrao LIMIT 1"),
            {"padrao": f"%@{dominio}"},
        ).fetchone()
    assert row is not None, f"Nenhum e-mail @{dominio} encontrado em tb_propagandistas."
    return row.rep_email


def _ciclo_atual() -> str:
    """Descobre o ciclo real mais recente na fonte, em vez de depender do
    default estático CICLO_REFERENCIA em config.py (fica desatualizado a
    cada rollover mensal de ciclo)."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(CICLO_RECOMENDACAO) AS ciclo FROM tb_recomendacoes_painel_historico")
        ).fetchone()
    assert row is not None and row.ciclo is not None, "Nenhum ciclo encontrado em tb_recomendacoes_painel_historico."
    return row.ciclo


def _rep_elegivel(tipo: str, ciclo: str) -> str:
    """Busca o e-mail de um propagandista com pelo menos uma recomendação
    PENDENTE do tipo pedido no ciclo real (em vez de um e-mail aleatório,
    que pode não ter recomendação nenhuma daquele tipo)."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT REP_MATRICULA FROM tb_recomendacoes_painel_historico "
                "WHERE TIPO_RECOMENDACAO = :tipo AND STATUS_RECOMENDACAO = 'PENDENTE' "
                "AND CICLO_RECOMENDACAO = :ciclo "
                "GROUP BY REP_MATRICULA LIMIT 1"
            ),
            {"tipo": tipo, "ciclo": ciclo},
        ).fetchone()
        assert row is not None, f"Nenhum REP_MATRICULA elegível para {tipo} no ciclo {ciclo}."

        email_row = conn.execute(
            text("SELECT rep_email FROM tb_propagandistas WHERE rep_matricula = :mat LIMIT 1"),
            {"mat": row.REP_MATRICULA},
        ).fetchone()
    assert email_row is not None, f"REP_MATRICULA {row.REP_MATRICULA} não encontrado em tb_propagandistas."
    return email_row.rep_email


def _qtd_medicos_painel(id_recomendacao: str):
    """Consulta direta à fonte para validar o filtro de painel > 400 por fora do endpoint."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT QTD_MEDICOS_PAINEL_CICLO FROM tb_recomendacoes_painel_historico "
                "WHERE ID_RECOMENDACAO = :id"
            ),
            {"id": id_recomendacao},
        ).fetchone()
    return row.QTD_MEDICOS_PAINEL_CICLO if row is not None else None


def test_propagandista_nao_encontrado_entrada():
    resp = CLIENT.get("/recomendacoes/entrada", params={"email": EMAIL_INEXISTENTE})
    assert resp.status_code == 403
    assert resp.json()["detail"]["status"] == "PROPAGANDISTA_NAO_ENCONTRADO"


def test_propagandista_nao_encontrado_revisao():
    resp = CLIENT.get("/recomendacoes/revisao", params={"email": EMAIL_INEXISTENTE})
    assert resp.status_code == 403
    assert resp.json()["detail"]["status"] == "PROPAGANDISTA_NAO_ENCONTRADO"


def test_entrada_email_real_lista_coerente():
    email = _um_email_real()
    resp = CLIENT.get("/recomendacoes/entrada", params={"email": email})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tipo"] == "ENTRADA_PAINEL"
    assert isinstance(data["recomendacoes"], list)
    assert data["total"] == len(data["recomendacoes"])
    assert len(data["recomendacoes"]) <= 5
    for item in data["recomendacoes"]:
        assert item["id_recomendacao"]
        assert item["nome_medico"]
        assert item["ufcrm"]
        assert item["ciclo_referencia"]


def test_entrada_ordenada_por_soma_pontuacao_desc():
    """NOME_MEDICO estava nulo em 100% das linhas reais de ENTRADA_PAINEL
    até 2026-07-30 (ver docs/context/known-issues.md); Hugo corrigiu na
    origem em 2026-07-31 via COALESCE com a tabela dimensional
    ranking_medicos_renovache_dim_medicos — hoje 0 nulos. O fallback
    aplicado em routers/recomendacoes.py (_aplicar_fallback_nome_medico)
    permanece no código como defesa em profundidade permanente, não é mais
    esperado aparecer nos dados atuais — por isso não exigimos aqui que
    apareça, só que nome_medico nunca venha vazio/None e que a ordenação
    continue correta."""
    ciclo = _ciclo_atual()
    email = _rep_elegivel("ENTRADA_PAINEL", ciclo)
    resp = CLIENT.get("/recomendacoes/entrada", params={"email": email, "ciclo": ciclo})
    assert resp.status_code == 200
    itens = resp.json()["recomendacoes"]
    assert itens, "Rep elegível via query direta à fonte, mas o endpoint devolveu lista vazia."
    pontuacoes = [i["soma_pontuacao"] for i in itens if i["soma_pontuacao"] is not None]
    assert pontuacoes == sorted(pontuacoes, reverse=True)
    for item in itens:
        assert item["nome_medico"], "nome_medico não pode vir vazio/None no payload — fallback deveria ter sido aplicado."


def test_revisao_email_real_lista_coerente():
    email = _um_email_real()
    resp = CLIENT.get("/recomendacoes/revisao", params={"email": email})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tipo"] == "REVISAO_PAINEL"
    assert isinstance(data["recomendacoes"], list)
    assert data["total"] == len(data["recomendacoes"])
    assert len(data["recomendacoes"]) <= 5


def test_revisao_ordenada_por_posicao_ranking_desc():
    ciclo = _ciclo_atual()
    email = _rep_elegivel("REVISAO_PAINEL", ciclo)
    resp = CLIENT.get("/recomendacoes/revisao", params={"email": email, "ciclo": ciclo})
    assert resp.status_code == 200
    itens = resp.json()["recomendacoes"]
    assert itens, "Rep elegível via query direta à fonte, mas o endpoint devolveu lista vazia."
    posicoes = [i["posicao_ranking"] for i in itens if i["posicao_ranking"] is not None]
    assert posicoes == sorted(posicoes, reverse=True)


def test_revisao_respeita_guarda_painel_maior_que_400():
    """Defesa em profundidade: nenhum item retornado pode ter
    QTD_MEDICOS_PAINEL_CICLO <= 400 na fonte, mesmo que a coluna não venha
    no payload de resposta (ver mapeamento em routers/recomendacoes.py)."""
    ciclo = _ciclo_atual()
    email = _rep_elegivel("REVISAO_PAINEL", ciclo)
    resp = CLIENT.get("/recomendacoes/revisao", params={"email": email, "ciclo": ciclo})
    assert resp.status_code == 200
    itens = resp.json()["recomendacoes"]
    assert itens, "Rep elegível via query direta à fonte, mas o endpoint devolveu lista vazia."
    for item in itens:
        qtd = _qtd_medicos_painel(item["id_recomendacao"])
        assert qtd is not None
        assert qtd > 400
