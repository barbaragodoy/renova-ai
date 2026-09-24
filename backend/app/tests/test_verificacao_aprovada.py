"""Regressão do campo `verificacao_aprovada` de tb_agente_log.

Até 17/09/2026 o campo era calculado só sobre `itens`, a lista de números que
têm origem confirmada em ferramenta. Como `composicao.py` só coloca ali números
aprovados, e sempre com `"confere": True`, a expressão era incapaz de devolver
falso. Os números inventados ficam numa lista separada, `numeros_sem_origem`,
que nunca chegava à função.

Efeito medido na produção: 102 de 102 interações entre 20/08 e 16/09/2026 com
`verificacao_aprovada = true`, incluindo cinco em que a resposta foi degradada
por números sem origem. Uma delas escreveu uma lista inteira de percentuais
inventados.

Os testes abaixo reproduzem esse cenário exato.
"""
from types import SimpleNamespace

import pytest

from backend.app.agente import contrato_log
from backend.app.agente.contrato_log import ContratoInvalido, verificacao_aprovada


def _item(numero: str, confere: bool = True) -> dict:
    return {
        "numero": numero,
        "ferramenta": "painel",
        "chamada_id": "c1",
        "campo": "share",
        "resultado_hash": "abc123",
        "confere": confere,
    }


def _veredito(aprovado: bool, sem_origem=(), proibidas=()):
    return SimpleNamespace(
        aprovado=aprovado,
        numeros_sem_origem=list(sem_origem),
        palavras_proibidas=list(proibidas),
    )


def test_resposta_limpa_e_aprovada():
    itens = [_item("15,2"), _item("78")]
    assert verificacao_aprovada(itens, _veredito(True)) is True


def test_sem_numero_nenhum_segue_aprovada():
    """Resposta de texto puro não tem o que conferir; 56% do log é assim."""
    assert verificacao_aprovada([], _veredito(True)) is True


def test_numero_inventado_reprova_mesmo_com_itens_todos_confere():
    """O caso que a versão anterior deixava passar.

    Reproduz a interação real "Qual o perfil completo da Maria Eduarda Santana":
    alguns números tinham origem, outros não, e o campo dizia aprovado.
    """
    itens = [_item("15,2")]
    veredito = _veredito(False, sem_origem=["202608", "78"])
    assert verificacao_aprovada(itens, veredito) is False


def test_lista_inteira_de_percentuais_inventados_reprova():
    """A interação "Meus produtos aparecem mais para paciente homem ou mulher"."""
    veredito = _veredito(
        False,
        sem_origem=["13,2", "16,0", "16,8", "16,9", "17,6", "19,9", "20,5", "20,8", "24,1"],
    )
    assert verificacao_aprovada([], veredito) is False


def test_palavra_proibida_reprova():
    """`composicao.aprovado` considera palavra proibida; o campo gravado passou a considerar também."""
    veredito = _veredito(False, proibidas=["mercado"])
    assert verificacao_aprovada([_item("3")], veredito) is False


def test_confere_falso_reprova_antes_de_olhar_o_veredito():
    itens = [_item("3", confere=False)]
    assert verificacao_aprovada(itens, _veredito(True)) is False


def test_confere_como_texto_continua_recusado():
    """Guarda de 19/08/2026: `"false"` é verdadeiro em Python e aprovava a verificação."""
    itens = [_item("3")]
    itens[0]["confere"] = "false"
    with pytest.raises(ContratoInvalido):
        verificacao_aprovada(itens, _veredito(True))


def test_veredito_ausente_e_erro_e_nao_aprovacao():
    """Sem veredito não há o que afirmar. Devolver True reintroduziria o defeito."""
    with pytest.raises(ContratoInvalido):
        verificacao_aprovada([_item("3")], None)


def test_assinatura_exige_o_veredito():
    """Chamar só com `itens` precisa falhar, e não aprovar por omissão.

    É o que torna o defeito irrepetível por esquecimento: a forma antiga de
    chamada não compila mais.
    """
    with pytest.raises(TypeError):
        contrato_log.verificacao_aprovada([_item("3")])
