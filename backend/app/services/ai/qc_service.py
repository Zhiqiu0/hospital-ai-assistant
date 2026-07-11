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
from app.services.qc_engine.checker import build_context
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)
from app.services.qc_engine.scorer import score as run_rubric_score


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

        all_issues: list[dict] = []   # 返回摘要用（规则 + LLM 全量 issue dict）
        rule_issues: list[dict] = []  # 规则引擎问题，推迟到 LLM 之后统一落库
        llm_issues: list[dict] = []   # LLM 问题，同上

        # ── 第一步：Rubric 评分（纯计算，不碰 DB） ────────────────────────────
        # 后台 qc_scan 也走与工作台 SSE 同一引擎，保证扫描结果与实时质控一致
        ctx = build_context(str(content), record_type=record.record_type or "outpatient")
        report = run_rubric_score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
        for ded in report.deductions:
            # 扣分值 → 风险等级（与 qc_stream_service._deductions_to_issues 同语义）
            if ded.is_veto or ded.points >= 5:
                level = "high"
            elif ded.points >= 2:
                level = "medium"
            else:
                level = "low"
            issue_data = {
                # issue_type 是 qc_issues 表的 NOT NULL 字段（admin 统计按它分组）。
                # 新引擎走 Rubric 评分，本质都是"病历该写没写/写得不规范"的完整性问题，
                # 统一归类为 "completeness"，与旧版 check_completeness 同语义。
                "issue_type": "completeness",
                "risk_level": level,
                "field_name": ded.item_name,
                "issue_description": ded.description,
                "suggestion": ded.description,
            }
            rule_issues.append(issue_data)
            all_issues.append(issue_data)

        # 模型配置（最后一次 DB 读）
        opts = await get_model_options(self.db, "qc")

        # 连接池护栏：进入最长 270s 的 LLM 之前先 commit，把 asyncpg 连接还回池。
        # 关键：AITask/QCIssue 全部推迟到 LLM 之后一次性原子落库，所以此处 commit
        # 不落任何业务写——既释放了连接，又不会在崩溃时留下孤儿 running 任务，原子性完好。
        await self.db.commit()

        # ── 第二步：LLM 规范性和逻辑一致性检查（此时不持有 DB 连接） ──────────
        llm_ok = True
        llm_error: str | None = None
        try:
            content_str = json.dumps(content, ensure_ascii=False)
            prompt = QC_LOGIC_PROMPT.format(content=content_str)
            llm_result = await llm_client.chat_json_stream(
                [{"role": "user", "content": prompt}],
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            for issue_data in llm_result.get("issues", []):
                llm_issues.append(issue_data)
                all_issues.append(issue_data)
        except Exception as e:
            # LLM 失败不影响已算出的规则引擎结果，只记录错误信息
            llm_ok = False
            llm_error = str(e)

        # ── 落库：AITask + 全部 QCIssue + 病历状态，LLM 之后一次原子提交 ──────
        task = AITask(
            medical_record_id=record_id,
            task_type="qc_scan",
            status="success" if llm_ok else "failed",
            error_message=llm_error,
            input_snapshot=content,  # 快照当前版本内容，便于事后审计
        )
        self.db.add(task)
        await self.db.flush()  # 获取数据库生成的 task.id
        for issue_data in rule_issues:
            self.db.add(QCIssue(
                ai_task_id=task.id, medical_record_id=record_id,
                record_version_no=record.current_version, source="rule", **issue_data,
            ))
        for issue_data in llm_issues:
            self.db.add(QCIssue(
                ai_task_id=task.id, medical_record_id=record_id,
                record_version_no=record.current_version, source="llm", **issue_data,
            ))
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
