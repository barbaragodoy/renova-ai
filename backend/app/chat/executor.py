"""Ponte entre o `perfil_medico` e a conexão Databricks do portal.

O módulo da resposta nasceu num backend próprio, que falava com o Databricks
pela SQL Statement Execution API. Aqui ele passa a usar a engine SQLAlchemy que
o portal já mantém, a mesma do login e das recomendações, sem abrir conexão
nova nem duplicar credencial.

A interface é de propósito mínima, só `query(sql, params)`, para o módulo
continuar testável com um executor falso e para trocar a origem de dados um dia
sem tocar em uma linha de texto da resposta.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.app.db.databricks_connection import get_engine


def _chaves_nos_dois_casos(linha: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta a versão maiúscula de cada chave, sem remover a original.

    Os objetos reais no Databricks não têm uma convenção só: tabelas mais
    antigas (tb_perfil_medico_setor, tb_ranking_medicos_validacao,
    tb_dim_medicos) têm coluna maiúscula, e as mais novas (tb_conduta_medico,
    tb_segmentacao_medico, tb_agente_persona, vw_segmentacao_efetiva) têm
    coluna minúscula — confirmado via DESCRIBE real em 26/08/2026. O código
    deste módulo (chat/perfil_medico.py, agente/ferramentas.py,
    routers/agente.py) lê cada um pela convenção real dele, misturando
    `linha["UFCRM"]` e `linha.get("perfil_efetivo")` no mesmo arquivo.

    Contra o Postgres local, identificador sem aspas sempre volta em
    minúsculo, não importa a caixa usada ao criar a tabela ou ao escrever a
    query (`v.UFCRM` também volta `ufcrm`) — confirmado em teste de fumaça
    real. Sem isto, todo acesso por `["MAIUSCULO"]` quebrava com KeyError
    contra o Postgres. Acrescentar a chave maiúscula (sem remover a
    minúscula original) resolve as duas convenções nas duas fontes: no
    Databricks já-maiúsculo isso é só uma cópia inofensiva, e onde a chave
    real já é minúscula (`perfil_efetivo` etc.) o acesso minúsculo original
    continua intacto."""
    for chave, valor in list(linha.items()):
        maiuscula = chave.upper()
        if maiuscula not in linha:
            linha[maiuscula] = valor
    return linha


class ExecutorDoPortal:
    """Executa SELECT parametrizado e devolve a lista de linhas como dicts.

    Somente leitura. A entrada do propagandista nunca é concatenada no texto
    do SQL: vai sempre por parâmetro nomeado.
    """

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with get_engine().connect() as conn:
            linhas = conn.execute(text(sql), params or {}).mappings().all()
        return [_chaves_nos_dois_casos(dict(linha)) for linha in linhas]


_executor: ExecutorDoPortal | None = None


def get_executor() -> ExecutorDoPortal:
    """Instância única, criada na primeira chamada.

    A engine por trás já tem cache próprio, então isto aqui só evita recriar o
    invólucro a cada requisição.
    """
    global _executor
    if _executor is None:
        _executor = ExecutorDoPortal()
    return _executor
