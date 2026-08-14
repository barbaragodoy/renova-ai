"""
Testes de registrar_envio_recomendacoes() (backend/app/services/registro_envio.py)
— registro de envio de recomendações do piloto (Sprint 5). Ainda não é
endpoint FastAPI, então os testes chamam a função de serviço diretamente.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from backend.app.schemas.envio_recomendacoes import EnvioRecomendacaoItem, RegistrarEnvioRequest
from backend.app.services.registro_envio import registrar_envio_recomendacoes

# Testes de integração precisam do Postgres local independente do que
# estiver em .env (pode estar em 'databricks') — mesmo padrão do resto do
# projeto (ver test_recomendacoes.py, test_desconsiderar.py).
pytestmark = pytest.mark.usefixtures("forcar_data_source_local")


def _item(**overrides):
    base = {"id_recomendacao": str(uuid.uuid4()), "tipo_recomendacao": "ENTRADA_PAINEL", "ciclo_recomendacao": "202507"}
    base.update(overrides)
    return EnvioRecomendacaoItem(**base)


def _mock_engine(captured):
    """Mocka _engine() capturando os params de cada INSERT executado."""
    mock_eng = MagicMock()
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    def _exec(query, params=None):
        captured.append(params)
        return MagicMock()

    conn.execute.side_effect = _exec
    mock_eng.return_value.connect.return_value = conn
    return mock_eng


# ---------------------------------------------------------------------------
# Validação do contrato (Pydantic) — mockado, sem DB
# ---------------------------------------------------------------------------

def test_grupo_controle_exige_canal_nenhum():
    with pytest.raises(ValidationError):
        RegistrarEnvioRequest(
            rep_matricula="REP001", grupo_piloto="CONTROLE", canal_envio="WHATSAPP",
            recomendacoes=[_item()],
        )


def test_grupo_whatsapp_exige_canal_whatsapp():
    with pytest.raises(ValidationError):
        RegistrarEnvioRequest(
            rep_matricula="REP001", grupo_piloto="WHATSAPP", canal_envio="EMAIL",
            recomendacoes=[_item()],
        )


def test_grupo_email_exige_canal_email():
    with pytest.raises(ValidationError):
        RegistrarEnvioRequest(
            rep_matricula="REP001", grupo_piloto="EMAIL", canal_envio="NENHUM",
            recomendacoes=[_item()],
        )


def test_grupo_canal_consistentes_aceita_as_tres_combinacoes_validas():
    for grupo, canal in [("WHATSAPP", "WHATSAPP"), ("EMAIL", "EMAIL"), ("CONTROLE", "NENHUM")]:
        req = RegistrarEnvioRequest(
            rep_matricula="REP001", grupo_piloto=grupo, canal_envio=canal, recomendacoes=[_item()]
        )
        assert req.grupo_piloto == grupo
        assert req.canal_envio == canal


def test_grupo_piloto_fora_da_lista_literal_rejeitado():
    with pytest.raises(ValidationError):
        RegistrarEnvioRequest(
            rep_matricula="REP001", grupo_piloto="SMS", canal_envio="NENHUM", recomendacoes=[_item()]
        )


def test_canal_envio_fora_da_lista_literal_rejeitado():
    with pytest.raises(ValidationError):
        RegistrarEnvioRequest(
            rep_matricula="REP001", grupo_piloto="WHATSAPP", canal_envio="SMS", recomendacoes=[_item()]
        )


def test_recomendacoes_exige_pelo_menos_1_item():
    with pytest.raises(ValidationError):
        RegistrarEnvioRequest(
            rep_matricula="REP001", grupo_piloto="CONTROLE", canal_envio="NENHUM", recomendacoes=[]
        )


def test_contrato_nao_tem_id_envio_nem_data_hora_envio():
    campos = RegistrarEnvioRequest.model_fields
    assert "id_envio" not in campos
    assert "data_hora_envio" not in campos


# ---------------------------------------------------------------------------
# Comportamento do serviço — mockado (engine)
# ---------------------------------------------------------------------------

def test_id_envio_agrupa_todas_recomendacoes_da_mesma_chamada():
    captured = []
    req = RegistrarEnvioRequest(
        rep_matricula="REP001", grupo_piloto="WHATSAPP", canal_envio="WHATSAPP",
        recomendacoes=[_item(), _item(), _item()],
    )
    with patch("backend.app.services.registro_envio._engine", _mock_engine(captured)):
        resp = registrar_envio_recomendacoes(req)

    assert len(captured) == 3
    ids_envio_usados = {p["id_envio"] for p in captured}
    assert ids_envio_usados == {resp.id_envio}
    assert uuid.UUID(resp.id_envio)  # é um UUID válido
    assert resp.quantidade_recomendacoes_registradas == 3


def test_data_hora_envio_gerada_pelo_backend_para_todas_as_linhas():
    captured = []
    req = RegistrarEnvioRequest(
        rep_matricula="REP001", grupo_piloto="EMAIL", canal_envio="EMAIL",
        recomendacoes=[_item(), _item()],
    )
    antes = datetime.now(timezone.utc)
    with patch("backend.app.services.registro_envio._engine", _mock_engine(captured)):
        resp = registrar_envio_recomendacoes(req)
    depois = datetime.now(timezone.utc)

    datas_usadas = {p["data_hora_envio"] for p in captured}
    assert len(datas_usadas) == 1  # mesma data para as duas linhas
    (data_gravada,) = datas_usadas
    assert antes <= data_gravada <= depois
    assert resp.data_hora_envio == data_gravada.isoformat()


def test_grupo_canal_rep_matricula_persistidos_corretamente_nos_tres_grupos():
    for grupo, canal in [("WHATSAPP", "WHATSAPP"), ("EMAIL", "EMAIL"), ("CONTROLE", "NENHUM")]:
        captured = []
        req = RegistrarEnvioRequest(
            rep_matricula="REP007", grupo_piloto=grupo, canal_envio=canal, recomendacoes=[_item()]
        )
        with patch("backend.app.services.registro_envio._engine", _mock_engine(captured)):
            registrar_envio_recomendacoes(req)
        assert captured[0]["grupo_piloto"] == grupo
        assert captured[0]["canal_envio"] == canal
        assert captured[0]["rep_matricula"] == "REP007"


# ---------------------------------------------------------------------------
# Integração real (Postgres local)
# ---------------------------------------------------------------------------

def _ids_reais(rep_matricula: str, qtd: int):
    """Busca id_recomendacao/tipo/ciclo reais já existentes em
    tb_recomendacoes_painel, evitando os UUIDs fixos de teste de
    desconsiderar (prefixo '10000000-')."""
    from backend.app.db.databricks_connection import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id_recomendacao, tipo_recomendacao, ciclo_referencia
                FROM tb_recomendacoes_painel
                WHERE rep_matricula = :mat AND id_recomendacao::text NOT LIKE '10000000%'
                ORDER BY id_recomendacao
                LIMIT :qtd
                """
            ),
            {"mat": rep_matricula, "qtd": qtd},
        ).fetchall()
    assert len(rows) >= qtd, f"Massa local insuficiente: esperava >= {qtd} recomendações reais para {rep_matricula}."
    return [
        EnvioRecomendacaoItem(
            id_recomendacao=str(r.id_recomendacao), tipo_recomendacao=r.tipo_recomendacao, ciclo_recomendacao=r.ciclo_referencia
        )
        for r in rows
    ]


def test_tabela_existe_e_aceita_insercao_real():
    itens = _ids_reais("REP005", 1)
    req = RegistrarEnvioRequest(
        rep_matricula="REP005", grupo_piloto="WHATSAPP", canal_envio="WHATSAPP", recomendacoes=itens
    )
    resp = registrar_envio_recomendacoes(req)
    assert resp.success is True

    from backend.app.db.databricks_connection import get_engine

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) AS total FROM tb_envios_recomendacoes_piloto WHERE id_envio = :id"),
            {"id": resp.id_envio},
        ).fetchone()
    assert row.total == 1


def test_multiplas_recomendacoes_recuperaveis_como_grupo_via_group_by():
    itens = _ids_reais("REP006", 3)
    req = RegistrarEnvioRequest(
        rep_matricula="REP006", grupo_piloto="EMAIL", canal_envio="EMAIL", recomendacoes=itens
    )
    resp = registrar_envio_recomendacoes(req)

    from backend.app.db.databricks_connection import get_engine

    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT COUNT(*) AS total, COUNT(DISTINCT rep_matricula) AS reps
                FROM tb_envios_recomendacoes_piloto
                WHERE id_envio = :id
                GROUP BY id_envio
                """
            ),
            {"id": resp.id_envio},
        ).fetchone()
    assert row.total == 3
    assert row.reps == 1


def test_registro_permanece_apos_insercao_sem_soft_delete():
    """Histórico permanente: sem coluna de soft-delete/expiração, e o
    registro continua visível numa query normal após a inserção."""
    from backend.app.db.databricks_connection import get_engine

    engine = get_engine()

    with engine.connect() as conn:
        colunas = {
            r.column_name
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tb_envios_recomendacoes_piloto'"
                )
            ).fetchall()
        }
    assert not colunas & {"ativo", "deletado", "excluido", "data_expiracao", "soft_deleted"}

    itens = _ids_reais("REP008", 1)
    req = RegistrarEnvioRequest(
        rep_matricula="REP008", grupo_piloto="CONTROLE", canal_envio="NENHUM", recomendacoes=itens
    )
    resp = registrar_envio_recomendacoes(req)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM tb_envios_recomendacoes_piloto WHERE id_envio = :id"),
            {"id": resp.id_envio},
        ).fetchone()
    assert row is not None


def test_select_distinct_grupo_piloto_retorna_exatamente_os_tres_grupos():
    """Depende dos cenários de data/scripts/12_popular_cenarios_envios_recomendacoes_piloto.sql
    (WhatsApp/E-mail/Controle) já terem sido aplicados. DISTINCT continua
    correto mesmo com outros testes deste arquivo inserindo linhas extras,
    porque o Literal do schema nunca permite um 4º valor de grupo_piloto."""
    from backend.app.db.databricks_connection import get_engine

    with get_engine().connect() as conn:
        grupos = {
            r.grupo_piloto
            for r in conn.execute(text("SELECT DISTINCT grupo_piloto FROM tb_envios_recomendacoes_piloto")).fetchall()
        }
        canais_por_grupo = {
            (r.grupo_piloto, r.canal_envio)
            for r in conn.execute(
                text("SELECT DISTINCT grupo_piloto, canal_envio FROM tb_envios_recomendacoes_piloto")
            ).fetchall()
        }
    assert grupos == {"WHATSAPP", "EMAIL", "CONTROLE"}
    assert {"WHATSAPP", "EMAIL", "CONTROLE"} <= {g for g, _ in canais_por_grupo}
    assert ("CONTROLE", "WHATSAPP") not in canais_por_grupo
    assert ("CONTROLE", "EMAIL") not in canais_por_grupo
