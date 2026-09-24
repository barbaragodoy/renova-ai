from functools import lru_cache
from typing import List, Literal

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

    # Modo de autenticação do portal:
    #   senha    -> e-mail corporativo + senha gerada pelo time, conferida
    #               contra o hash em acessos.csv. Modo padrão.
    #   entra_id -> autenticação feita pelo Azure App Service Easy Auth.
    #               O backend confia nos headers X-MS-CLIENT-PRINCIPAL-*;
    #               AUTH_REQUIRE_JWT/AUTH_EMAIL_CLAIM não participam desse
    #               fluxo. POST /auth/login responde 404.
    auth_mode: Literal["senha", "entra_id"] = "senha"

    # Segredo de assinatura do token de sessão. Obrigatório no modo senha,
    # mínimo de 32 caracteres, injetado pelo ambiente. Em HMG e produção vem
    # do Azure Key Vault via Managed Identity, nunca do código nem de um valor
    # padrão. Sem ele, POST /auth/login devolve 503 em vez de assinar com um
    # segredo previsível.
    sessao_jwt_secret: str = ""
    sessao_token_minutos: int = 60

    # Caminho dos arquivos estáticos do frontend dentro da imagem.
    frontend_dist: str = "frontend_dist"

    # App
    app_env: str = "local"
    debug: bool = False

    # Negócio
    #
    # corte_ranking/corte_ranking_local removidos na Sprint 6: o corte fixo
    # (400 prod / 100 local) foi substituído pelo limite por propagandista
    # (LIMITE_PAINEL em tb_perfil_portal, COALESCE(..., 318) — o 318 vive só
    # como literal SQL em quem consome, não como setting Python, porque o
    # valor não é uma escolha do portal: é o mesmo que o notebook de geração
    # do Hugo aplica na fonte real). Ver routers/recomendacoes.py e
    # jobs/gerar_recomendacoes.py.
    ciclo_referencia: str = "202608"
    sem_visita_meses: int = 3
    # Até 04/09/2026 este número cortava a lista das abas de entrada e
    # exclusão, e o que passasse dele simplesmente não aparecia. Medido no
    # ciclo atual: a mediana é de 132 recomendações por pessoa e por tipo, e o
    # máximo é 629, então mais de 96% ficavam invisíveis. Por decisão de
    # George, a lista passou a mostrar todas, paginadas, e este número virou
    # quantas ficam destacadas como prioridade da semana. A origem dele é o
    # combinado antigo de 5 inclusões e 5 exclusões por semana.
    #
    # Continua cortando a geração em jobs/gerar_recomendacoes.py, que é outro
    # uso e não foi alterado.
    limite_sugestoes: int = 5

    @property
    def lista_dominios_email_aceitos(self) -> List[str]:
        """Parseia DOMINIOS_EMAIL_ACEITOS em lista, ignorando espaços/itens vazios."""
        return [d.strip().lower() for d in self.dominios_email_aceitos.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
