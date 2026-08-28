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

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
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

    # 按 HIS 患者主索引号反查接诊（患者查重强键 2，见 admit_service
    # ._find_patient_by_his_no）。2026-08-15 换索引形状：
    # 原索引是 GIN((his_external_ref -> 'his_patient_no'))，但查询是**等值查
    # JSON 标量**，走的是 ->> 取文本后比对，GIN 那个形状根本命中不了
    # （GIN 服务的是整列 @> 包含查询）。等值查 JSON 标量的通行做法是在 ->>
    # 表达式上建 btree，这里改成与查询逐字对应的形状。
    __table_args__ = (
        Index(
            "idx_encounters_his_patient_no",
            text("(his_external_ref ->> 'his_patient_no')"),
        ),
        # 热路径索引（2026-08-11 病历安全）："我的接诊"/叫号队列都按
        # doctor_id + visited_at 过滤排序，原先无索引全表扫描。索引随 alembic 基线建出。
        Index("idx_encounters_doctor_visited", "doctor_id", "visited_at"),
        # HIS 接诊幂等查重（2026-08-14 第七轮审计）：process_admit 每收到一条
        # 推送都要按 visit_no 反查已有接诊，且这条查询跑在 advisory lock 里面。
        # 原先 visit_no 上**没有任何索引**——上面那个 GIN 索引建的是
        # his_external_ref->'his_patient_no'，跟 visit_no 是两回事，
        # 而 admit_service 里的注释一直宣称「用 GIN 索引命中 visit_no」。
        # 实际每次患者叫号都全表扫 encounters，还串行化在锁内，随接诊量线性劣化。
        Index("idx_encounters_visit_no", "visit_no"),
        # 患者维度反查（档案页、既往接诊、病历列表都按 patient_id 过滤）
        Index("idx_encounters_patient", "patient_id"),
    )

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

    # ── 取消接诊（status='cancelled' 配套字段，2026-05-03 加）─────────────────
    # 取消理由：医生显式填写，预设 5 选 + 自由备注，纯文本存。
    # 设计为 nullable：仅取消时填写，正常 in_progress / completed 接诊为空。
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(500))
    # 取消时间
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # 操作医生 ID（一般 = doctor_id，但保留独立字段以备将来值班医生强取等场景）
    cancelled_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))

    # ── HIS 嵌入模式外部标识（2026-05-27 加）────────────────────────────────
    # 嵌入模式接诊关联的 HIS 患者标识，普通 SaaS 接诊为 NULL。
    # JSONB 字段结构见 his_adapter/models.py:HISExternalRef，示例：
    #   {"his_brand": "jinsuanpan", "hospital_code": "H33052300957",
    #    "his_patient_no": "Y1232605260025", "his_visit_no": "20260526000200"}
    # 加 GIN 索引（his_patient_no 路径），方便医生从 HIS 切回查上次接诊。
    #
    # ⚠️ 现状（2026-08-14 第七轮审计 #21）：**his_patient_no 实际从来没被写入过**。
    #    admit_service 建接诊时只写 source/hospital_code/his_visit_no/dept/doctor，
    #    因为 AdmitPushRequest 里压根没有"HIS 患者编号"这个字段——规范的接诊推送
    #    只带 visit_id。于是上面那个 GIN 索引索引的是一个恒不存在的键，
    #    「从 HIS 切回查上次接诊」这个能力也并不存在。
    #    Patient.patient_no 同理，全仓只读不写，恒为 NULL。
    #    要补齐需要厂商在推送里加患者编号字段（改接口契约，需与厂商约定），
    #    不是后端单方面能补的，故此处只把注释改成实话，不做假实现。
    # none_as_null=True：Python None 存 SQL NULL（而非 JSON null），否则
    # 「his_external_ref IS NOT NULL」这类过滤（叫号队列只看 HIS 接诊）会失效。
    his_external_ref: Mapped[Optional[dict]] = mapped_column(JSONB(none_as_null=True))

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

    # 热路径索引（2026-08-11 病历安全）：取最新问诊版本(WHERE encounter_id ORDER BY
    # version DESC)是 AI 生成/工作台恢复的高频前置查询，原先全表扫描。索引随 alembic 基线建出。
    __table_args__ = (
        Index("idx_inquiry_inputs_enc_ver", "encounter_id", "version"),
    )

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


class Diagnosis(Base, TimestampMixin):
    """诊断条目表（病历诊断的结构化权威源，2026-08-21 阶段1）。

    背景（病案首页质控方案落地）：病案首页是 DRG 分组唯一数据源，"主要诊断
    选择错误"是法定单项否决（扣 10 分）且直接决定医保拨付。此前诊断散落在
    inquiry_inputs 的三个自由文本列，主诊断靠"第一个非空字段即主"隐式推断，
    "入院病情"标志（首页逐条诊断必填项）完全没有落点。

    职责边界（与 problem_list 表的区分，防两套真相）：
      - 本表      = 法定文书语义——病历/病案首页上的诊断条目（回写 HIS 的
                    diagnoses[] 数组即从本表构建），每次接诊的权威诊断清单
      - problem_list = 临床管理语义——住院期间的问题跟踪（active/resolved
                    生命周期），是医生的工作清单而非法定文书内容

    双写过渡策略（阶段1）：本表为权威；保存时同步把条目渲染成文本投影写回
    inquiry_inputs 的旧三列（western_diagnosis / tcm_disease_diagnosis /
    tcm_syndrome_diagnosis），LLM 生成 / 渲染器 / QC 引擎现有文本链路零改动
    继续工作，后续阶段逐步切到结构化直读。

    category 取值（与 HIS 回写 diagnoses[].category 枚举一致）：
      western     : 西医诊断（可多条，其中恰一条 is_primary）
      tcm_disease : 中医疾病诊断（每次接诊至多一条）
      tcm_syndrome: 中医证候诊断（每次接诊至多一条）

    admission_condition（入院病情，病案首页逐条诊断的标志位，住院场景填写）：
      有 / 临床未确定 / 情况不明 / 无 —— 国家病案首页规范四值枚举
    """

    __tablename__ = "diagnoses"

    __table_args__ = (
        # 主查询：按接诊拉全部条目（排序在应用层按 sort_order）
        Index("idx_diagnoses_enc", "encounter_id"),
        # 主诊断唯一部分索引（2026-08-28 完整性审计）：replace_all 的接诊行锁
        # 是"单写路径记得加锁"式保护，这里给"每接诊至多一条主诊断"的病案首页
        # 硬约束加 DB 终极兜底（迁移 k20260828integrity 同名建）
        Index("uq_diag_primary_per_enc", "encounter_id", unique=True,
              postgresql_where=text("is_primary"),
              sqlite_where=text("is_primary")),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[str] = mapped_column(
        ForeignKey("encounters.id"), nullable=False
    )
    # 诊断类别：western / tcm_disease / tcm_syndrome（枚举见类注释）
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    # 诊断名称（权威展示值；编码化后与 code 成对）
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 诊断编码 + 编码体系（阶段2 编码化启用；HIS 回写 v1.4 已预留同名槽位）
    # code_type 枚举与接口规范一致：ICD10（西医）/ GB95（中医病证分类国标）
    code: Mapped[Optional[str]] = mapped_column(String(20))
    code_type: Mapped[Optional[str]] = mapped_column(String(10))
    # 是否主要诊断（西医组内恰一条为真；法定单项否决项，必须显式而非推断）
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    # 入院病情标志（住院场景逐条必填；门急诊留空）
    admission_condition: Mapped[Optional[str]] = mapped_column(String(10))
    # 组内排序（西医多条时的展示与回写次序；主诊断恒排首位）
    sort_order: Mapped[int] = mapped_column(default=0)
    # 录入人（医生姓名快照，与 problem_list.added_by 同风格）
    added_by: Mapped[Optional[str]] = mapped_column(String(50))


class DiagnosisCode(Base):
    """诊断/手术编码字典表（2026-08-21 阶段2 编码化）。

    数据源（全部官方渠道，构建脚本 scripts/build_diagnosis_dict.py）：
      ICD10    : 疾病诊断编码，医保 2.0 口径（湖北完整库的医保对应码列）
      ICD9CM3  : 手术操作编码，医保 2.0 口径（同上）
      TCD_DIS  : 中医疾病名代码（GB/T 15657-2021，A 码，云南医保局医保版材料）
      TCD_SYN  : 中医证候名代码（GB/T 15657-2021，B 码，同上）
    共约 4.8 万条，随迁移自动导入（seed_data/diagnosis_codes.csv.gz）。

    检索设计：名称 contains + 拼音首字母前缀 + 编码前缀 三路（搜索端点见
    api/v1/diagnosis_codes.py）；aliases 存"可选词"别名（中医国标里的
    同义写法，如 感冒 的"伤风感冒"），检索时一并命中。

    HIS 回写 code_type 映射：ICD10→"ICD10"；TCD_DIS/TCD_SYN→"GB95"
    （v1.4 规范枚举值；国标已升级 2021 版，具体口径联调时与厂商确认）。
    """

    __tablename__ = "diagnosis_codes"

    __table_args__ = (
        # 三路检索索引：类型+名称 / 类型+拼音首字母（前缀）/ 类型+编码（前缀）
        Index("idx_diag_codes_type_name", "code_type", "name"),
        Index("idx_diag_codes_type_pinyin", "code_type", "pinyin_initial"),
        Index("idx_diag_codes_type_code", "code_type", "code"),
        # 字典键唯一（2026-08-28 完整性审计）：构建脚本已去重，这里防换版
        # 导入路径回潮（迁移 k20260828integrity 同名建）
        Index("uq_diagcode_type_code", "code_type", "code", unique=True),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # ICD10 / ICD9CM3 / TCD_DIS / TCD_SYN
    code_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # 主名拼音首字母串（小写），联想检索用
    pinyin_initial: Mapped[Optional[str]] = mapped_column(String(60))
    # 别名（"；"分隔，中医"可选词"），检索一并命中
    aliases: Mapped[Optional[str]] = mapped_column(String(300))
    # 字典版本标注（整库换版时区分）
    version: Mapped[str] = mapped_column(String(20), default="医保2.0")
