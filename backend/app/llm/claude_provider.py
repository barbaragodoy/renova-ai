import asyncio
import anthropic

from backend.app.llm.adapter import LLMAdapter, LLMTimeoutError, LLMError, LLMEmptyResponseError


class ClaudeProvider(LLMAdapter):
    def __init__(self, settings):
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._timeout = settings.llm_timeout_seconds

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call, system_prompt, user_prompt),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise LLMTimeoutError("Claude não respondeu no tempo limite.")
        except anthropic.APIError as exc:
            raise LLMError(f"Erro na API Claude: {exc}") from exc

        text = response.content[0].text if response.content else ""
        if not text.strip():
            raise LLMEmptyResponseError("Claude retornou resposta vazia.")
        return text

    def _call(self, system_prompt: str, user_prompt: str):
        return self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
