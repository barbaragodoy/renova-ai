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
        connect_args={
            "server_hostname": settings.databricks_server_hostname,
            "http_path": settings.databricks_http_path,
            "catalog": settings.databricks_catalog,
            "schema": settings.databricks_schema,
            "credentials_provider": _oauth_credentials_provider(settings),
        },
    )


def _build_local_engine(settings: "Settings") -> Engine:
    return create_engine(settings.database_url)


def get_engine(settings: "Settings | None" = None) -> Engine:
    if settings is None:
        from backend.app.config import get_settings

        settings = get_settings()

    if settings.data_source.lower() == "databricks":
        return _build_databricks_engine(settings)
    return _build_local_engine(settings)
