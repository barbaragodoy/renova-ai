import asyncio
import openai as _openai

from backend.app.llm.adapter import LLMAdapter, LLMTimeoutError, LLMError, LLMEmptyResponseError

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(LLMAdapter):
    """Groq expõe uma API compatível com o SDK da OpenAI, apenas trocando o base_url."""

    def __init__(self, settings):
        self._client = _openai.OpenAI(api_key=settings.groq_api_key, base_url=_GROQ_BASE_URL)
        self._timeout = settings.llm_timeout_seconds

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call, system_prompt, user_prompt),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise LLMTimeoutError("Groq não respondeu no tempo limite.")
        except _openai.OpenAIError as exc:
            raise LLMError(f"Erro na API Groq: {exc}") from exc

        text = response.choices[0].message.content if response.choices else ""
        if not text or not text.strip():
            raise LLMEmptyResponseError("Groq retornou resposta vazia.")
        return text

    def _call(self, system_prompt: str, user_prompt: str):
        return self._client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
