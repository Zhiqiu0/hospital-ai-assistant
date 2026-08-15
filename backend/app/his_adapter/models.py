"""HIS 对接的数据传输对象（DTO）

不是 SQLAlchemy ORM model（那些复用现有 encounter / medical_record 表，
仅扩展一个 his_external_ref JSONB 字段记录 HIS 标识）。

本文件定义：
  - HISExternalRef    : HIS 患者/就诊标识（存进 encounter.his_external_ref 的 JSONB 结构文档）
  - ApiEnvelope / AdmitPushRequest : HIS 外部接口（接诊推送/回写）用的信封与入参

注：控件模式的 Fill* / DesktopHeartbeat DTO 已随 UI 自动化方案退休删除；
    旧 embed 会话的 StartEmbedRequest/StartEmbedResponse 已随 /embed 入口下线删除
    （2026-08-12，接入统一走接诊推送 + 叫号工作台）。

设计原则：
  - 强类型 + Pydantic 校验，前后端契约清晰
"""

from typing import Literal, Optional

from pydantic import field_validator, BaseModel, Field


class HISExternalRef(BaseModel):
    """HIS 患者/就诊外部标识，存进 encounter.his_external_ref JSONB 字段。

    为什么不另开 his_sessions 表：
      嵌入会话本质上就是一次"接诊"——患者来诊、医生录入、生成病历、签发。
      跟普通 SaaS 接诊唯一差异是"病历最终去向是 HIS"而不是"自己的归档"。
      复用 encounter + medical_record 表能让 AI 生成 / 质控 / 审计 / 历史
      查询所有现有逻辑零改动直接复用。

    JSONB 而不是分散的列：
      不同 HIS 厂商的标识字段不一样（金算盘是 patient_no/visit_no，
      东软可能是别的命名），用 JSONB 灵活适配，避免每接一家新医院加新列。
    """

    his_brand: str = Field(..., description="HIS 厂商，如 'jinsuanpan' / 'donghua'")
    hospital_code: str = Field(..., description="医院国家编码，如 H33052300957")
    his_patient_no: str = Field(..., description="HIS 患者编号，跨就诊稳定")
    his_visit_no: Optional[str] = Field(None, description="HIS 就诊号，单次就诊维度")
    his_doctor_no: Optional[str] = Field(None, description="HIS 医生工号（可选）")


class ApiEnvelope(BaseModel):
    """HIS 对接统一响应信封：{code, message, trace_id, data}。"""

    code: int = 0
    message: str = "success"
    trace_id: str = ""
    data: dict = Field(default_factory=dict)


def ok(data: Optional[dict] = None, trace_id: str = "") -> ApiEnvelope:
    """成功信封。"""
    return ApiEnvelope(code=0, message="success", trace_id=trace_id, data=data or {})


def err(code: int, message: str, trace_id: str = "") -> ApiEnvelope:
    """失败信封（HTTP 仍 200，靠 code 区分）。"""
    return ApiEnvelope(code=code, message=message, trace_id=trace_id, data={})


def _coerce_str(v):
    """数值型入参统一转字符串（2026-08-14 规范一致性核对修复）。

    HIS 里体温/脉搏/血压/身高体重几乎都是数值列，序列化成 JSON number 是最
    自然的写法；而我方字段声明为 str，pydantic 严格模式下 36.5 会直接
    ValidationError → **整条接诊推送 40004 被拒，患者进不了工作台**。
    规范承诺的是「选填字段没有就不传，完全不影响流程」，一个格式偏差就把
    主流程打挂，与承诺不符。身份证、手机号同理（厂商可能存成数字列）。
    """
    if isinstance(v, bool):
        return v  # bool 不在此列，交给各自的校验器
    if isinstance(v, (int, float)):
        # 36.0 这种整数值浮点要还原成 "36" 而不是 "36.0"
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    return v


# 性别的宽容映射：接受英文、国标代码（XB：1男/2女/9未知）、中文
_GENDER_ALIASES = {
    "male": "male", "m": "male", "1": "male", "男": "male",
    "female": "female", "f": "female", "2": "female", "女": "female",
    "unknown": "unknown", "9": "unknown", "0": "unknown", "未知": "unknown",
}


def _coerce_gender(v):
    """性别归一（同上修复）。

    规范给的浙里智医对应字段是 XB（国标代码 1/2/9），厂商极可能直接透传原值
    或数据库 NULL，而我方原先是 Literal 严格枚举——传 "1"/"男"/None 都会让
    **整条接诊被拒**。对照：visit_type 早就有中英文+数字的宽容映射。
    识别不了的一律降级为 unknown，不拒收接诊（人进得来最重要，
    性别错了医生在工作台一眼能看出来并改）。
    """
    if v is None:
        return "unknown"
    key = str(v).strip().lower()
    return _GENDER_ALIASES.get(key, "unknown")


# 初诊标志的宽容映射：规范类型写 bool，但对应字段 CZBZDM 是国标代码
_FIRST_VISIT_TRUE = {"true", "1", "初诊", "y", "yes"}
_FIRST_VISIT_FALSE = {"false", "0", "2", "复诊", "n", "no"}


def _coerce_first_visit(v):
    """初诊/复诊归一（同上修复）。

    规范把类型写成 bool 却把对应字段写成 CZBZDM（国标代码），厂商直接映射
    代码值时，"2"（复诊）会 ValidationError 打挂整条接诊。
    识别不了的返回 None，由业务层按「初诊」兜底。
    """
    if v is None or isinstance(v, bool):
        return v
    key = str(v).strip().lower()
    if key in _FIRST_VISIT_TRUE:
        return True
    if key in _FIRST_VISIT_FALSE:
        return False
    return None


class AdmitVitals(BaseModel):
    """接诊推送里的选填体征（规范 3.1 vitals.*，与 3.2 回写字段对称）。

    这些是 HIS 侧护士/设备**实测**的真实值，不是 AI 推断——预填进工作台既省去
    医生重复录入，也不违反"AI 不得编造数值"的红线（红线针对的是无出处的数值）。
    全部按字符串收（厂商可能给 "36.5"/"36.5℃"/空串），落库前统一清洗。
    """

    temperature: Optional[str] = None    # 体温 ℃
    pulse: Optional[str] = None          # 脉搏 次/分
    respiration: Optional[str] = None    # 呼吸 次/分
    bp_systolic: Optional[str] = None    # 收缩压 mmHg
    bp_diastolic: Optional[str] = None   # 舒张压 mmHg
    spo2: Optional[str] = None           # 血氧饱和度 %
    height: Optional[str] = None         # 身高 cm
    weight: Optional[str] = None         # 体重 kg

    # 数值型入参统一转字符串（见 _coerce_str 说明）
    _coerce = field_validator("*", mode="before")(_coerce_str)


class AdmitPushRequest(BaseModel):
    """接诊推送请求体（HIS→我方）。visit_id/hospital_code/patient_name 必填，其余容错可空。"""

    visit_id: str
    hospital_code: str
    patient_name: str
    # HIS 侧患者主索引号（病案号 / 患者主索引 / 居民健康档案号，贵方取哪个都行，
    # 只要「同一个人历次就诊恒定不变」即可）。2026-08-15 补接：
    # 此前我方跨就诊认人只靠 id_card 或 phone+姓名，两者都缺的患者每次就诊
    # 都会新建档案，医生看不到他的既往病历与过敏史。院内编号是 HIS 里最稳定
    # 的标识，收下后与 hospital_code 联合作为查重强键（见 _find_or_create_patient）。
    patient_no: Optional[str] = None
    # 宽容接受英文 / 国标代码 / 中文，识别不了降级 unknown（见 _coerce_gender）
    gender: Literal["male", "female", "unknown"] = "unknown"
    birth_date: Optional[str] = None
    id_card: Optional[str] = None
    phone: Optional[str] = None
    dept_code: Optional[str] = None
    dept_name: Optional[str] = None
    doctor_code: Optional[str] = None
    doctor_name: Optional[str] = None
    visit_type: Optional[str] = None
    is_first_visit: Optional[bool] = None
    agent_device_ip: Optional[str] = None
    agent_device_mac: Optional[str] = None
    # ── 选填档案/体征（规范 3.1，"有则推送"）──────────────────────────────
    # 2026-08-13 补接：规范与发给厂商的参考实现都带这些字段，后端却没定义，
    # pydantic 默认忽略未知字段 → 厂商推来的体温血压被**静默丢弃**，联调现场
    # 会变成"我推了/我没收到"且日志无痕。
    vitals: Optional[AdmitVitals] = None
    allergy_history: Optional[str] = None   # 过敏史（纵向档案，跟随患者）
    past_history: Optional[str] = None      # 既往史（同上）

    # ── 入参容错（2026-08-14 规范一致性核对修复）─────────────────────────
    # 规范承诺「选填字段没有则不传，完全不影响流程」，但原先任意一个格式偏差
    # （体温传数字 / 性别传国标码 / 身份证传数字 / 初诊传 "2"）都会让整条接诊
    # 推送 40004 被拒、患者进不了工作台。这里把格式差异吸收掉，让承诺成立。
    _norm_gender = field_validator("gender", mode="before")(_coerce_gender)
    _norm_first_visit = field_validator("is_first_visit", mode="before")(
        _coerce_first_visit
    )
    # birth_date / patient_no 一并纳入（2026-08-15）：规范容错段写的是「体征、
    # 身份证、手机号**等**接受 JSON 数字」，「等」是开放承诺，白名单却漏了它们。
    # CSRQ 在 HIS 里常是 date 列，序列化成 JSON 数字（19680520）时 pydantic
    # 仍会 ValidationError → 整条接诊推送 40004 被拒，正是容错要根除的失败形态。
    _norm_str_fields = field_validator(
        "id_card", "phone", "visit_id", "hospital_code",
        "dept_code", "doctor_code", "patient_no", "birth_date", mode="before",
    )(_coerce_str)
