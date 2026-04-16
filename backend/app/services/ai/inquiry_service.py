"""
问诊建议服务（app/services/ai/inquiry_service.py）

供 /api/v1/encounters/{id}/inquiry-suggestions 路由调用，
通过 LLM 生成临床追问建议并以 SSE 流式推送。

注意：快捷 AI 接口（/api/v1/ai/inquiry-suggestions）由 ai_suggestions.py
路由直接调用 llm_client，不经过本服务。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import json

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.schemas.ai_suggestion import InquirySuggestionRequest
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options


INQUIRY_PROMPT = """你是一名经验丰富的临床医生助手。根据患者信息，生成追问建议。

患者信息：
- 主诉：{chief_complaint}
- 现病史：{history_present_illness}
- 科室：{department}
- 年龄：{patient_age}岁
- 性别：{patient_gender}

请输出JSON格式的追问建议列表，格式如下：
{{
  "suggestions": [
    {{
      "priority": "high",
      "is_red_flag": false,
      "category": "病程特征",
      "suggestion": "追问内容",
      "reason": "建议原因"
    }}
  ]
}}

要求：
1. priority: high（必问）/ medium（建议问）/ low（可选）
2. is_red_flag: 是否为危险信号（胸痛/呼吸困难/意识改变等）
3. 生成5-8条建议，按优先级排序
4. 危险信号必须标记为high优先级"""


class InquiryService:
    """就诊问诊建议服务，通过 LLM 生成追问问题列表。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def stream_suggestions(self, encounter_id: str, request: InquirySuggestionRequest):
        """生成追问建议并以 SSE 格式逐条推送。

        Args:
            encounter_id: 就诊记录 ID（当前用于上下文，暂不查询 DB）。
            request: 包含主诉、现病史、科室等信息的请求对象。

        Yields:
            SSE 格式字符串，事件类型：suggestion / done / error。
        """
        prompt = INQUIRY_PROMPT.format(
            chief_complaint=request.chief_complaint,
            history_present_illness=request.history_present_illness or "未提供",
            department=request.department or "未知",
            patient_age=request.patient_age or "未知",
            patient_gender=(
                "男" if request.patient_gender == "male"
                else "女" if request.patient_gender == "female"
                else "未知"
            ),
        )
        messages = [{"role": "user", "content": prompt}]

        try:
            opts = await get_model_options(self.db, "inquiry")
            result = await llm_client.chat_json_stream(
                messages,
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            for suggestion in result.get("suggestions", []):
                data = json.dumps({"type": "suggestion", **suggestion}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error_data = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
