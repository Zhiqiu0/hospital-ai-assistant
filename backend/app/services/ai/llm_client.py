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
from contextvars import ContextVar
from typing import Any, Optional, cast

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings


class LLMServiceError(Exception):
    """LLM 上游故障的业务化异常（2026-08-28 全量体检：欠费可识别）。

    此前 openai SDK 的原始异常一路裸奔到各端点的 except Exception，医生只能
    看到"生成失败，请重试"——把 402 欠费这种「确定性、需管理员行动」的故障
    打扮成瞬时抖动，全院会反复重试半天。这里按状态码映射成中文文案 +
    retryable 标记：重试循环据此跳过确定性失败（省钱），端点把 user_message
    透传给前端（医生一眼知道该找谁）。
    """

    def __init__(self, user_message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.retryable = retryable
        self.status_code = status_code


def _classify_llm_error(exc: Exception) -> LLMServiceError:
    """把 openai SDK 异常翻译成 LLMServiceError（映射关系单点维护）。"""
    if isinstance(exc, APIStatusError):
        code = exc.status_code
        if code == 402:
            return LLMServiceError(
                "AI 账户余额不足，请联系管理员充值后再试", retryable=False, status_code=code)
        if code in (401, 403):
            return LLMServiceError(
                "AI 服务凭证无效，请联系管理员检查配置", retryable=False, status_code=code)
        if code == 429:
            return LLMServiceError(
                "AI 服务繁忙，请稍候片刻再试", retryable=True, status_code=code)
        return LLMServiceError(
            "AI 服务方暂时故障，请稍后重试", retryable=True, status_code=code)
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return LLMServiceError("AI 服务连接超时，请重试", retryable=True)
    # 未知形态原样透传语义：可重试的通用失败
    return LLMServiceError("AI 调用失败，请重试", retryable=True)


# 每次 LLM 调用后的 token usage。用 ContextVar 而非实例属性：
# llm_client 是模块级单例，若把 usage 存实例属性，两个医生并发跑 AI 时
# A 的 usage 会被 B 的响应覆盖，导致 token 记账串号（admin 用量统计失真）。
# ContextVar 按 asyncio 任务隔离——每个请求是独立 task、各持一份上下文副本，
# 调用方 await 后在同一 task 内读回的一定是自己那次调用的 usage。
_last_usage_var: ContextVar[Optional[Any]] = ContextVar("llm_last_usage", default=None)


class LLMClient:
    """异步 LLM 客户端，封装 DeepSeek / OpenAI 兼容接口。

    使用模块级单例 ``llm_client`` 而非直接实例化。
    ``_last_usage`` 在每次调用后更新，供上层记录 token 用量（按请求隔离）。
    """

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=270.0,
            # SDK 自动重试 1 次即可：应用层（record_gen 等）另有 1 次重试，
            # 原 max_retries=2 叠加后单击最多 6 次上游调用，超时场景 6 倍计费
            # （2026-08-28 全量体检收敛）
            max_retries=1,
        )
        self.model = settings.deepseek_model

    # _last_usage 用 ContextVar 承载：读写语法与原实例属性完全一致，
    # 所有既有调用点（`llm_client._last_usage`）无需改动，但获得了按请求隔离。
    @property
    def _last_usage(self) -> Optional[Any]:
        return _last_usage_var.get()

    @_last_usage.setter
    def _last_usage(self, value: Optional[Any]) -> None:
        _last_usage_var.set(value)

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
        try:
            response = await self.client.chat.completions.create(
                model=model_name or self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # SDK 异常 → 业务化（欠费/凭证/限流可识别）
            raise _classify_llm_error(exc) from exc
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
        try:
            response = await self.client.chat.completions.create(
                model=model_name or self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise _classify_llm_error(exc) from exc
        self._last_usage = response.usage
        # 截断检测：JSON 被 max_tokens 拦腰砍断时重试同一 prompt 大概率再截断，
        # 明确报错且标记不可重试，省掉注定失败的二次计费
        if response.choices and response.choices[0].finish_reason == "length":
            raise LLMServiceError("AI 输出超长被截断，请缩短输入后重试", retryable=False)
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
        truncated = False
        try:
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
                if chunk.choices and chunk.choices[0].finish_reason == "length":
                    truncated = True
                if chunk.usage:
                    self._last_usage = chunk.usage
        except Exception as exc:
            raise _classify_llm_error(exc) from exc
        if truncated:
            raise LLMServiceError("AI 输出超长被截断，请缩短输入后重试", retryable=False)
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
        try:
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
        except Exception as exc:
            if isinstance(exc, LLMServiceError):
                raise
            raise _classify_llm_error(exc) from exc


llm_client = LLMClient()
