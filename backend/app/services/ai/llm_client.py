"""
LLM 客户端封装（app/services/ai/llm_client.py）

对 OpenAI 兼容接口（DeepSeek / 其他）提供统一调用入口：
  - chat            : 单次文本请求
  - chat_json       : 请求 JSON 响应格式（response_format=json_object）
  - chat_json_stream: 流式 + JSON 合并（适合大 max_tokens，避免超时）
  - stream          : 纯文本流式生成器
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import json
from typing import Any, Optional, cast

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from openai import AsyncOpenAI

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings


class LLMClient:
    """异步 LLM 客户端，封装 DeepSeek / OpenAI 兼容接口。

    使用模块级单例 ``llm_client`` 而非直接实例化。
    ``_last_usage`` 在每次调用后更新，供上层记录 token 用量。
    """

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
        """发送对话请求，返回文本响应。

        Args:
            messages: OpenAI 格式的消息列表。
            temperature: 采样温度（0 = 确定性，1 = 随机）。
            max_tokens: 最大输出 token 数。
            model_name: 覆盖默认模型；为 None 时使用 settings.deepseek_model。

        Returns:
            模型返回的文本字符串。
        """
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
        """发送对话请求，强制模型返回 JSON 对象格式。

        注意：大 max_tokens 场景优先使用 ``chat_json_stream`` 以避免单次响应超时。

        Returns:
            解析后的 JSON 字典。
        """
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
        """流式接收响应并在结束后合并解析为 JSON（大 max_tokens 场景更可靠）。

        Returns:
            解析后的 JSON 字典。
        """
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
        """流式生成文本 chunk；流结束后更新 ``_last_usage``。

        Yields:
            模型输出的文本片段（str）。
        """
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
