from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.schemas.ai_suggestion import ExamSuggestionRequest
import json


EXAM_PROMPT = """你是临床检查建议助手。根据患者信息，提供合理的检查建议。

主诉：{chief_complaint}
现病史：{history_present_illness}
初步印象：{initial_impression}
科室：{department}

请输出JSON格式：
{{
  "suggestions": [
    {{
      "category": "basic",
      "exam_name": "血常规",
      "reason": "发热患者必查，判断感染类型"
    }}
  ]
}}

category说明：basic（基础必查）/ differential（鉴别诊断）/ high_risk（高风险补充）
要求：仅做建议，不替代医生决策，输出5-8条。"""


class ExamService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_suggestions(self, encounter_id: str, request: ExamSuggestionRequest):
        prompt = EXAM_PROMPT.format(
            chief_complaint=request.chief_complaint,
            history_present_illness=request.history_present_illness or "未提供",
            initial_impression=request.initial_impression or "未提供",
            department=request.department or "未知",
        )
        try:
            opts = await get_model_options(self.db, "exam")
            result = await llm_client.chat_json_stream(
                [{"role": "user", "content": prompt}],
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            return {"code": 0, "data": {"suggestions": result.get("suggestions", [])}}
        except Exception as e:
            return {"code": 503, "message": f"AI服务异常: {str(e)}", "data": {"suggestions": []}}
