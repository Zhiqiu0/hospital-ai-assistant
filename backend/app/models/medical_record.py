"""
病历相关 ORM 模型（models/medical_record.py）

数据表：
  medical_records  : 病历主表（一次接诊可生成多种类型的病历）
  record_versions  : 病历版本历史（每次保存/生成产生新版本）
  qc_issues        : 质控问题记录（规则引擎和 LLM 发现的问题）
  ai_tasks         : AI 调用任务日志（记录 token 消耗和调用结果）

设计说明：
  病历版本控制（RecordVersion）：
    每次生成、润色、出具最终病历都会产生新版本，current_version 始终指向最新版本号。
    版本历史可用于还原历史内容或审计操作轨迹。

  质控来源区分（QCIssue.source）：
    "rule" : 规则引擎发现的结构性问题（必须修复才能出具病历）
    "llm"  : LLM 质量建议（不阻塞出具，但建议改进）

  AI 任务日志（AITask）：
    记录每次 AI 调用的 token 消耗，用于成本统计和用量分析。
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class MedicalRecord(Base, TimestampMixin):
    """病历主表（一次接诊可有多份不同类型的病历，如门诊病历 + 转诊记录）。

    record_type 可选值：
      outpatient          : 门诊病历
      admission_note      : 入院记录
      first_course_record : 首次病程记录
      course_record       : 日常病程记录
      discharge_record    : 出院记录
      op_record           : 手术记录（及其他住院类型）
    """

    __tablename__ = "medical_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联接诊（必填）
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), nullable=False)
    # 病历类型（见上方说明）
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 病历状态："draft"（草稿）/ "final"（已出具最终版）
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # 当前最新版本号（与 RecordVersion.version_no 关联）
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    # 出具最终病历的时间（status 变为 "final" 时填入）
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 关联接诊
    encounter: Mapped["Encounter"] = relationship(back_populates="medical_records")
    # 所有历史版本（按 version_no 排序使用）
    versions: Mapped[list["RecordVersion"]] = relationship(back_populates="record")
    # 该病历的质控问题
    qc_issues: Mapped[list["QCIssue"]] = relationship(back_populates="record")


class RecordVersion(Base):
    """病历版本历史表（每次生成/修改产生新版本，不可覆盖）。

    source 说明：
      "ai_generate" : AI 一键生成
      "ai_polish"   : AI 润色
      "ai_supplement": AI 补全缺失项
      "manual"      : 医生手动编辑
      "final"       : 出具最终病历时的最终版本
    """

    __tablename__ = "record_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    medical_record_id: Mapped[str] = mapped_column(
        ForeignKey("medical_records.id"), nullable=False
    )
    # 版本号（从 1 开始递增）
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 版本内容（JSONB，存储 {"content": "病历全文..."} 等结构）
    content: Mapped[Any] = mapped_column(JSONB, nullable=False)
    # 版本来源（见上方说明）
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # 触发此版本的用户 ID
    triggered_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    # 关联的 AI 任务 ID（AI 生成的版本有值，手动编辑没有）
    ai_task_id: Mapped[Optional[str]] = mapped_column(String)
    # 版本创建时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关联病历主表
    record: Mapped[MedicalRecord] = relationship(back_populates="versions")


class QCIssue(Base):
    """质控问题记录表。

    每次质控运行（规则引擎 + LLM）的所有问题持久化到此表，
    方便管理员统计各类问题的出现频率，优化质控规则。

    source 字段说明：
      "rule" : 规则引擎检测到的结构性问题（完整性/医保风险）
      "llm"  : LLM 识别的质量建议（格式/逻辑/规范性）
    """

    __tablename__ = "qc_issues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联 AI 任务（必填，用于追溯哪次质控产生了这条问题）
    ai_task_id: Mapped[str] = mapped_column(ForeignKey("ai_tasks.id"), nullable=False)
    # 关联病历（可空：病历未保存时也可以做质控，此时无 medical_record_id）
    medical_record_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("medical_records.id"), nullable=True
    )
    # 质控时的病历版本号（可空）
    record_version_no: Mapped[Optional[int]] = mapped_column(Integer)
    # 问题类型："completeness"/"insurance"/"format"/"logic"/"normality"/"quality"
    issue_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 风险等级："high"（必须修复）/"medium"/"low"
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    # 涉及的病历字段名（如 "physical_exam"/"chief_complaint"）
    field_name: Mapped[Optional[str]] = mapped_column(String(50))
    # 问题描述（展示给医生的文字）
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)
    # 修复建议
    suggestion: Mapped[Optional[str]] = mapped_column(Text)
    # 处理状态："open"（待处理）/"resolved"（已处理）
    status: Mapped[str] = mapped_column(String(20), default="open")
    # 问题来源："rule"（规则引擎）/ "llm"（AI 建议）
    source: Mapped[str] = mapped_column(String(10), default="rule")
    # 问题解决时间
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # 问题发现时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关联病历（可空）
    record: Mapped[Optional["MedicalRecord"]] = relationship(back_populates="qc_issues")


class AITask(Base):
    """AI 调用任务日志表（记录每次 LLM 调用的 token 消耗和结果）。

    用途：
      - 成本统计：按 task_type 分组统计 token 消耗，核算各功能 AI 费用
      - 用量分析：分析高频调用时段，优化限流策略
      - 故障排查：通过 error_message 定位 AI 调用失败原因

    task_type 可选值：
      "qc"       : 病历质控
      "generate" : 病历生成
      "polish"   : 病历润色
      "supplement": 补全缺失项
      "grade"    : 甲级评分
    """

    __tablename__ = "ai_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联接诊（可空，部分任务没有关联接诊）
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    # 关联病历（可空）
    medical_record_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("medical_records.id")
    )
    # 任务类型（见上方说明）
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 任务状态："pending"/"done"/"failed"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # 输入快照（JSONB，存储传给 AI 的关键参数，便于复现和审计）
    input_snapshot: Mapped[Optional[Any]] = mapped_column(JSONB)
    # 输出结果（JSONB，存储 AI 返回的结构化结果）
    output_result: Mapped[Optional[Any]] = mapped_column(JSONB)
    # 调用的模型名称（如 "deepseek-chat"）
    model_name: Mapped[Optional[str]] = mapped_column(String(50))
    # 使用的 prompt 版本
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20))
    # 输入 token 数（获取失败时为 0，NULL 表示未记录）
    token_input: Mapped[Optional[int]] = mapped_column(Integer)
    # 输出 token 数
    token_output: Mapped[Optional[int]] = mapped_column(Integer)
    # 调用耗时（毫秒）
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    # 失败时的错误信息
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    # 任务创建时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 任务完成时间
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# 延迟导入避免循环引用（MedicalRecord ↔ Encounter）
from app.models.encounter import Encounter  # noqa: E402
