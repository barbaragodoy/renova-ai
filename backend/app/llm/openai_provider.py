import asyncio
import openai as _openai

from backend.app.llm.adapter import LLMAdapter, LLMTimeoutError, LLMError, LLMEmptyResponseError


class OpenAIProvider(LLMAdapter):
    def __init__(self, settings):
        self._client = _openai.OpenAI(api_key=settings.openai_api_key)
        self._timeout = settings.llm_timeout_seconds

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call, system_prompt, user_prompt),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise LLMTimeoutError("OpenAI não respondeu no tempo limite.")
        except _openai.OpenAIError as exc:
            raise LLMError(f"Erro na API OpenAI: {exc}") from exc

        text = response.choices[0].message.content if response.choices else ""
        if not text or not text.strip():
            raise LLMEmptyResponseError("OpenAI retornou resposta vazia.")
        return text

    def _call(self, system_prompt: str, user_prompt: str):
        return self._client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
