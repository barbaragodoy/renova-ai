"""
Testes dos endpoints GET /ranking e GET /ranking/medico/{ufcrm}.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.tests.apoio_sessao import CABECALHO
from backend.app.auth.context import ContextoResponse, StatusContexto

pytestmark = pytest.mark.usefixtures("liberar_acesso_por_padrao")

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


def _mock_engine_lista(cabecalho, rows, atualizado_em="2026-09-18 12:56:35"):
    """A listagem faz três consultas na mesma conexão, nesta ordem: o
    cabeçalho do setor (fetchone), a data de carga do histórico (scalar,
    desde 18/09/2026) e a página de médicos (fetchall)."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    resultado_cabecalho = MagicMock()
    resultado_cabecalho.mappings.return_value.fetchone.return_value = cabecalho
    resultado_atualizado = MagicMock()
    resultado_atualizado.scalar.return_value = atualizado_em
    resultado_rows = MagicMock()
    resultado_rows.mappings.return_value.fetchall.return_value = rows
    mock_conn.execute.side_effect = [resultado_cabecalho, resultado_atualizado, resultado_rows]
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
    # Índice 2: a consulta da página vem depois do cabeçalho e da data de carga.
    params_da_lista = mock_conn.execute.call_args_list[2].args[1]
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


# --------------------------------------------------------------------------- #
# Recomendacao pendente na lista, para a sinalizacao da aba Ranking.
# --------------------------------------------------------------------------- #


def _linha(status, id_rec="11111111-1111-1111-1111-111111111111", tipo="ENTRADA_PAINEL"):
    return dict(
        _MEDICO,
        id_recomendacao=id_rec,
        tipo_recomendacao=tipo,
        status_recomendacao=status,
    )


def _listar(rows):
    mock_eng, _ = _mock_engine_lista(_CABECALHO_SETOR, rows)
    with patch("backend.app.routers.ranking.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.ranking.get_engine", return_value=mock_eng):
            return CLIENT.get(
                "/ranking", params={"email": "ana.silva@ache.com.br"}, headers=CABECALHO
            ).json()["medicos"][0]


def test_pendente_traz_id_e_tipo_para_a_acao():
    m = _listar([_linha("PENDENTE")])
    assert m["id_recomendacao_pendente"] == "11111111-1111-1111-1111-111111111111"
    assert m["tipo_recomendacao_pendente"] == "ENTRADA_PAINEL"
    assert m["status_recomendacao"] == "PENDENTE"


@pytest.mark.parametrize("status", ["ACEITA", "DESCONSIDERADA", "APLICADA", "EXPIRADA", "INELEGIVEL"])
def test_recomendacao_resolvida_nao_devolve_id_acionavel(status):
    """O status sai sempre, para a linha mostrar a decisao ja tomada. O id e o
    tipo nao: sem recomendacao pendente nao existe o que aceitar nem o que
    desconsiderar, e devolver o id convidaria a tela a oferecer acao que o
    endpoint recusaria."""
    m = _listar([_linha(status)])
    assert m["status_recomendacao"] == status
    assert m["id_recomendacao_pendente"] is None
    assert m["tipo_recomendacao_pendente"] is None


def test_medico_sem_recomendacao_nenhuma():
    m = _listar([dict(_MEDICO)])
    assert m["status_recomendacao"] is None
    assert m["id_recomendacao_pendente"] is None


def test_juncao_do_databricks_garante_uma_linha_por_medico():
    """A tabela tem 580.911 grupos de matricula, medico e ciclo com mais de uma
    linha, medido em 04/09/2026. Sem a janela, a juncao multiplicaria o medico e
    a pagina devolveria menos de 50. O teste tranca as seis propriedades que
    fazem a cardinalidade e a escolha da linha serem deterministicas."""
    from backend.app.routers.ranking import _fragmentos_recomendacao
    join = _fragmentos_recomendacao("databricks")["join"]
    assert "ROW_NUMBER() OVER" in join
    assert "rec.ordem = 1" in join
    # Setor entra na particao: uma matricula pode ter mais de um setor.
    assert "PARTITION BY SETOR, UFCRM, CICLO_RECOMENDACAO" in join
    # A matricula corta antes da janela, que nao roda sobre a tabela inteira.
    assert "WHERE REP_MATRICULA = :mat" in join
    # Desempate deterministico: sem o id, duas linhas de mesma data alternariam.
    assert "ID_RECOMENDACAO DESC" in join
    # GREATEST e nao COALESCE: a primeira data nao nula nao e a mais recente.
    assert "GREATEST(" in join and "COALESCE(DATA_ACEITE" not in join


def test_juncao_local_sinaliza_recomendacao_sem_duplicar_medico():
    """O Postgres local tem o mesmo selo de ação usando sua tabela própria."""
    from backend.app.routers.ranking import _fragmentos_recomendacao

    frag = _fragmentos_recomendacao("local")
    assert "rec.id_recomendacao" in frag["select"]
    assert "FROM tb_recomendacoes_painel" in frag["join"]
    assert "ROW_NUMBER() OVER" in frag["join"]
    assert "PARTITION BY setor, ufcrm, ciclo_referencia" in frag["join"]
    assert "WHERE rep_matricula = :mat" in frag["join"]
    assert "rec.ordem = 1" in frag["join"]


def test_fonte_desconhecida_degrada_sem_sinalizacao():
    from backend.app.routers.ranking import _fragmentos_recomendacao

    assert _fragmentos_recomendacao("desconhecida") == {"select": "", "join": ""}



def test_busca_casa_nome_ou_ufcrm_e_lista_traz_ultima_visita():
    """"Pesquisar médico" da Home (20/09/2026): aceita nome ou CRM, e o card
    mostra a última visita sem abrir o detalhe."""
    mock_eng, mock_conn = _mock_engine_lista(
        _CABECALHO_SETOR, [{**_MEDICO, "ufcrm": "RJ0994499", "data_ultima_visita": "2026-09-15"}]
    )
    with patch("backend.app.routers.ranking.resolver_contexto", return_value=_CTX_VALIDO):
        with patch("backend.app.routers.ranking.get_engine", return_value=mock_eng):
            resp = CLIENT.get(
                "/ranking", params={"email": "ana.silva@ache.com.br", "q": "994499"}, headers=CABECALHO
            )
    assert resp.status_code == 200, resp.text
    sql = str(mock_conn.execute.call_args_list[2].args[0])
    assert "r.ufcrm LIKE :busca" in sql
    assert mock_conn.execute.call_args_list[2].args[1]["busca"] == "%994499%"
    assert resp.json()["medicos"][0]["data_ultima_visita"] == "2026-09-15"
