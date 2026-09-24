"""
Fábrica de engine SQLAlchemy agnóstica à fonte de dados.

DATA_SOURCE=local      -> PostgreSQL local (docker compose), sem autenticação especial.
DATA_SOURCE=databricks -> Databricks SQL Warehouse real, via OAuth M2M (client_credentials)
                          do Service Principal. Nunca usa PAT (DATABRICKS_TOKEN não existe
                          mais neste fluxo — ver .env.example).

Consumidores (ex.: auth/context.py) só enxergam `get_engine()` e usam
`engine.connect()` / `conn.execute(text(...), params)` normalmente — a troca de
fonte não muda nenhuma lógica de negócio.
"""

from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from backend.app.config import Settings


def _oauth_credentials_provider(settings: "Settings"):
    from databricks.sdk.core import Config, oauth_service_principal

    cfg = Config(
        host=f"https://{settings.databricks_server_hostname}",
        client_id=settings.databricks_client_id,
        client_secret=settings.databricks_client_secret,
    )
    return lambda: oauth_service_principal(cfg)


def _build_databricks_engine(settings: "Settings") -> Engine:
    return create_engine(
        "databricks://",
        # Mesmo par que Bárbara aplicou em `APP_KANBAN_IA` no commit 2fd8169.
        # `pool_pre_ping` testa a conexão antes de entregar, descartando a que
        # o warehouse derrubou no auto-stop de 10 minutos. `pool_recycle`
        # fecha conexão com mais de 5 minutos, o que também mantém o token
        # OAuth fresco: o `credentials_provider` é consultado a cada conexão
        # nova, então reciclar renova o token sem código extra.
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "server_hostname": settings.databricks_server_hostname,
            "http_path": settings.databricks_http_path,
            "catalog": settings.databricks_catalog,
            "schema": settings.databricks_schema,
            "credentials_provider": _oauth_credentials_provider(settings),
        },
    )


def _build_local_engine(settings: "Settings") -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300)


def _chave(settings: "Settings") -> tuple:
    """Identidade da conexão, para saber se uma engine já serve.

    Só entram os campos que mudam para onde a engine aponta. O segredo do
    Service Principal fica de fora de propósito: ele não muda o destino e não
    deve circular em estrutura de cache.
    """
    if settings.data_source.lower() == "databricks":
        return (
            "databricks",
            settings.databricks_server_hostname,
            settings.databricks_http_path,
            settings.databricks_catalog,
            settings.databricks_schema,
        )
    return ("local", settings.database_url)


_engines: dict[tuple, Engine] = {}


def get_engine(settings: "Settings | None" = None) -> Engine:
    """Engine correspondente à configuração, reaproveitada entre chamadas.

    Motivo, medido em 07/08/2026 contra o warehouse real: criar a engine e
    abrir a primeira conexão custa cerca de 3,1 segundos, enquanto conectar
    por uma engine que já existe custa 0,32. O custo é o handshake OAuth mais
    a abertura Thrift, não a consulta em si.

    A aba Usuário chama `get_engine()` duas vezes por carregamento, uma no
    perfil e outra no resumo do setor, e pagava o handshake nas duas. O
    carregamento inteiro caiu de 7,30 para 1,57 segundos de média só com este
    reaproveitamento.

    Engine do SQLAlchemy é feita para ser criada uma vez e viver o processo
    inteiro, e é thread-safe. O `uvicorn` do `Dockerfile` sobe sem
    `--workers`, então não há fork depois da criação, que é o caso em que uma
    conexão herdada daria problema.

    O cache é por configuração e não um singleton cego. Um singleton devolveria
    a engine do Postgres local para quem pedisse Databricks depois de
    `DATA_SOURCE` mudar, e foi exatamente o que aconteceu na primeira versão
    desta função: `test_context.py` troca `DATA_SOURCE` para `local` durante os
    seus casos e quatro testes de integração passaram a falhar em sequência.
    Chaveando pelo destino, uma configuração nova simplesmente ganha a sua
    própria engine, sem ninguém precisar lembrar de limpar cache.
    """
    if settings is None:
        from backend.app.config import get_settings

        settings = get_settings()

    chave = _chave(settings)
    engine = _engines.get(chave)
    if engine is None:
        engine = (
            _build_databricks_engine(settings)
            if settings.data_source.lower() == "databricks"
            else _build_local_engine(settings)
        )
        _engines[chave] = engine
    return engine
