"""
Fixtures compartilhadas entre os testes locais/mockados.
"""
import pytest

from backend.app.config import get_settings


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
    monkeypatch.setenv("DATA_SOURCE", "local")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
