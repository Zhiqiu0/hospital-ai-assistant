"""
AI 语音路由私有辅助（ASR 转写 + meta 前缀剥离）

从 ai_voice.py 拆出（Round 5 瘦身）：仅存放非端点的辅助函数，供
ai_voice_records.py 的上传端点调用。逻辑与拆分前逐字一致，无行为改动。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import base64
import logging
from pathlib import Path

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import httpx

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings

logger = logging.getLogger(__name__)


# Qwen-Audio 偶尔会无视 prompt 输出 meta 前缀（"这段音频的原始内容是：'XXX'"），
# 即使 prompt 已经强调"直接输出"。这里做兜底剥离，覆盖常见模板。
# 关键词与 prompt 中的 negative example 对齐，保持单一信息源。
_TRANSCRIPT_META_PREFIXES = (
    "这段音频的原始内容是",
    "这段音频的原始内容为",
    "这段音频的内容是",
    "音频的原始内容是",
    "音频原始内容是",
    "原始内容是",
    "转录如下",
    "转录内容如下",
    "转录文字如下",
    "以下是转录",
    "以下是音频内容",
    "以下是音频",
    "音频内容",
    "内容为",
    "内容如下",
)


def _strip_transcript_meta(text: str) -> str:
    """剥离 Qwen-Audio 偶发的 meta 前缀与外包引号。"""
    if not text:
        return text
    s = text.strip()
    # 反复剥（极少数情况会嵌套两层："转录如下：以下是音频：'xxx'"）
    for _ in range(3):
        original = s
        for prefix in _TRANSCRIPT_META_PREFIXES:
            if s.startswith(prefix):
                s = s[len(prefix):].lstrip("：:，, 。.").strip()
                break
        # 整体被 '' / "" / "" / '' 包裹时拆掉外层引号
        if len(s) >= 2 and s[0] in "'\"‘“" and s[-1] in "'\"’”":
            s = s[1:-1].strip()
        if s == original:
            break
    return s


async def _asr_qwen_audio(audio_bytes: bytes, filename: str) -> str:
    """调用阿里云 qwen3-asr-flash 对音频执行 ASR 转写。

    选 qwen3-asr-flash 而非旧的 qwen-audio-turbo：
      - qwen-audio-turbo 是"听音频回答问题"的多模态 LLM，**不是 ASR 专用**；
        会冒"这段音频的原始内容是…"meta 输出 + 同一段话重复输出两遍
      - qwen3-asr-flash 是阿里专用 ASR 模型，接口形态相同（base64 直传），
        标点 + 不重复 + ITN 数字归一化都明显更好
      - 真实测试 3 段医疗对话的对比记录在 commit message

    Args:
        audio_bytes: 原始音频二进制内容。
        filename: 原始文件名，用于推断 MIME 类型。

    Returns:
        转写结果字符串；API 调用失败或异常时返回空字符串。
    """
    try:
        audio_b64 = base64.b64encode(audio_bytes).decode()
        suffix = Path(filename).suffix.lstrip(".") or "webm"
        mime_map = {"m4a": "mp4", "mp3": "mpeg"}
        audio_mime = f"audio/{mime_map.get(suffix, suffix)}"

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                headers={
                    "Authorization": f"Bearer {settings.aliyun_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "qwen3-asr-flash",
                    "input": {
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"audio": f"data:{audio_mime};base64,{audio_b64}"},
                                # qwen3-asr-flash 是纯 ASR，接口仍需 text 字段占位；
                                # 留空让模型只走转写不走 instruction following
                                {"text": ""},
                            ],
                        }]
                    },
                    "parameters": {
                        "asr_options": {
                            # 关闭语种识别，固定中文（医院全中文环境，省一次模型调用）
                            "enable_lid": False,
                            # 反向文本归一化：把"三十六度五"规范成"36.5°"等
                            "enable_itn": True,
                        },
                    },
                },
            )
        if resp.status_code != 200:
            logger.warning("qwen3-asr-flash 转写失败: HTTP %s — %s", resp.status_code, resp.text[:200])
            return ""
        data = resp.json()
        content = (
            data.get("output", {})
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", [])
        )
        if isinstance(content, list):
            joined = " ".join(
                item["text"] for item in content if isinstance(item, dict) and "text" in item
            ).strip()
            return _strip_transcript_meta(joined)
        if isinstance(content, str):
            return _strip_transcript_meta(content.strip())
    except Exception as exc:
        logger.warning("qwen3-asr-flash 转写异常: %s", exc)
    return ""
