from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Banco
    database_url: str = "postgresql://renovai:renovai@localhost:5432/renovai"

    # LLM
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    llm_timeout_seconds: int = 30

    # Auth0
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_algorithms: str = "RS256"

    # App
    app_env: str = "local"
    debug: bool = False

    # Negócio
    ciclo_referencia: str = "202507"
    corte_ranking: int = 400
    corte_ranking_local: int = 100
    sem_visita_meses: int = 5
    limite_sugestoes: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
