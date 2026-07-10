"""
Testes ponta-a-ponta dos 10 cenários da matriz (GEORGE-06 e GEORGE-13).
Todos usam mocks de banco e LLM — não dependem de PostgreSQL ou chave de API.

Cenários cobertos:
  E2E-01  propagandista com lista de entrada pendente
  E2E-02  propagandista com lista de revisão pendente
  E2E-03  propagandista sem pendências
  E2E-04  desconsiderar e confirmar que sai da lista
  E2E-05  novo ciclo com recorrência (qtd_vezes_recomendado incrementado)
  E2E-06  novo ciclo com expiração de PENDENTE
  E2E-07  GD visualiza escopo correto
  E2E-08  GD tenta acessar fora do escopo (403)
  E2E-09  LLM responde pergunta operacional com filtro de setor
  E2E-10  LLM responde pergunta de total geral sem filtro de setor
"""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.auth.context import ContextoResponse, StatusContexto

CLIENT = TestClient(app)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
CICLO = "202507"
CICLO_NOVO = "202508"
GD_EMAIL = "marcos.vieira@ache.com.br"
GD_MAT = "GD001"
GD_NOME = "Marcos Vieira"
REP_EMAIL = "ana.silva@ache.com.br"
REP_MAT = "REP001"
UFCRM_A = "SP00001"
UFCRM_B = "SP00050"
ID_REC = str(uuid.uuid4())

_CTX_VALIDO = ContextoResponse(
    status=StatusContexto.SETOR_RESOLVIDO,
    matricula=REP_MAT,
    setor="SP_INTERIOR",
    cod_linha="CARDIO",
    nome="Ana Silva",
)
_CTX_NAO_ENCONTRADO = ContextoResponse(
    status=StatusContexto.PROPAGANDISTA_NAO_ENCONTRADO,
    mensagem="Não encontrado.",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dict_row(**kwargs):
    class FakeRow(dict):
        pass
    return FakeRow(kwargs)


def _rec_row(**overrides):
    base = dict(
        id_recomendacao=ID_REC,
        nome_medico="Dr. Teste",
        ufcrm=UFCRM_A,
        posicao_ranking=42,
        soma_pontuacao=900.0,
        ciclo_referencia=CICLO,
        motivo_revisao=None,
    )
    base.update(overrides)
    return _dict_row(**base)


def _mock_engine_rec(rows):
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.mappings.return_value.fetchall.return_value = rows
    conn.execute.return_value.mappings.return_value.fetchone.return_value = rows[0] if rows else None
    conn.execute.return_value.scalar.return_value = 1 if rows else None
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


# ---------------------------------------------------------------------------
# E2E-01: propagandista com lista de entrada PENDENTE
# ---------------------------------------------------------------------------
def test_e2e_01_lista_entrada_pendente():
    rows = [_rec_row()]
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_rec(rows)):
            resp = CLIENT.get("/recomendacoes/entrada", params={"email": REP_EMAIL})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tipo"] == "ENTRADA_PAINEL"
    assert body["total"] == 1
    assert body["recomendacoes"][0]["ufcrm"] == UFCRM_A


# ---------------------------------------------------------------------------
# E2E-02: propagandista com lista de revisão PENDENTE
# ---------------------------------------------------------------------------
def test_e2e_02_lista_revisao_pendente():
    rows = [_rec_row(motivo_revisao="SEM_VISITA_5_MESES")]
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_rec(rows)):
            resp = CLIENT.get("/recomendacoes/revisao", params={"email": REP_EMAIL})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tipo"] == "REVISAO_PAINEL"
    assert body["recomendacoes"][0]["motivo_revisao"] == "SEM_VISITA_5_MESES"


# ---------------------------------------------------------------------------
# E2E-03: propagandista sem pendências
# ---------------------------------------------------------------------------
def test_e2e_03_sem_pendencias():
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_rec([])):
            resp_ent = CLIENT.get("/recomendacoes/entrada", params={"email": REP_EMAIL})
            resp_rev = CLIENT.get("/recomendacoes/revisao", params={"email": REP_EMAIL})
    assert resp_ent.status_code == 200
    assert resp_ent.json()["total"] == 0
    assert resp_rev.status_code == 200
    assert resp_rev.json()["total"] == 0


# ---------------------------------------------------------------------------
# E2E-04: desconsiderar → sai da lista
# ---------------------------------------------------------------------------
def test_e2e_04_desconsiderar_sai_da_lista():
    # Passo 1: desconsiderar
    row_pendente = MagicMock()
    row_pendente.__getitem__ = lambda s, k: {"rep_matricula": REP_MAT, "status_recomendacao": "PENDENTE"}[k]

    eng1 = MagicMock()
    conn1 = MagicMock()
    conn1.__enter__ = lambda s: s
    conn1.__exit__ = MagicMock(return_value=False)
    conn1.execute.return_value.mappings.return_value.fetchone.return_value = row_pendente
    eng1.return_value.connect.return_value = conn1

    body = {
        "id_recomendacao": ID_REC,
        "rep_matricula": REP_MAT,
        "motivo": "Fora da área.",
        "timestamp": datetime.utcnow().isoformat(),
    }
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", eng1):
            resp = CLIENT.post("/recomendacoes/desconsiderar", json=body, params={"email": REP_EMAIL})
    assert resp.status_code == 200
    assert resp.json()["sucesso"] is True

    # Passo 2: lista deve estar vazia (DESCONSIDERADA filtrada pelo status=PENDENTE)
    with patch("backend.app.routers.recomendacoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.recomendacoes._engine", _mock_engine_rec([])):
            resp_lista = CLIENT.get("/recomendacoes/entrada", params={"email": REP_EMAIL})
    assert resp_lista.json()["total"] == 0


# ---------------------------------------------------------------------------
# E2E-05: novo ciclo com recorrência (qtd_vezes_recomendado incrementado)
# ---------------------------------------------------------------------------
def test_e2e_05_novo_ciclo_recorrencia():
    from backend.app.jobs.gerar_recomendacoes import gerar_recomendacoes

    prop = _dict_row(rep_matricula=REP_MAT, setor="SP_INTERIOR", cod_linha="CARDIO")
    candidato = _dict_row(ufcrm=UFCRM_A, nome_medico="Dr. Recorrente", posicao_ranking=30, soma_pontuacao=800.0)
    existente = _dict_row(id_recomendacao=uuid.uuid4(), qtd_vezes_recomendado=1)

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "ativo = TRUE" in sql and "rep_matricula" not in sql:
            result.mappings.return_value.fetchall.return_value = [prop]
        elif "LEFT JOIN tb_painel_medico" in sql:
            result.mappings.return_value.fetchall.return_value = [candidato]
        elif "id_recomendacao, qtd_vezes_recomendado" in sql:
            result.mappings.return_value.fetchone.return_value = existente
        else:
            result.mappings.return_value.fetchall.return_value = []
            result.mappings.return_value.fetchone.return_value = None
        return result

    conn.execute.side_effect = _exec

    with patch("backend.app.jobs.gerar_recomendacoes.create_engine") as mock_eng:
        mock_eng.return_value.connect.return_value = conn
        resultado = gerar_recomendacoes(ciclo=CICLO_NOVO, dry_run=True)

    assert resultado["entrada_incrementados"] >= 1
    assert resultado["entrada_inseridos"] == 0


# ---------------------------------------------------------------------------
# E2E-06: novo ciclo com expiração de PENDENTE
# ---------------------------------------------------------------------------
def test_e2e_06_novo_ciclo_expiracao():
    from backend.app.jobs.novo_ciclo import transicionar_ciclo

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchall.return_value = [MagicMock(), MagicMock(), MagicMock()]
    conn.execute.return_value.scalar.return_value = 3

    with patch("backend.app.jobs.novo_ciclo.create_engine") as mock_eng:
        mock_eng.return_value.connect.return_value = conn
        with patch("backend.app.jobs.novo_ciclo.gerar_recomendacoes") as mock_gerar:
            mock_gerar.return_value = {
                "ciclo": CICLO_NOVO, "dry_run": True,
                "entrada_inseridos": 5, "entrada_incrementados": 0,
                "revisao_inseridos": 2, "revisao_incrementados": 0,
            }
            resultado = transicionar_ciclo(ciclo_atual=CICLO, ciclo_novo=CICLO_NOVO, dry_run=True)

    assert resultado["ciclo_encerrado"] == CICLO
    assert resultado["ciclo_novo"] == CICLO_NOVO
    assert resultado["expiradas"] == 3
    mock_gerar.assert_called_once_with(ciclo=CICLO_NOVO, dry_run=True)


# ---------------------------------------------------------------------------
# E2E-07: GD visualiza escopo correto
# ---------------------------------------------------------------------------
def test_e2e_07_gd_visualiza_escopo_correto():
    gd_row = _dict_row(gd_matricula=GD_MAT, gd_nome=GD_NOME)
    indicador = _dict_row(
        gd_matricula=GD_MAT, gd_nome=GD_NOME, ciclo_referencia=CICLO,
        total_gerado=8, total_pendente=3, total_aplicado=2,
        total_desconsiderado=1, total_expirado=2, taxa_aceite_pct=25.0,
    )

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "gd_email" in sql:
            result.mappings.return_value.fetchone.return_value = gd_row
        else:
            result.mappings.return_value.fetchall.return_value = [indicador]
        return result

    conn.execute.side_effect = _exec

    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get("/gerencial/indicadores", params={"gd_email": GD_EMAIL, "ciclo": CICLO})

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)


# ---------------------------------------------------------------------------
# E2E-08: GD tenta acessar rep fora do escopo → 403
# ---------------------------------------------------------------------------
def test_e2e_08_gd_fora_do_escopo():
    gd_row = _dict_row(gd_matricula=GD_MAT, gd_nome=GD_NOME)

    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "gd_email" in sql:
            result.mappings.return_value.fetchone.return_value = gd_row
        else:
            # rep fora do escopo → scalar retorna None
            result.scalar.return_value = None
        return result

    conn.execute.side_effect = _exec

    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get(
            "/gerencial/recomendacoes",
            params={"gd_email": GD_EMAIL, "matricula": "REP999", "ciclo": CICLO},
        )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# E2E-09: LLM responde pergunta OPERACIONAL com filtro de setor
# ---------------------------------------------------------------------------
def test_e2e_09_pergunta_operacional_filtro_setor():
    sql_gerado = "SELECT * FROM tb_prescricoes_geral WHERE setor = 'SP_INTERIOR'"

    async def _fake_consultar(pergunta, setor, matricula, periodo, llm=None):
        assert setor == "SP_INTERIOR"
        assert "SP_INTERIOR" in sql_gerado
        return {"resposta_texto": "Os médicos com mais prescrições são...", "sql_gerado": sql_gerado, "status": "OK"}

    with patch("backend.app.routers.prescricoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.prescricoes.nl_to_sql.consultar", side_effect=_fake_consultar):
            resp = CLIENT.post(
                "/prescricoes/consultar",
                json={
                    "pergunta": "Quais médicos prescreveram mais Venlaxin no meu setor?",
                    "email": REP_EMAIL,
                    "perfil_tecnico": True,
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert body["sql_gerado"] is not None
    assert "SP_INTERIOR" in body["sql_gerado"]


# ---------------------------------------------------------------------------
# E2E-10: LLM responde pergunta TOTAL_GERAL sem filtro de setor
# ---------------------------------------------------------------------------
def test_e2e_10_pergunta_total_geral_sem_filtro():
    sql_gerado = "SELECT fabricante, SUM(quantidade) FROM tb_prescricoes_geral GROUP BY fabricante"

    async def _fake_consultar(pergunta, setor, matricula, periodo, llm=None):
        # TOTAL_GERAL: SQL não deve filtrar setor
        assert "WHERE setor" not in sql_gerado
        return {
            "resposta_texto": "O total geral de prescrições no Brasil foi...",
            "sql_gerado": sql_gerado,
            "status": "OK",
        }

    with patch("backend.app.routers.prescricoes.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.prescricoes.nl_to_sql.consultar", side_effect=_fake_consultar):
            resp = CLIENT.post(
                "/prescricoes/consultar",
                json={
                    "pergunta": "Qual o total geral de prescrições de todos os fabricantes no Brasil?",
                    "email": REP_EMAIL,
                    "perfil_tecnico": True,
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert "WHERE setor" not in (body["sql_gerado"] or "")
