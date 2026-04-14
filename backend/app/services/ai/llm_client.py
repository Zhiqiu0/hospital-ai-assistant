from openai import AsyncOpenAI
from app.config import settings
import json
from typing import Any, Optional, cast


class LLMClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=270.0,
            max_retries=2,
        )
        self.model = settings.deepseek_model
        self._last_usage: Optional[Any] = None

    async def chat(
        self,
        messages: list,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model_name: Optional[str] = None,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=model_name or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._last_usage = response.usage
        return cast(str, response.choices[0].message.content or "")

    async def chat_json(
        self,
        messages: list,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model_name: Optional[str] = None,
    ) -> dict:
        response = await self.client.chat.completions.create(
            model=model_name or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        self._last_usage = response.usage
        content = cast(str, response.choices[0].message.content or "{}")
        return json.loads(content)

    async def chat_json_stream(
        self,
        messages: list,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model_name: Optional[str] = None,
    ) -> dict:
        """Stream the response and parse JSON at the end. More reliable for large max_tokens."""
        self._last_usage = None
        stream = await self.client.chat.completions.create(
            model=model_name or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            stream=True,
            stream_options={"include_usage": True},
        )
        chunks = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
            if chunk.usage:
                self._last_usage = chunk.usage
        content = "".join(chunks) or "{}"
        return json.loads(content)

    async def stream(
        self,
        messages: list,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model_name: Optional[str] = None,
    ):
        """Yields text chunks; sets self._last_usage after the stream ends."""
        self._last_usage = None
        stream = await self.client.chat.completions.create(
            model=model_name or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if chunk.usage:
                self._last_usage = chunk.usage


llm_client = LLMClient()
