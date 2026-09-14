"""Testes do estado órfão da foto de perfil.

O caso real: FOTO_PATH gravado na tb_perfil_portal apontando para arquivo que
já não existe no volume. Visto em homologação em 01/09/2026 como NotFound do
SDK virando erro 502 na tela. O contrato correto: se a raiz do volume existe,
é "sem foto" com a coluna limpa; se nem a raiz responde, é 502 de
infraestrutura. A limpeza é condicional ao caminho observado, para não apagar
uma foto gravada por um PUT concorrente.

Tudo com dublês: nem engine, nem volume, nem SDK real.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.app.auth import foto as modulo


class _NotFoundFalso(Exception):
    """Papel da databricks.sdk.errors.NotFound, sem exigir o SDK no teste."""


CAMINHO = "/Volumes/x/fotos-perfil/1.jpg"
DT_OBSERVADA = "2026-09-01 10:00:00"


def _engine_com_caminho(caminho):
    conexao = MagicMock()
    conexao.__enter__ = MagicMock(return_value=conexao)
    conexao.__exit__ = MagicMock(return_value=False)
    resultado = MagicMock()
    resultado.mappings.return_value.fetchone.return_value = (
        {"foto_path": caminho, "dt_atualizacao": DT_OBSERVADA}
        if caminho is not None else None
    )
    conexao.execute.return_value = resultado
    engine = MagicMock()
    engine.connect.return_value = conexao
    return engine


def _cliente_sem_arquivo(raiz_existe=True):
    cliente = MagicMock()
    cliente.files.download.side_effect = _NotFoundFalso("arquivo sumiu")
    if raiz_existe:
        cliente.files.get_directory_metadata.return_value = {}
    else:
        cliente.files.get_directory_metadata.side_effect = _NotFoundFalso("raiz sumiu")
    return cliente


def _cenario(cliente, caminho=CAMINHO, limpar=None):
    patches = [
        patch.object(modulo, "get_engine", return_value=_engine_com_caminho(caminho)),
        patch.object(modulo, "_cliente", return_value=cliente),
        patch.object(modulo, "_nao_encontrado_no_volume", return_value=_NotFoundFalso),
        patch.object(modulo, "resolver_email_autenticado",
                     return_value="antonio.vaz@ache.com.br"),
    ]
    if limpar is not None:
        patches.append(patch.object(modulo, "_limpar_caminho_orfao", limpar))
    return patches


def _executar(patches):
    for p in patches:
        p.start()
    try:
        with pytest.raises(HTTPException) as erro:
            modulo.obter_foto(email=None, authorization="Bearer x")
        return erro.value
    finally:
        for p in patches:
            p.stop()


def test_foto_orfa_devolve_404_e_limpa_condicionado_ao_caminho():
    limpar = MagicMock()
    erro = _executar(_cenario(_cliente_sem_arquivo(raiz_existe=True), limpar=limpar))
    assert erro.status_code == 404
    assert "Sem foto" in erro.detail
    # a limpeza recebe o caminho observado, e não anula às cegas: é o guarda
    # contra apagar uma foto gravada por um PUT concorrente
    limpar.assert_called_once_with("antonio.vaz@ache.com.br", CAMINHO, DT_OBSERVADA)


def test_raiz_do_volume_ausente_e_infraestrutura_e_vira_502():
    """NotFound com a raiz fora do ar não é órfão: nada é limpo e a resposta
    preserva o contrato de falha de infraestrutura."""
    limpar = MagicMock()
    erro = _executar(_cenario(_cliente_sem_arquivo(raiz_existe=False), limpar=limpar))
    assert erro.status_code == 502
    limpar.assert_not_called()


def test_falha_da_limpeza_nao_muda_a_resposta():
    limpar = MagicMock(side_effect=RuntimeError("sem banco"))
    erro = _executar(_cenario(_cliente_sem_arquivo(raiz_existe=True), limpar=limpar))
    assert erro.status_code == 404


def test_outra_falha_do_volume_continua_502():
    cliente = MagicMock()
    cliente.files.download.side_effect = RuntimeError("timeout")
    limpar = MagicMock()
    erro = _executar(_cenario(cliente, limpar=limpar))
    assert erro.status_code == 502
    limpar.assert_not_called()


def test_sem_caminho_gravado_nao_toca_o_volume():
    with patch.object(modulo, "get_engine", return_value=_engine_com_caminho(None)), \
         patch.object(modulo, "_cliente") as cliente, \
         patch.object(modulo, "resolver_email_autenticado",
                      return_value="antonio.vaz@ache.com.br"):
        with pytest.raises(HTTPException) as erro:
            modulo.obter_foto(email=None, authorization="Bearer x")
    assert erro.value.status_code == 404
    cliente.assert_not_called()


def test_sdk_ausente_cai_no_502_e_nao_escapa():
    """Sem o SDK, o seletor de except usa a sentinela e a falha do download
    cai no except genérico, preservando o 502. Achado da revisão de 01/09."""
    with patch.object(modulo, "get_engine", return_value=_engine_com_caminho(CAMINHO)), \
         patch.object(modulo, "_cliente", side_effect=ModuleNotFoundError("databricks")), \
         patch.object(modulo, "resolver_email_autenticado",
                      return_value="antonio.vaz@ache.com.br"):
        with pytest.raises(HTTPException) as erro:
            modulo.obter_foto(email=None, authorization="Bearer x")
    assert erro.value.status_code == 502


def test_sentinela_quando_o_import_do_sdk_falha():
    """Exercita o caminho real da sentinela: com o módulo de erros ausente do
    sys.modules, o import dentro de _nao_encontrado_no_volume falha e a
    função devolve _NuncaLevantada, que nenhum download levanta."""
    import sys
    congelados = {k: sys.modules.pop(k) for k in list(sys.modules)
                  if k == "databricks.sdk.errors" or k.startswith("databricks.sdk.errors.")}
    try:
        with patch.dict(sys.modules, {"databricks.sdk.errors": None}):
            classe = modulo._nao_encontrado_no_volume()
        assert classe is modulo._NuncaLevantada
    finally:
        sys.modules.update(congelados)


def test_limpeza_condicional_usa_update_com_guarda_do_caminho():
    """O SQL anula só quando FOTO_PATH ainda é o caminho órfão observado."""
    conexao = MagicMock()
    conexao.__enter__ = MagicMock(return_value=conexao)
    conexao.__exit__ = MagicMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = conexao
    with patch.object(modulo, "get_engine", return_value=engine):
        modulo._limpar_caminho_orfao("antonio.vaz@ache.com.br", CAMINHO, DT_OBSERVADA)
    sql = " ".join(str(conexao.execute.call_args[0][0]).split())
    parametros = conexao.execute.call_args[0][1]
    assert "SET foto_path = NULL" in sql
    assert "AND foto_path = :caminho" in sql
    # a dupla caminho + dt_atualizacao é a versão da linha: o PUT regrava o
    # mesmo caminho quando a extensão repete, e só a dt denuncia a troca
    assert "AND dt_atualizacao IS NOT DISTINCT FROM :dt" in sql
    assert parametros == {"email": "antonio.vaz@ache.com.br",
                          "caminho": CAMINHO, "dt": DT_OBSERVADA}
    conexao.commit.assert_called_once()
