"""
接诊与问诊输入 ORM 模型（models/encounter.py）

数据表：
  encounters     : 接诊记录主表（一次就诊对应一条记录）
  inquiry_inputs : 医生填写的问诊信息（每条 encounter 关联一条或多条，取最新版本）

业务流程：
  1. 医生创建接诊（POST /encounters/quick-start）
  2. 系统创建 Encounter 记录，状态 "in_progress"
  3. 医生填写问诊信息 → 保存到 InquiryInput
  4. AI 生成病历草稿 → 保存到 MedicalRecord
  5. 出具最终病历 → Encounter 状态变为 "completed"

visit_type 可选值：
  outpatient : 门诊
  emergency  : 急诊
  inpatient  : 住院
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid

# TYPE_CHECKING 块内的导入只在类型检查时生效，运行时不执行，避免循环导入
if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.medical_record import MedicalRecord


class Encounter(Base, TimestampMixin):
    """接诊记录表（一次就诊 = 一条 Encounter）。

    状态流转：
      in_progress → completed（出具最终病历时）
      in_progress → cancelled（接诊取消时）
    """

    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 接诊患者（必填）
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    # 接诊医生（必填）
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    # 所属科室
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))
    # 就诊类型："outpatient"（门诊）/ "emergency"（急诊）/ "inpatient"（住院）
    visit_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 就诊流水号（与 HIS 对接时使用，手动创建时为空）
    visit_no: Mapped[Optional[str]] = mapped_column(String(50))
    # 是否初诊：True=初诊，False=复诊（影响质控规则和 prompt 选择）
    is_first_visit: Mapped[bool] = mapped_column(Boolean, default=True)
    # 接诊状态："in_progress"（进行中）/ "completed"（已完成）/ "cancelled"（已取消）
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    # 主诉简述（来自 InquiryInput.chief_complaint 的摘要，便于列表页快速展示）
    chief_complaint_brief: Mapped[Optional[str]] = mapped_column(String(200))
    # 接诊开始时间
    visited_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 接诊完成时间（出具病历时填入）
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # 床位号（住院用）
    bed_no: Mapped[Optional[str]] = mapped_column(String(20))
    # 入院途径："门诊"/"急诊"/"转院"（住院病案首页字段）
    admission_route: Mapped[Optional[str]] = mapped_column(String(20))
    # 入院病情："危"/"急"/"一般"（住院病案首页字段）
    admission_condition: Mapped[Optional[str]] = mapped_column(String(10))

    # 关联患者信息
    patient: Mapped["Patient"] = relationship(back_populates="encounters")
    # 该次接诊生成的所有病历版本
    medical_records: Mapped[list["MedicalRecord"]] = relationship(back_populates="encounter")
    # 该次接诊的所有问诊输入版本（每次保存产生新版本，取最新的一条使用）
    inquiry_inputs: Mapped[list["InquiryInput"]] = relationship(back_populates="encounter")


class InquiryInput(Base, TimestampMixin):
    """医生问诊输入表（保存结构化的问诊字段内容）。

    每次医生点击「保存问诊信息」会创建新版本（version 递增），
    系统使用最新版本（version 最大值）生成病历。

    字段分组说明：
      基础字段 (6个)      : 门诊/急诊/住院通用（主诉、现病史、既往史等）
      住院扩展字段 (8个)  : 仅住院病历需要
      中医四诊 (4个)      : 中医门诊专用
      门诊诊断细化 (3个)  : 西医/中医疾病/证候诊断
      治疗意见 (4个)      : 治则、处理意见、复诊建议等
      急诊附加 (2个)      : 留观记录、患者去向
      时间字段 (2个)      : 就诊时间、发病时间
    """

    __tablename__ = "inquiry_inputs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), nullable=False)

    # ── 基础问诊字段（门诊/急诊/住院通用）────────────────────────────────────
    chief_complaint: Mapped[Optional[str]] = mapped_column(Text)            # 主诉
    history_present_illness: Mapped[Optional[str]] = mapped_column(Text)   # 现病史
    past_history: Mapped[Optional[str]] = mapped_column(Text)              # 既往史
    allergy_history: Mapped[Optional[str]] = mapped_column(Text)           # 过敏史
    personal_history: Mapped[Optional[str]] = mapped_column(Text)          # 个人史
    # 体格检查：仅存非生命体征的文字描述（心肺听诊、腹部触诊等）
    # 生命体征数值通过独立字段（temperature/pulse/...）存储，AI 生成病历时自动合并到体检段
    physical_exam: Mapped[Optional[str]] = mapped_column(Text)             # 体格检查（不含生命体征数值）
    initial_impression: Mapped[Optional[str]] = mapped_column(Text)        # 初步诊断

    # ── 生命体征（结构化独立字段，取代原 physical_exam 文本内嵌模式）──────
    # 存 String 便于直接承接前端用户输入（可能含 "36.5" / "37" 等多种格式），
    # 未来做异常预警/趋势分析时再转 Float。
    temperature: Mapped[Optional[str]] = mapped_column(String(10))          # 体温 ℃
    pulse: Mapped[Optional[str]] = mapped_column(String(10))                # 脉搏 次/分
    respiration: Mapped[Optional[str]] = mapped_column(String(10))          # 呼吸 次/分
    bp_systolic: Mapped[Optional[str]] = mapped_column(String(10))          # 血压 收缩压 mmHg
    bp_diastolic: Mapped[Optional[str]] = mapped_column(String(10))         # 血压 舒张压 mmHg
    spo2: Mapped[Optional[str]] = mapped_column(String(10))                 # 血氧饱和度 %
    height: Mapped[Optional[str]] = mapped_column(String(10))               # 身高 cm
    weight: Mapped[Optional[str]] = mapped_column(String(10))               # 体重 kg

    # ── 住院病历扩展字段 ──────────────────────────────────────────────────────
    marital_history: Mapped[Optional[str]] = mapped_column(Text)           # 婚育史
    menstrual_history: Mapped[Optional[str]] = mapped_column(Text)         # 月经史（女性）
    family_history: Mapped[Optional[str]] = mapped_column(Text)            # 家族史
    history_informant: Mapped[Optional[str]] = mapped_column(Text)         # 陈述者（供史者）
    current_medications: Mapped[Optional[str]] = mapped_column(Text)       # 当前用药
    rehabilitation_assessment: Mapped[Optional[str]] = mapped_column(Text) # 康复评估
    religion_belief: Mapped[Optional[str]] = mapped_column(Text)           # 宗教信仰（影响用药）
    pain_assessment: Mapped[Optional[str]] = mapped_column(Text)           # 疼痛评估
    vte_risk: Mapped[Optional[str]] = mapped_column(Text)                  # VTE 风险评估（静脉血栓）
    nutrition_assessment: Mapped[Optional[str]] = mapped_column(Text)      # 营养评估
    psychology_assessment: Mapped[Optional[str]] = mapped_column(Text)     # 心理评估
    auxiliary_exam: Mapped[Optional[str]] = mapped_column(Text)            # 辅助检查
    admission_diagnosis: Mapped[Optional[str]] = mapped_column(Text)       # 入院诊断

    # ── 中医四诊（门诊中医专用）──────────────────────────────────────────────
    tcm_inspection: Mapped[Optional[str]] = mapped_column(Text)        # 望诊（神色形态）
    tcm_auscultation: Mapped[Optional[str]] = mapped_column(Text)      # 闻诊（声音气味）
    tongue_coating: Mapped[Optional[str]] = mapped_column(Text)        # 舌象（舌质、舌苔）
    pulse_condition: Mapped[Optional[str]] = mapped_column(Text)       # 脉象

    # ── 门诊诊断细化 ──────────────────────────────────────────────────────────
    western_diagnosis: Mapped[Optional[str]] = mapped_column(Text)      # 西医诊断
    tcm_disease_diagnosis: Mapped[Optional[str]] = mapped_column(Text)  # 中医疾病诊断
    tcm_syndrome_diagnosis: Mapped[Optional[str]] = mapped_column(Text) # 中医证候诊断

    # ── 治疗意见 ──────────────────────────────────────────────────────────────
    treatment_method: Mapped[Optional[str]] = mapped_column(Text)  # 治则治法（中医）
    treatment_plan: Mapped[Optional[str]] = mapped_column(Text)    # 处理意见 / 治疗方案
    followup_advice: Mapped[Optional[str]] = mapped_column(Text)   # 复诊建议
    precautions: Mapped[Optional[str]] = mapped_column(Text)       # 注意事项

    # ── 急诊附加字段 ──────────────────────────────────────────────────────────
    observation_notes: Mapped[Optional[str]] = mapped_column(Text)   # 留观记录
    patient_disposition: Mapped[Optional[str]] = mapped_column(Text) # 患者去向（收住院/离院/转院）

    # ── 时间字段 ──────────────────────────────────────────────────────────────
    # 就诊时间（格式如 "2024-01-15 14:30"，24小时制，写入病历署名行）
    visit_time: Mapped[Optional[str]] = mapped_column(String(30))
    # 发病时间（自然语言，如 "3天前" / "2024年1月10日"）
    onset_time: Mapped[Optional[str]] = mapped_column(String(50))

    # 版本号：每次保存递增，服务层取 version 最大的一条作为当前有效输入
    version: Mapped[int] = mapped_column(default=1)

    # 关联接诊记录
    encounter: Mapped[Encounter] = relationship(back_populates="inquiry_inputs")
