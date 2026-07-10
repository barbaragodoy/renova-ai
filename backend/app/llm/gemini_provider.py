import asyncio
import google.generativeai as genai

from backend.app.llm.adapter import LLMAdapter, LLMTimeoutError, LLMError, LLMEmptyResponseError


class GeminiProvider(LLMAdapter):
    def __init__(self, settings):
        genai.configure(api_key=settings.google_api_key)
        self._model = genai.GenerativeModel("gemini-1.5-pro")
        self._timeout = settings.llm_timeout_seconds

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._model.generate_content, full_prompt),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise LLMTimeoutError("Gemini não respondeu no tempo limite.")
        except Exception as exc:
            raise LLMError(f"Erro na API Gemini: {exc}") from exc

        text = response.text if hasattr(response, "text") else ""
        if not text or not text.strip():
            raise LLMEmptyResponseError("Gemini retornou resposta vazia.")
        return text
