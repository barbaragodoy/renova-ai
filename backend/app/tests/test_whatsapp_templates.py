"""
Testes de render_template() (backend/app/integrations/whatsapp/templates.py)
— Sprint 7. Puro, sem banco nem rede.
"""
import pytest

from backend.app.integrations.whatsapp.templates import (
    TemplateNotFoundError,
    render_template,
)


def test_render_entrada_painel_com_contexto_valido():
    texto = render_template(
        "entrada_painel",
        {"nome_propagandista": "Ana", "nome_medico": "João Silva", "ciclo": "202608"},
    )
    assert "Ana" in texto
    assert "João Silva" in texto
    assert "202608" in texto


def test_render_revisao_painel_com_contexto_valido():
    texto = render_template(
        "revisao_painel",
        {
            "nome_propagandista": "Bruno",
            "nome_medico": "Maria Souza",
            "ciclo": "202608",
            "motivo_revisao": "REVISAO_SEM_VISITA_3_MESES",
        },
    )
    assert "Bruno" in texto
    assert "Maria Souza" in texto
    assert "REVISAO_SEM_VISITA_3_MESES" in texto


def test_template_inexistente_levanta_template_not_found_error():
    with pytest.raises(TemplateNotFoundError):
        render_template("inexistente", {})


def test_contexto_incompleto_levanta_key_error_em_vez_de_texto_com_variavel_literal():
    """`Template.substitute` (não `safe_substitute`) — variável faltando
    precisa quebrar alto e cedo, não virar `$variavel` literal na mensagem
    que chegaria ao propagandista."""
    with pytest.raises(KeyError):
        render_template("entrada_painel", {"nome_propagandista": "Ana"})
