import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.medical_record_service import MedicalRecordService
from app.models.medical_record import RecordVersion, AITask
from app.schemas.medical_record import RecordGenerateRequest, RecordContinueRequest, RecordPolishRequest
from datetime import datetime


GENERATE_PROMPT = """你是一名专业的临床病历书写助手。根据以下问诊信息，生成标准化的{record_type}病历草稿。

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
个人史：{personal_history}
体格检查：{physical_exam}
初步印象：{initial_impression}

请输出JSON格式，包含以下字段：
{{
  "chief_complaint": "规范化主诉（症状+时间，20字以内）",
  "history_present_illness": "规范化现病史（时间顺序，书面语）",
  "past_history": "规范化既往史",
  "allergy_history": "规范化过敏史",
  "personal_history": "规范化个人史",
  "physical_exam": "规范化体格检查",
  "initial_diagnosis": "初步诊断"
}}

要求：口语转书面语，时间线清晰，符合医疗文书规范。"""

POLISH_PROMPT = """你是临床病历规范化专家。请对以下病历内容进行润色，要求：
1. 口语转书面医学语言
2. 消除重复内容
3. 优化时间顺序
4. 保持医学术语准确性

原始内容：
{content}

请输出相同JSON结构，仅改善表达，不添加虚构内容。"""


RECORD_TYPE_MAP = {
    "outpatient": "门诊",
    "admission_note": "入院记录",
    "first_course_record": "首次病程记录",
}


class RecordGenService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.record_service = MedicalRecordService(db)

    async def stream_generate(self, record_id: str, request: RecordGenerateRequest, user_id: str):
        record = await self.record_service.get_by_id(record_id, doctor_id=user_id)
        if record.status == "submitted":
            yield f"data: {json.dumps({'type': 'error', 'message': '病历已签发，不可修改'}, ensure_ascii=False)}\n\n"
            return
        inquiry = request.inquiry_input
        record_type_cn = RECORD_TYPE_MAP.get(record.record_type, "门诊")

        prompt = GENERATE_PROMPT.format(
            record_type=record_type_cn,
            chief_complaint=inquiry.get("chief_complaint", ""),
            history_present_illness=inquiry.get("history_present_illness", ""),
            past_history=inquiry.get("past_history", ""),
            allergy_history=inquiry.get("allergy_history", ""),
            personal_history=inquiry.get("personal_history", ""),
            physical_exam=inquiry.get("physical_exam", ""),
            initial_impression=inquiry.get("initial_impression", ""),
        )

        record.status = "generating"
        await self.db.commit()

        try:
            opts = await get_model_options(self.db, "generate")
            result = await llm_client.chat_json_stream(
                [{"role": "user", "content": prompt}],
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            new_version_no = record.current_version + 1
            version = RecordVersion(
                medical_record_id=record_id,
                version_no=new_version_no,
                content=result,
                source="ai_generated",
                triggered_by=user_id,
            )
            self.db.add(version)
            record.current_version = new_version_no
            record.status = "generated"
            await self.db.commit()

            for field, value in result.items():
                data = json.dumps({"type": "field_done", "field": field, "content": value}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            done_data = json.dumps({"type": "done", "version_no": new_version_no}, ensure_ascii=False)
            yield f"data: {done_data}\n\n"
        except Exception as e:
            record.status = "draft"
            await self.db.commit()
            error_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    async def stream_continue(self, record_id: str, request: RecordContinueRequest, user_id: str):
        prompt = f"""请续写以下病历中未完成的「{request.target_field}」字段内容。
已有内容：{json.dumps(request.current_content, ensure_ascii=False)}
请仅输出续写内容，不重复已有部分，保持书面医学语言。"""
        try:
            opts = await get_model_options(self.db, "generate")
            content = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            data = json.dumps({"type": "done", "field": request.target_field, "content": content}, ensure_ascii=False)
            yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    async def stream_polish(self, record_id: str, request: RecordPolishRequest, user_id: str):
        content_str = json.dumps(request.content, ensure_ascii=False)
        prompt = POLISH_PROMPT.format(content=content_str)
        try:
            opts = await get_model_options(self.db, "polish")
            result = await llm_client.chat_json_stream(
                [{"role": "user", "content": prompt}],
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            data = json.dumps({"type": "done", "content": result}, ensure_ascii=False)
            yield f"data: {data}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
