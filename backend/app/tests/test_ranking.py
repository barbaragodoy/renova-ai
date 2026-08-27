"""
Testes dos endpoints GET /ranking e GET /ranking/medico/{ufcrm}.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.tests.apoio_sessao import CABECALHO
from backend.app.auth.context import ContextoResponse, StatusContexto

CLIENT = TestClient(app)

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

_CABECALHO_SETOR = {
    "ciclo": "202608",
    "total_medicos": 1023,
    "pontos_lider": 425811.50,
    "qtd_painel_setor": 413,
}

_MEDICO = {
    "posicao": 1,
    "nome_medico": "MEDICO TESTE",
    "ufcrm": "SP0000001",
    "pontos": 425811.50,
    "flag_no_painel": 1,
    "especialidade": "PSIQUIATRIA",
    "cidade": "SAO PAULO",
    "uf": "SP",
}


def _mock_engine_lista(cabecalho, rows):
    """A listagem faz duas consultas na mesma conexão: o cabeçalho do setor
    (fetchone) e a página de médicos (fetchall)."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    resultado_cabecalho = MagicMock()
    resultado_cabecalho.mappings.return_value.fetchone.return_value = cabecalho
    resultado_rows = MagicMock()
    resultado_rows.mappings.return_value.fetchall.return_value = rows
    mock_conn.execute.side_effect = [resultado_cabecalho, resultado_rows]
    mock_eng = MagicMock()
    mock_eng.connect.return_value = mock_conn
    return mock_eng, mock_conn


def _mock_engine_detalhe(row):
    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.fetchone.return_value = row
    mock_eng = MagicMock()
    mock_eng.connect.return_value = mock_conn
    return mock_eng


def test_lista_ranking():
    mock_eng, _ = _mock_engine_lista(_CABECALHO_SETOR, [_MEDICO])
    with patch("backend.app.routers.ranking.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.ranking.get_engine", return_value=mock_eng):
            resp = CLIENT.get("/ranking", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ciclo"] == "202608"
    assert body["total_medicos"] == 1023
    assert body["medicos"][0]["no_painel"] is True
    assert body["medicos"][0]["especialidade"] == "PSIQUIATRIA"


def test_busca_vai_para_a_consulta_em_caixa_alta():
    """A busca roda no warehouse com o termo em caixa alta, porque a tabela
    guarda os nomes assim."""
    mock_eng, mock_conn = _mock_engine_lista(_CABECALHO_SETOR, [])
    with patch("backend.app.routers.ranking.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.ranking.get_engine", return_value=mock_eng):
            CLIENT.get("/ranking", params={"email": "ana.silva@ache.com.br", "q": "maria"}, headers=CABECALHO)
    params_da_lista = mock_conn.execute.call_args_list[1].args[1]
    assert params_da_lista["busca"] == "%MARIA%"


def test_propagandista_nao_encontrado():
    with patch("backend.app.routers.ranking.resolver_contexto", return_value=_CTX_NAO_ENCONTRADO):
        resp = CLIENT.get("/ranking", params={"email": "x@x.com"}, headers=CABECALHO)
    assert resp.status_code == 403


def test_detalhe_medico_fora_do_setor():
    mock_eng = _mock_engine_detalhe(None)
    with patch("backend.app.routers.ranking.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.ranking.get_engine", return_value=mock_eng):
            resp = CLIENT.get("/ranking/medico/RJ9999999", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 404


def test_detalhe_medico_completo():
    row = {
        "nome_medico": "MEDICO TESTE",
        "ufcrm": "SP0000001",
        "especialidade": "PSIQUIATRIA",
        "cidade": "SAO PAULO",
        "uf": "SP",
        "posicao": 12,
        "pontos": 1000.0,
        "pontos_lider": 425811.50,
        "flag_no_painel": 1,
        "qtd_medicos_painel_setor": 413,
        "data_ultima_visita": "2026-03-12",
        "meses_desde_ultima_visita": 5,
        "ciclos_no_painel_janela": 5,
        "recomendacao": "REMOVER",
        "criterio_saida": "dentro do corte sem visita",
        "ciclo_top1_categoria": "Medicamentos para dor e inflamação",
        "ciclo_top1_pct": 40.0,
        "ciclo_top2_categoria": None, "ciclo_top2_pct": None,
        "ciclo_top3_categoria": None, "ciclo_top3_pct": None,
        "ciclo_top1_produto": "PRODUTO X", "ciclo_top2_produto": None, "ciclo_top3_produto": None,
        "ciclo_pct_ache": 12.5,
        "ytd_top1_categoria": None, "ytd_top1_pct": None,
        "ytd_top2_categoria": None, "ytd_top3_categoria": None, "ytd_pct_ache": None,
        "geral_top1_categoria": None, "geral_top1_pct": None,
        "geral_top2_categoria": None, "geral_top3_categoria": None,
        "geral_top1_produto": None, "geral_top2_produto": None, "geral_top3_produto": None,
        "geral_pct_ache": None,
        "produto_recomendado_linha": "PRODUTO DA LINHA",
        "produto_recomendado_categoria": "Medicamentos para dor e inflamação",
        "rec_e_top1": 0,
        "ja_prescreve_o_produto": 0,
        "produto2_linha": "PRODUTO 2", "produto2_categoria": "Categoria 2",
        "produto3_linha": None, "produto3_categoria": None,
    }
    mock_eng = _mock_engine_detalhe(row)
    with patch("backend.app.routers.ranking.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.ranking.get_engine", return_value=mock_eng):
            resp = CLIENT.get("/ranking/medico/SP0000001", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO)
    assert resp.status_code == 200
    body = resp.json()
    assert body["recomendacao"] == "REMOVER"
    assert body["criterio_saida"] == "dentro do corte sem visita"
    assert body["janela"] == "no último ciclo"
    assert body["categorias"][0]["pct"] == 40.0
    assert body["produtos"] == ["PRODUTO X"]
    assert body["produto_recomendado"] == "PRODUTO DA LINHA"
    assert len(body["opcoes_produto"]) == 1
