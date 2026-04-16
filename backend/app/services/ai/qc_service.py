from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.medical_record_service import MedicalRecordService
from app.models.medical_record import QCIssue, AITask, RecordVersion
from app.services.rule_engine.completeness_rules import check_completeness
import json


QC_LOGIC_PROMPT = """你是病历质控专家。请对以下病历进行规范性和逻辑一致性检查。

病历内容：
{content}

请输出JSON格式的问题列表：
{{
  "issues": [
    {{
      "issue_type": "standardization",
      "risk_level": "medium",
      "field_name": "history_present_illness",
      "issue_description": "问题描述",
      "suggestion": "修改建议"
    }}
  ]
}}

issue_type: standardization（规范性）/ logic_consistency（逻辑一致性）/ insurance_risk（医保风险）
risk_level: high / medium / low
如无问题，输出 {{"issues": []}}"""


class QCService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.record_service = MedicalRecordService(db)

    async def scan(self, record_id: str):
        record = await self.record_service.get_by_id(record_id)

        # 获取当前版本内容
        result = await self.db.execute(
            select(RecordVersion)
            .where(RecordVersion.medical_record_id == record_id)
            .where(RecordVersion.version_no == record.current_version)
        )
        version = result.scalar_one_or_none()
        content = version.content if version else {}

        # 创建AI任务记录
        task = AITask(
            medical_record_id=record_id,
            task_type="qc_scan",
            status="running",
            input_snapshot=content,
        )
        self.db.add(task)
        await self.db.flush()

        all_issues = []

        # 规则引擎：完整性检查
        rule_issues = await check_completeness(record_text=str(content), db=self.db)
        for issue_data in rule_issues:
            issue = QCIssue(
                ai_task_id=task.id,
                medical_record_id=record_id,
                record_version_no=record.current_version,
                source="rule",
                **issue_data,
            )
            self.db.add(issue)
            all_issues.append(issue_data)

        # LLM：规范性和逻辑一致性检查
        try:
            content_str = json.dumps(content, ensure_ascii=False)
            prompt = QC_LOGIC_PROMPT.format(content=content_str)
            opts = await get_model_options(self.db, "qc")
            llm_result = await llm_client.chat_json_stream(
                [{"role": "user", "content": prompt}],
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            for issue_data in llm_result.get("issues", []):
                issue = QCIssue(
                    ai_task_id=task.id,
                    medical_record_id=record_id,
                    record_version_no=record.current_version,
                    source="llm",
                    **issue_data,
                )
                self.db.add(issue)
                all_issues.append(issue_data)
            task.status = "success"
        except Exception as e:
            task.error_message = str(e)
            task.status = "failed"

        record.status = "qc_done"
        await self.db.commit()

        high = sum(1 for i in all_issues if i.get("risk_level") == "high")
        medium = sum(1 for i in all_issues if i.get("risk_level") == "medium")
        low = sum(1 for i in all_issues if i.get("risk_level") == "low")

        return {
            "code": 0,
            "data": {
                "task_id": task.id,
                "summary": {"high_count": high, "medium_count": medium, "low_count": low},
                "issues": all_issues,
            },
        }
