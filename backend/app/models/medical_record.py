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

from sqlalchemy import Boolean, UniqueConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class MedicalRecord(Base, TimestampMixin):
    """病历主表（一次接诊可有多份不同类型的病历，如门诊病历 + 转诊记录）。

    record_type 可选值（与《HIS 接口规范》3.2 的 record_type 枚举一一对应，
    该值会原样回写给 HIS，也用作刷新消息的 target，改动须同步规范）：
      outpatient          : 门诊病历
      emergency           : 急诊病历
      admission_note      : 入院记录
      first_course_record : 首次病程记录
      course_record       : 日常病程记录
      senior_round        : 上级医师查房记录
      pre_op_summary      : 术前小结
      op_record           : 手术记录
      post_op_record      : 术后首次病程
      discharge_record    : 出院记录
    """

    __tablename__ = "medical_records"

    # 热路径索引（2026-08-11 病历安全）：quick_save/auto_save/草稿查询/病案首页 都是
    # WHERE encounter_id=? [AND record_type=?] 的高频操作，PG 不给 FK 自动建索引，
    # 原先全表扫描随病历量线性劣化。索引随 alembic 基线建出。
    __table_args__ = (
        Index("idx_medical_records_enc_type", "encounter_id", "record_type"),
        # 文书身份键唯一（2026-08-28 完整性审计）：(接诊, 类型, 序号) = HIS 回写
        # 幂等键，重复即互相覆盖。应用层已在三条写路径锁 encounter 行串行化，
        # 此索引是最后兜底（迁移 k20260828integrity 同名建，含存量顺延清理）
        Index("uq_medrec_enc_type_no", "encounter_id", "record_type", "record_no",
              unique=True),
        # 规模热路径索引（2026-08-31 数据规模审计，迁移 n20260831medrecidx 同名建）：
        # 质控复核台/全院病历列表都是 WHERE status='submitted' [ORDER BY submitted_at
        # DESC]，而 status 单列选择性极差（运行一年后绝大多数行都是这个终态），
        # 必须把 submitted_at 带进来 PG 才能沿索引直接取头部、不排序全表。
        # （用 text 而非 submitted_at.desc()：__table_args__ 在类体顶部求值，
        #   那时列属性还没定义）
        Index("idx_medrec_status_submitted", "status", text("submitted_at DESC")),
        # 未签发草稿的部分索引：不等值查询用不上普通 B-tree，而"没签发的"在任何
        # 时刻都只是极少数，部分索引又小又准——服务病区列表那个
        # `status != 'submitted'` 子查询（住院医生进入接诊的唯一入口）。
        Index("idx_medrec_pending", "encounter_id",
              postgresql_where=text("status <> 'submitted'")),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联接诊（必填）
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), nullable=False)
    # 病历类型（见上方说明）
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 同类型文书的序号（2026-08-14 第六轮审计修复）。
    #
    # 住院一次接诊天然有**多份同类型文书**：日常病程、上级查房、术后病程……
    # 而原先定位病历只按 (encounter_id, record_type) 取最近更新的一行，
    # 第二份病程会直接覆盖第一份——医生前一天写的病程被今天这份顶掉，
    # 病历内容永久丢失。HIS 接口规范里早就预留了 record_no 用于区分多份文书，
    # 但后端一直没实现（全仓 grep 只有注释提到过它）。
    # 门急诊一次接诊一份文书，恒为 1。
    record_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 病历状态："draft"（草稿）/ "final"（已出具最终版）
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # 当前最新版本号（与 RecordVersion.version_no 关联）
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    # 出具最终病历的时间（status 变为 "final" 时填入）
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # ── 记录时间（2026-08-14 第八轮审计后按行业标准新增）────────────────────
    #
    # 这是**临床相关时间**——这份文书所记述的诊疗行为发生在什么时候，
    # 与 created_at（系统录入时间，不可改）是两个不同的东西。两者必须分开存，
    # 这不是本项目的发明，是三方规范一致的要求：
    #
    #   · HL7 FHIR：DocumentReference.date 是"文档创建时刻"，临床相关时间
    #     必须另用 context.period 表达——明确要求两者分开。
    #   · 《病历书写基本规范》：病程记录"首先标明记录时间"，具体到分钟。
    #     它是一个要标出来的字段，不是混在正文里的一句话。
    #   · 医法实务（AHIMA 等）：**绝不允许回填过去时间**。补记应带当前日期、
    #     明确标注为补记、原记录保持可见——因为电子病历有审计轨迹，
    #     事后改时间线一查即知，未标注的补记在纠纷中会被视为可疑。
    #
    # 所以本字段的语义是「这份文书对应的诊疗时点」，而不是「可以随便改的时间」：
    # 它与 created_at 差得多，就说明这是一次**补记**，前端必须显式标注出来
    # （见 is_late_entry / _serialize_record）。
    #
    # 门急诊一次接诊一份文书、当场书写，留空即可（按 submitted_at 展示）。
    recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # ── 病案首页快照（2026-05-16 新增，合规级要求）──────────────────────────
    # 签发时刻把患者完整身份字段冻结到这里：姓名/性别/出生日期/身份证/电话/住址/民族/
    # 婚姻/职业/工作单位/紧急联系人 + 接诊医生/科室/就诊时间。
    # 为什么需要：
    #   病案首页（identity）和病程内容（content）合规上是病历不可分割的两部分。
    #   患者主档后续更新（如改了电话）不应回写已签发病历——已签发的必须保留
    #   签发当时的状态供审计/复核。
    # 旧病历此字段为 NULL，UI 渲染时 fallback 到当前 patient 表，保证不报错。
    patient_snapshot: Mapped[Optional[Any]] = mapped_column(JSONB)

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

    # 热路径索引（2026-08-11 病历安全）：按 (medical_record_id, version_no) 取当前/历史
    # 版本是签发、草稿、版本列表的高频操作，原先全表扫描。索引随 alembic 基线建出。
    __table_args__ = (
        # 版本号唯一（2026-08-13 第五轮审计修复）：version_no 是「读 current_version+1」
        # 算出来的，并发写入会产生两条相同版本号，此后按 version_no==current_version
        # 取正文的 JOIN 会命中 2 行——同一份病历刷新两次看到不同内容，医疗场景
        # 不可接受。应用层三条写路径都加了行锁，这条是数据库层的最后兜底：
        # 任何路径漏加锁都会当场失败而不是静默产出重复版本。
        UniqueConstraint("medical_record_id", "version_no",
                         name="uq_record_versions_record_version"),
        Index("idx_record_versions_rec_ver", "medical_record_id", "version_no"),
        # AI 采纳看板聚合索引（2026-08-12 复检修复）：adoption_stats 按
        # source='doctor_signed' AND ai_similarity IS NOT NULL AND created_at>=X
        # 聚合，无索引会随版本表增长退化为全表扫描。部分索引只覆盖带指标的
        # 签发版本，极小且精准。迁移见 c20260812adoptidx。
        Index(
            "idx_record_versions_adoption",
            "created_at",
            postgresql_where=text("source = 'doctor_signed' AND ai_similarity IS NOT NULL"),
            sqlite_where=text("source = 'doctor_signed' AND ai_similarity IS NOT NULL"),
        ),
        # 签名链链尾（2026-08-14 第七轮审计）：latest_chain_hash 每次医生签发
        # 病历都要跑一次「按 created_at 倒序取最近一条 sign_hash 非空的版本」，
        # 上面两个索引都不覆盖这个条件 → 签发热路径一直全表扫 + 排序。
        # 绝大多数版本是草稿、没有 sign_hash，部分索引体积极小且精准。
        Index(
            "idx_record_versions_chain_tail",
            text("created_at DESC"),
            postgresql_where=text("sign_hash IS NOT NULL"),
            sqlite_where=text("sign_hash IS NOT NULL"),
        ),
        # 管理员修订通道（2026-08-29 对抗复核）：质控复核台"最新修订时间"子查询
        # 与删除横幅整改判据都按 source='admin_revise' 过滤后按 medical_record_id
        # 聚合/EXISTS，上面各索引都不覆盖 → 版本表增长后每次开复核台全表扫。
        # 修订版本占比极小，部分索引小且精准。迁移见 l20260829idxgap。
        Index(
            "idx_record_versions_admin_revise",
            "medical_record_id",
            "created_at",
            postgresql_where=text("source = 'admin_revise'"),
            sqlite_where=text("source = 'admin_revise'"),
        ),
    )

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

    # ── 电子签名防篡改哈希链（2026-08-11 病历可信，分级评审电子签名项基线）──────
    # 仅签发版本(source='doctor_signed')有值：sign_hash = SHA-256(正文+患者快照+
    # 医生+签发时间+prev_hash)，prev_hash 指向上一份签发病历的 sign_hash，串成只追加
    # 的哈希链。任何对已签发病历正文/快照的库内回改、或删除一份签发记录，都会让链
    # 校验失败（见 services/_record_signature.py）。不替代 CA/UKey 数字签名，是其前置基线。
    sign_hash: Mapped[Optional[str]] = mapped_column(String(64))
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64))

    # ── AI 采纳度量（2026-08-12 反馈闭环数据管道）────────────────────────────
    # 仅签发版本(source='doctor_signed')且签发前存在 AI 版本时有值：
    #   ai_similarity      : 签发终稿与最近一版 AI 草稿的文本相似度（0~1，
    #                        difflib.SequenceMatcher.ratio，1=原样采纳）
    #   ai_base_version_no : 对比基准的 AI 版本号（便于追溯是哪版草稿）
    # 纯手写签发（无 AI 版本）两字段均为 NULL，看板聚合时天然排除。
    ai_similarity: Mapped[Optional[float]] = mapped_column(Float)
    ai_base_version_no: Mapped[Optional[int]] = mapped_column(Integer)

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

    # 2026-08-14 第七轮审计：本表零索引。两个外键列在 PG 里不会自动建索引，
    # 而删除父行（ai_task / medical_record）时的外键检查要扫子表。
    __table_args__ = (
        Index("idx_qc_issues_task", "ai_task_id"),
        Index("idx_qc_issues_record", "medical_record_id"),
    )

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
    # 法定扣分条款代码（如 "OP-PRESENT-ILLNESS-02" / "IP-DISCHARGE-01"；LLM 建议无此值）
    # 2026-08-21 阶段0 补列：此前 rule_code 在 SSE 里给了前端但落库丢失，
    # "全院最高频扣分条款 Top 榜"这类统计只能退化到粒度混乱的 field_name
    rule_code: Mapped[Optional[str]] = mapped_column(String(40))
    # 问题解决时间
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # 问题发现时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关联病历（可空）
    record: Mapped[Optional["MedicalRecord"]] = relationship(back_populates="qc_issues")


class QCReport(Base):
    """质控评分报告表（每次法定评分的权威落库记录，2026-08-21 阶段0 新增）。

    与 qc_issues 的分工：本表是"表头"（一次评分的分数/等级/全部法定扣分明细），
    qc_issues 是"明细流水"（逐条问题的处理状态跟踪）。此前评分结果只走 SSE
    给前端、完全不落库——"科室甲级率月度趋势"这类看板在库里无数可查；
    且 qc_issues 只在 LLM 成功后才写，LLM 一挂整次质控零痕迹。
    本表在规则引擎评分完成的瞬间落库（不等 LLM、与 LLM 成败无关）。

    统计口径约定：同一 (encounter_id, record_type) 会随医生反复点质控产生多行，
    看板统计一律按 created_at 取最新一行，否则测出来的是"谁爱点按钮"。

    department_id / doctor_id 是从 Encounter 冗余下来的快照列——看板按科室/
    医生聚合时避免三层 join（audit_logs 冗余 user_name/user_role 是同一先例）。
    """

    __tablename__ = "qc_reports"

    __table_args__ = (
        # 看板主查询：按接诊+类型取最新一次评分
        Index("idx_qc_reports_enc", "encounter_id", "record_type", "created_at"),
        # 科室维度月度聚合
        Index("idx_qc_reports_dept", "department_id", "created_at"),
        # 删除病历前"有无质控报告"探测（2026-08-29 对抗复核）：按
        # medical_record_id 等值查，此前无索引全表扫。可空列用部分索引跳过
        # NULL 行（裸调用产生的报告无病历关联，不参与该查询）。
        Index(
            "idx_qc_reports_record",
            "medical_record_id",
            postgresql_where=text("medical_record_id IS NOT NULL"),
            sqlite_where=text("medical_record_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 被质控的接诊（评分必有接诊上下文；极少数无 encounter 的裸调用存 NULL）
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    # 被质控的那份文书（可空：纯草稿态跑质控时病历行可能还不存在）
    medical_record_id: Mapped[Optional[str]] = mapped_column(ForeignKey("medical_records.id"))
    # 文书类型（住院多文书场景的定位键，与评分表路由同源）
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 使用的评分标准标识（如 "zj_outpatient_emergency_2023" / "zj_inpatient_2021"）
    rubric_key: Mapped[str] = mapped_column(String(50), nullable=False)
    # 总分（法定百分制）
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # 等级（"甲级"/"乙级"/"丙级"；门急诊标准无等级时存 "合格"/"不合格"口径值）
    grade: Mapped[str] = mapped_column(String(10), nullable=False)
    # 是否通过（与 SSE 的 pass 字段同源）
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 全部法定扣分明细快照：[{rule_code,item_name,target_field,points,is_veto,description}]
    deductions: Mapped[Optional[list]] = mapped_column(JSONB)
    # 科室/医生冗余快照（来自 Encounter，聚合免 join；接诊缺失时为 NULL）
    department_id: Mapped[Optional[str]] = mapped_column(String)
    doctor_id: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


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

    # 2026-08-14 第七轮审计：本表零索引。工作台恢复快照（_encounter_snapshot）
    # 每次都按 encounter_id + task_type 取最近一条，医生每开一个患者都要跑几次，
    # 无索引即全表扫描 + 排序。ai_tasks 是随每次 AI 调用增长的大表。
    __table_args__ = (
        Index("idx_ai_tasks_enc_type_created", "encounter_id", "task_type", "created_at"),
        # 删除病历时解挂 AI 任务（2026-08-29 对抗复核）：UPDATE ... WHERE
        # medical_record_id = X 此前无索引全表扫；大部分任务不挂病历（NULL），
        # 部分索引只存非空行，极小。迁移见 l20260829idxgap。
        Index(
            "idx_ai_tasks_record",
            "medical_record_id",
            postgresql_where=text("medical_record_id IS NOT NULL"),
            sqlite_where=text("medical_record_id IS NOT NULL"),
        ),
    )

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


class QCReview(Base):
    """病历复核记录表（科室质控员三级质控的电子化落点，2026-08-21 阶段4）。

    病案首页质控方案要求"出院病历 24 小时内科室质控员自查并签字"——此前
    系统只有医生单签，三级体系（院-科-人）里"科"这一层是纸面的。本表记录
    质控员对已签发文书的复核结论，复核工作台见 api/v1/qc/。

    conclusion 取值：
      passed   : 复核通过
      returned : 退回整改（comment 必填整改意见）
    同一份文书可多次复核（退回→医生修订→再复核），按 created_at 取最新为准。
    """

    __tablename__ = "qc_reviews"

    __table_args__ = (
        Index("idx_qc_reviews_record", "medical_record_id", "created_at"),
        Index("idx_qc_reviews_enc", "encounter_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    medical_record_id: Mapped[str] = mapped_column(
        ForeignKey("medical_records.id"), nullable=False
    )
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    # 复核人（id + 姓名快照，与 audit_logs 冗余 user_name 同先例）
    reviewer_id: Mapped[str] = mapped_column(String, nullable=False)
    reviewer_name: Mapped[Optional[str]] = mapped_column(String(50))
    # passed / returned
    conclusion: Mapped[str] = mapped_column(String(10), nullable=False)
    # 复核意见（退回时必填）
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
