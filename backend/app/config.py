from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Banco
    database_url: str = "postgresql://renovai:renovai@localhost:5432/renovai"

    # Fonte de dados ativa (valores possíveis: local | databricks). Ver
    # backend/app/db/databricks_connection.py — resolver_contexto() e
    # demais consumidores não sabem qual fonte está por trás da engine.
    data_source: str = "local"

    # Databricks — OAuth M2M via Service Principal (client_credentials).
    # NUNCA usar PAT. Preenchidos apenas quando data_source=databricks.
    databricks_server_hostname: str = ""
    databricks_http_path: str = ""
    databricks_client_id: str = ""
    databricks_client_secret: str = ""
    databricks_catalog: str = "acheinfo_dev"
    databricks_schema: str = "renovai"

    # LLM
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    groq_api_key: str = ""
    llm_timeout_seconds: int = 30

    # Auth0
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_algorithms: str = "RS256"

    # Autenticação JWT (Entra ID/Auth0). Flag de dev: false aceita e-mail cru
    # via query/body (fluxo atual, sem token) — true exige Bearer token válido.
    # auth_email_claim é a claim do token usada como e-mail: ainda não
    # confirmada com Flávio (preferred_username vs upn) — configurável para
    # trocar via .env sem alterar código quando a resposta chegar.
    auth_require_jwt: bool = False
    auth_email_claim: str = "preferred_username"

    # Domínios de e-mail aceitos para autenticação/resolução de contexto.
    # Confirmado por George (PM Simbiox): ache.com.br e biosintetica.com.br
    # são empresas do mesmo grupo econômico e ambas fazem parte do escopo.
    # Lista configurável via env (nunca hardcoded) para suportar um novo
    # domínio no futuro sem alteração de código. Hoje NÃO é usada como filtro
    # ativo em resolver_contexto() — ver comentário em auth/context.py sobre
    # por que o match direto contra tb_propagandistas já é suficiente.
    dominios_email_aceitos: str = "ache.com.br,biosintetica.com.br"

    # App
    app_env: str = "local"
    debug: bool = False

    # Negócio
    ciclo_referencia: str = "202507"
    corte_ranking: int = 400
    corte_ranking_local: int = 100
    sem_visita_meses: int = 5
    limite_sugestoes: int = 5

    @property
    def lista_dominios_email_aceitos(self) -> List[str]:
        """Parseia DOMINIOS_EMAIL_ACEITOS em lista, ignorando espaços/itens vazios."""
        return [d.strip().lower() for d in self.dominios_email_aceitos.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
