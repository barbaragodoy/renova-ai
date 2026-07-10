"""
Testes dos endpoints gerenciais (GEORGE-13).
Cobre: acesso no escopo, fora do escopo, filtros, dados ausentes.
"""
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

CLIENT = TestClient(app)

GD_EMAIL = "marcos.vieira@ache.com.br"
GD_MAT = "GD001"
GD_NOME = "Marcos Vieira"
REP_MAT = "REP001"
CICLO = "202507"

_GD_ROW = {"gd_matricula": GD_MAT, "gd_nome": GD_NOME}


def _make_conn(rows_by_keyword: dict):
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _execute(query, params=None):
        sql = str(query)
        result = MagicMock()
        for kw, rows in rows_by_keyword.items():
            if kw in sql:
                if isinstance(rows, list):
                    result.mappings.return_value.fetchall.return_value = rows
                    result.mappings.return_value.fetchone.return_value = rows[0] if rows else None
                    result.scalar.return_value = rows[0] if rows else None
                else:
                    result.mappings.return_value.fetchone.return_value = rows
                    result.scalar.return_value = rows
                return result
        result.mappings.return_value.fetchall.return_value = []
        result.mappings.return_value.fetchone.return_value = None
        result.scalar.return_value = None
        return result

    conn.execute.side_effect = _execute
    return conn


def _row(**kwargs):
    r = MagicMock()
    r.__getitem__ = lambda s, k: kwargs[k]
    for k, v in kwargs.items():
        setattr(r, k, v)
    r.keys = lambda: kwargs.keys()
    # suporta dict()
    r._mapping = kwargs
    return r


def _dict_row(**kwargs):
    """Retorna um objeto que se comporta como mapping."""
    class FakeRow(dict):
        pass
    return FakeRow(kwargs)


# ---------------------------------------------------------------------------
# /gerencial/indicadores
# ---------------------------------------------------------------------------

def test_indicadores_gd_no_escopo():
    indicador = _dict_row(
        gd_matricula=GD_MAT, gd_nome=GD_NOME, ciclo_referencia=CICLO,
        total_gerado=10, total_pendente=4, total_aplicado=3,
        total_desconsiderado=2, total_expirado=1, taxa_aceite_pct=30.0,
    )
    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        conn = _make_conn({"gd_email": _dict_row(**_GD_ROW), "ciclo_referencia": [indicador]})
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get("/gerencial/indicadores", params={"gd_email": GD_EMAIL, "ciclo": CICLO})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_indicadores_gd_nao_encontrado():
    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        conn = _make_conn({"gd_email": None})
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get("/gerencial/indicadores", params={"gd_email": "nao@existe.com", "ciclo": CICLO})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /gerencial/propagandistas
# ---------------------------------------------------------------------------

def test_lista_propagandistas_no_escopo():
    rep = _dict_row(
        rep_matricula=REP_MAT, rep_nome="Ana Silva", setor="SP_INTERIOR",
        cod_linha="CARDIO", total_pendente=3, total_aplicado=1, total_desconsiderado=0,
    )
    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        conn = _make_conn({"gd_email": _dict_row(**_GD_ROW), "rep_matricula": [rep]})
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get("/gerencial/propagandistas", params={"gd_email": GD_EMAIL, "ciclo": CICLO})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# /gerencial/recomendacoes
# ---------------------------------------------------------------------------

def test_recomendacoes_gerencial_no_escopo():
    rec = _dict_row(
        id_recomendacao=str(uuid.uuid4()),
        rep_matricula=REP_MAT, rep_nome="Ana Silva",
        ufcrm="SP00001", nome_medico="Dr. Teste",
        tipo_recomendacao="ENTRADA_PAINEL", status_recomendacao="PENDENTE",
        posicao_ranking=42, soma_pontuacao=900.0,
        motivo_revisao=None, justificativa_texto="Recomendação teste.",
        motivo_desconsideracao=None,
        ciclo_referencia=CICLO, data_geracao=datetime.utcnow().isoformat(),
        qtd_vezes_recomendado=1,
    )
    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        conn = _make_conn({
            "gd_email": _dict_row(**_GD_ROW),
            "gd_matricula = :gd AND rep_matricula = :rep": 1,
            "rec.rep_matricula": [rec],
        })
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get(
            "/gerencial/recomendacoes",
            params={"gd_email": GD_EMAIL, "matricula": REP_MAT, "ciclo": CICLO},
        )
    assert resp.status_code == 200


def test_recomendacoes_gerencial_fora_do_escopo():
    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        conn = _make_conn({
            "gd_email": _dict_row(**_GD_ROW),
            "gd_matricula = :gd AND rep_matricula = :rep": None,
        })
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get(
            "/gerencial/recomendacoes",
            params={"gd_email": GD_EMAIL, "matricula": "REP999", "ciclo": CICLO},
        )
    assert resp.status_code == 403


def test_recomendacoes_filtro_tipo():
    """Filtro por tipo_recomendacao deve ser aceito sem erro."""
    with patch("backend.app.routers.gerencial._engine") as mock_eng:
        conn = _make_conn({
            "gd_email": _dict_row(**_GD_ROW),
            "gd_matricula = :gd AND rep_matricula = :rep": 1,
            "rec.rep_matricula": [],
        })
        mock_eng.return_value.connect.return_value = conn
        resp = CLIENT.get(
            "/gerencial/recomendacoes",
            params={"gd_email": GD_EMAIL, "matricula": REP_MAT, "ciclo": CICLO, "tipo": "REVISAO_PAINEL"},
        )
    assert resp.status_code == 200
    assert resp.json() == []
