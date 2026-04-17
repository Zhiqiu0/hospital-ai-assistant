"""
AI 质控服务（app/services/ai/qc_service.py）

职责：
  对病历进行全面质量控制扫描，结合两种检测方式：
  1. 规则引擎（completeness_rules）：基于数据库规则表的完整性和医保风险检测，
     速度快，结果确定性高，source='rule'。
  2. LLM 大模型（DeepSeek）：检测规范性和逻辑一致性等难以用规则表达的问题，
     source='llm'。

扫描流程：
  1. 读取病历当前版本内容
  2. 创建 AITask 记录（status='running'）
  3. 规则引擎扫描 → 写入 QCIssue（source='rule'）
  4. LLM 扫描 → 写入 QCIssue（source='llm'）
  5. 更新 AITask.status 和 MedicalRecord.status='qc_done'
  6. 返回汇总统计（high/medium/low 各几条）

与 ai_qc.py 路由的分工：
  - 此服务（QCService.scan）: 传统扫描模式，单次 JSON 响应，适合后台异步触发。
  - ai_qc.py 路由：SSE 流式推送实时质控结果，适合前端实时展示。
  两套实现并存，前端目前使用 SSE 流式接口（ai_qc.py）。
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medical_record import AITask, QCIssue, RecordVersion
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.medical_record_service import MedicalRecordService
from app.services.rule_engine.completeness_rules import check_completeness


# LLM 质控 prompt：要求检查规范性和逻辑一致性（非完整性，那由规则引擎负责）
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
    """AI 质控服务：规则引擎 + LLM 双重扫描，结果写入数据库。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.record_service = MedicalRecordService(db)

    async def scan(self, record_id: str):
        """对指定病历执行完整质控扫描，返回问题汇总。

        Args:
            record_id: 目标病历 ID。

        Returns:
            {
              "code": 0,
              "data": {
                "task_id": "...",
                "summary": {"high_count": N, "medium_count": N, "low_count": N},
                "issues": [问题字典列表]
              }
            }
        """
        record = await self.record_service.get_by_id(record_id)

        # 查询病历当前版本的内容
        result = await self.db.execute(
            select(RecordVersion)
            .where(RecordVersion.medical_record_id == record_id)
            .where(RecordVersion.version_no == record.current_version)
        )
        version = result.scalar_one_or_none()
        content = version.content if version else {}

        # 创建 AI 任务记录，用于追踪本次扫描状态和 token 用量
        task = AITask(
            medical_record_id=record_id,
            task_type="qc_scan",
            status="running",
            input_snapshot=content,  # 快照当前版本内容，便于事后审计
        )
        self.db.add(task)
        await self.db.flush()  # 获取数据库生成的 task.id

        all_issues = []

        # ── 第一步：规则引擎完整性检查 ────────────────────────────────────────
        rule_issues = await check_completeness(record_text=str(content), db=self.db)
        for issue_data in rule_issues:
            issue = QCIssue(
                ai_task_id=task.id,
                medical_record_id=record_id,
                record_version_no=record.current_version,
                source="rule",   # 明确标注来源为规则引擎
                **issue_data,
            )
            self.db.add(issue)
            all_issues.append(issue_data)

        # ── 第二步：LLM 规范性和逻辑一致性检查 ──────────────────────────────
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
                    source="llm",   # 明确标注来源为大模型
                    **issue_data,
                )
                self.db.add(issue)
                all_issues.append(issue_data)
            task.status = "success"
        except Exception as e:
            # LLM 失败不回滚已保存的规则引擎结果，只记录错误信息
            task.error_message = str(e)
            task.status = "failed"

        # 病历状态更新为"已质控"，前端可据此显示质控徽标
        record.status = "qc_done"
        await self.db.commit()

        # 按风险等级统计各类问题数量
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
