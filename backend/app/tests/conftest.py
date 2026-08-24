"""Configuração comum dos testes do backend.

O segredo de sessão precisa existir antes de qualquer `get_settings()`, que é
cacheado. Como o pytest importa este arquivo antes dos módulos de teste, é aqui
que ele entra. O valor vale só neste processo e não serve para nada fora dele.
"""
import os

# O `_exigir_segredo` recusa menos de 32 caracteres, e está certo em recusar.
os.environ.setdefault(
    "SESSAO_JWT_SECRET", "segredo-apenas-de-teste-nao-usar-fora-do-pytest"
)


import pytest
from sqlalchemy import text

MARCADOR = "requer_banco"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"{MARCADOR}: precisa do PostgreSQL local no ar. Pula sozinho quando não está.",
    )


def _banco_local_no_ar() -> bool:
    """Uma tentativa de conexão ao Postgres LOCAL, no começo da sessão.

    Testa direto via `create_engine(settings.database_url)`, desacoplado de
    `DATA_SOURCE` — se o `.env` estiver com `DATA_SOURCE=databricks` (comum
    neste projeto, para rodar os testes de integração real contra o
    Databricks de verdade), `get_engine()` resolveria para o Databricks, não
    para o Postgres local, e esta checagem reportaria "banco no ar" mesmo com
    o Postgres local desligado — mascarando exatamente o problema que este
    mecanismo existe para evitar. Mesmo alvo que a fixture
    `forcar_data_source_local` abaixo usa.

    Sem isto, quem clona o repositório e roda a suíte vê onze falhas vermelhas
    que não são defeito nenhum, só ausência de um serviço externo. Falha por
    dependência que não está no ar é ruído; falha por contrato quebrado é sinal.
    """
    try:
        from sqlalchemy import create_engine

        from backend.app.config import get_settings

        engine = create_engine(get_settings().database_url)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            engine.dispose()
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if _banco_local_no_ar():
        return
    pular = pytest.mark.skip(
        reason="PostgreSQL local indisponível. Suba o container e rode de novo."
    )
    for item in items:
        if MARCADOR in item.keywords:
            item.add_marker(pular)


@pytest.fixture
def forcar_data_source_local(monkeypatch):
    """
    Força DATA_SOURCE=local para a duração do teste, independente do que
    estiver no .env real (que pode estar em 'databricks' para rodar os
    testes de integração real contra o Databricks de verdade — ver
    test_context_integration.py e test_recomendacoes_integration.py).

    Uso: nos módulos que testam contra a seed do Postgres local, declarar

        pytestmark = pytest.mark.usefixtures("forcar_data_source_local")

    no topo do arquivo. Propositalmente NÃO é autouse aqui no conftest —
    isso vazaria a força para os arquivos de integração real, que precisam
    do DATA_SOURCE de verdade configurado no .env.
    """
    from backend.app.config import get_settings

    monkeypatch.setenv("DATA_SOURCE", "local")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
