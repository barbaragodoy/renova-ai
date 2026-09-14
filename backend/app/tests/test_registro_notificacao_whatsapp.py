"""
Testes de registrar_notificacao()/buscar_por_sid_twilio()
(backend/app/services/registro_notificacao_whatsapp.py) — Sprint 7.

Mesmo padrão de test_registro_envio.py: testes de integração real contra o
Postgres local, independente do que estiver em DATA_SOURCE no .env real
(pode estar em 'databricks' para os testes de integração de outras
sprints) — forçado via fixture compartilhada.
"""
import uuid

import pytest
from sqlalchemy import text

from backend.app.db.databricks_connection import get_engine
from backend.app.services.registro_notificacao_whatsapp import (
    buscar_por_sid_twilio,
    registrar_notificacao,
)

pytestmark = [pytest.mark.requer_banco, pytest.mark.usefixtures("forcar_data_source_local")]

_DESTINATARIO = "+5511900000000"


@pytest.fixture(autouse=True)
def _limpar_cenario(forcar_data_source_local):
    # Dependência explícita, não só `usefixtures` no pytestmark: garante que
    # DATA_SOURCE já está forçado para 'local' ANTES desta fixture (autouse)
    # rodar — sem isso a ordem entre duas fixtures autouse não é garantida,
    # e esta chegou a rodar contra o Databricks real do .env por acidente.
    """Remove qualquer resíduo deste destinatário antes e depois de cada
    teste — os testes deste arquivo criam linha real, e o destinatário de
    teste é dedicado (não usado em nenhum script de seed), então limpar por
    ele é seguro e não risca dado de outro teste."""
    def _limpar():
        with get_engine().connect() as conn:
            conn.execute(
                text("DELETE FROM tb_notificacoes_whatsapp WHERE destinatario = :d"),
                {"d": _DESTINATARIO},
            )
            conn.commit()

    _limpar()
    yield
    _limpar()


def test_registrar_notificacao_sem_id_cria_registro_novo():
    novo_id = registrar_notificacao(
        registro_id=None,
        destinatario=_DESTINATARIO,
        tipo_notificacao="ENTRADA_PAINEL",
        template_usado="entrada_painel",
        status="queued",
    )
    assert novo_id

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM tb_notificacoes_whatsapp WHERE id = :id"), {"id": novo_id}
        ).fetchone()
    assert row is not None
    assert row.status == "queued"
    assert row.sid_twilio is None
    assert row.atualizado_em is None


def test_registrar_notificacao_com_id_atualiza_registro_existente():
    id_existente = registrar_notificacao(
        registro_id=None,
        destinatario=_DESTINATARIO,
        tipo_notificacao="ENTRADA_PAINEL",
        template_usado="entrada_painel",
        status="queued",
    )

    id_devolvido = registrar_notificacao(
        registro_id=id_existente,
        destinatario=_DESTINATARIO,
        tipo_notificacao="ENTRADA_PAINEL",
        template_usado="entrada_painel",
        status="sent",
        sid_twilio="SMfake123",
    )
    assert id_devolvido == id_existente

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM tb_notificacoes_whatsapp WHERE id = :id"), {"id": id_existente}
        ).fetchone()
    assert row.status == "sent"
    assert row.sid_twilio == "SMfake123"
    assert row.atualizado_em is not None

    # Confirma que não duplicou linha — criar depois atualizar é 1 linha só.
    with get_engine().connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) AS n FROM tb_notificacoes_whatsapp WHERE destinatario = :d"),
            {"d": _DESTINATARIO},
        ).fetchone()
    assert total.n == 1


def test_atualizacao_com_erro_grava_o_texto_do_erro():
    id_existente = registrar_notificacao(
        registro_id=None,
        destinatario=_DESTINATARIO,
        tipo_notificacao="REVISAO_PAINEL",
        template_usado="revisao_painel",
        status="queued",
    )
    registrar_notificacao(
        registro_id=id_existente,
        destinatario=_DESTINATARIO,
        tipo_notificacao="REVISAO_PAINEL",
        template_usado="revisao_painel",
        status="failed",
        erro="63016: fora da janela de 24h",
    )

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status, erro FROM tb_notificacoes_whatsapp WHERE id = :id"),
            {"id": id_existente},
        ).fetchone()
    assert row.status == "failed"
    assert "63016" in row.erro


def test_buscar_por_sid_twilio_encontra_o_registro_certo():
    id_existente = registrar_notificacao(
        registro_id=None,
        destinatario=_DESTINATARIO,
        tipo_notificacao="ENTRADA_PAINEL",
        template_usado="entrada_painel",
        status="sent",
        sid_twilio="SMbusca999",
    )

    encontrado = buscar_por_sid_twilio("SMbusca999")
    assert encontrado is not None
    assert str(encontrado.id) == id_existente
    assert encontrado.destinatario == _DESTINATARIO


def test_buscar_por_sid_twilio_inexistente_devolve_none():
    assert buscar_por_sid_twilio(f"SM-nao-existe-{uuid.uuid4()}") is None
