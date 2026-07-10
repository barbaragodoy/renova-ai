from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.config import Settings


class LLMTimeoutError(Exception):
    """Mapeado para GENIE_TIMEOUT."""


class LLMError(Exception):
    """Mapeado para GENIE_ERROR."""


class LLMEmptyResponseError(Exception):
    """Mapeado para EMPTY_RESPONSE."""


class LLMAdapter(ABC):
    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Envia system + user prompt e retorna a resposta em texto."""


def get_llm_provider(settings: "Settings | None" = None) -> LLMAdapter:
    from backend.app.config import get_settings
    from backend.app.llm.claude_provider import ClaudeProvider
    from backend.app.llm.openai_provider import OpenAIProvider
    from backend.app.llm.gemini_provider import GeminiProvider

    if settings is None:
        settings = get_settings()

    provider = settings.llm_provider.lower()
    if provider == "claude":
        return ClaudeProvider(settings)
    if provider == "openai":
        return OpenAIProvider(settings)
    if provider == "gemini":
        return GeminiProvider(settings)
    raise ValueError(f"LLM_PROVIDER inválido: '{provider}'. Use claude, openai ou gemini.")
