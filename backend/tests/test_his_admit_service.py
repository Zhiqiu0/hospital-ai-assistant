"""接诊推送业务落地单测（his_adapter/admit_service.py）。

覆盖：医生映射（employee_no / username 兜底 / 未注册拒收）、患者三级查重复用、
新建患者标记 is_from_his、visit_id 幂等、脏身份证降级、visit_type 口径映射。
"""
import pytest
from sqlalchemy import select

from app.his_adapter.admit_service import AdmitError, process_admit
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User


def _payload(**overrides) -> AdmitPushRequest:
    """构造最小合法接诊推送载荷，字段可覆盖。"""
    base = {
        "visit_id": "20260811000101",
        "hospital_code": "H33052300957",
        "patient_name": "张三",
        "gender": "male",
        "doctor_code": "D1001",
        "dept_code": "1230024",
        "dept_name": "全科",
    }
    base.update(overrides)
    return AdmitPushRequest(**base)


async def _mk_doctor(db, *, username="doc1", employee_no="D1001") -> User:
    """建一个激活状态的医生账号。"""
    doctor = User(
        username=username, password_hash="x", real_name="王医生",
        role="doctor", employee_no=employee_no, is_active=True,
    )
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return doctor


@pytest.mark.asyncio
async def test_admit_creates_patient_and_encounter(async_db):
    """新患者推送 → 建档（is_from_his=True，性别转中文）+ 建接诊（落 HIS 上下文）。"""
    doctor = await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload())

    assert result.reused is False
    assert result.doctor_id == doctor.id
    patient = await async_db.get(Patient, result.patient_id)
    assert patient.name == "张三"
    assert patient.gender == "男"
    assert patient.is_from_his is True
    enc = await async_db.get(Encounter, result.encounter_id)
    assert enc.visit_no == "20260811000101"
    assert enc.visit_type == "outpatient"
    assert enc.his_external_ref["source"] == "admit_push"
    assert enc.his_external_ref["dept_name"] == "全科"


@pytest.mark.asyncio
async def test_admit_unmapped_doctor_rejected(async_db):
    """医生工号未注册 → AdmitError(40007)。"""
    with pytest.raises(AdmitError) as exc_info:
        await process_admit(async_db, _payload(doctor_code="D404"))
    assert exc_info.value.code == 40007
    assert "D404" in exc_info.value.message


@pytest.mark.asyncio
async def test_admit_missing_doctor_code_rejected(async_db):
    """推送缺 doctor_code → AdmitError(40007)。"""
    with pytest.raises(AdmitError) as exc_info:
        await process_admit(async_db, _payload(doctor_code=None))
    assert exc_info.value.code == 40007


@pytest.mark.asyncio
async def test_admit_doctor_matched_by_username_fallback(async_db):
    """employee_no 未回填时，用户名=工号 兜底匹配（批量开户约定）。"""
    doctor = await _mk_doctor(async_db, username="D2002", employee_no=None)
    result = await process_admit(async_db, _payload(doctor_code="D2002"))
    assert result.doctor_id == doctor.id


@pytest.mark.asyncio
async def test_admit_visit_id_idempotent(async_db):
    """同 visit_id 重复推送 → 复用现存接诊，不重复建档。"""
    await _mk_doctor(async_db)
    first = await process_admit(async_db, _payload())
    second = await process_admit(async_db, _payload())

    assert second.reused is True
    assert second.encounter_id == first.encounter_id
    count = (await async_db.execute(select(Encounter))).scalars().all()
    assert len(count) == 1
    patients = (await async_db.execute(select(Patient))).scalars().all()
    assert len(patients) == 1


@pytest.mark.asyncio
async def test_admit_patient_dedup_by_id_card(async_db):
    """同身份证不同就诊 → 复用患者档案，只建新接诊。"""
    await _mk_doctor(async_db)
    id_card = "330523199001011238"  # 校验位合法的测试号
    first = await process_admit(
        async_db, _payload(id_card=id_card, birth_date="1990-01-01"))
    second = await process_admit(
        async_db, _payload(visit_id="20260811000102", id_card=id_card,
                           birth_date="1990-01-01"))
    assert second.patient_id == first.patient_id
    assert second.encounter_id != first.encounter_id


@pytest.mark.asyncio
async def test_admit_dirty_id_card_dropped(async_db):
    """HIS 推来的身份证过不了严格校验 → 丢弃该字段建档，不拒收接诊。"""
    await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload(id_card="123456"))
    patient = await async_db.get(Patient, result.patient_id)
    assert patient.id_card is None
    assert patient.name == "张三"


@pytest.mark.asyncio
async def test_admit_visit_type_chinese_mapped(async_db):
    """visit_type 中文口径（急诊）→ 收敛为 emergency。"""
    await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload(visit_type="急诊"))
    enc = await async_db.get(Encounter, result.encounter_id)
    assert enc.visit_type == "emergency"


@pytest.mark.asyncio
async def test_admit_cancelled_encounter_not_reused(async_db):
    """现存同 visit_id 接诊已取消 → 视为新接诊重建（医生误取消后 HIS 重推）。"""
    await _mk_doctor(async_db)
    first = await process_admit(async_db, _payload())
    enc = await async_db.get(Encounter, first.encounter_id)
    enc.status = "cancelled"
    await async_db.commit()

    second = await process_admit(async_db, _payload())
    assert second.reused is False
    assert second.encounter_id != first.encounter_id


# ── 2026-08-13 补接规范 3.1 选填体征/档案 ──────────────────────────────────

@pytest.mark.asyncio
async def test_admit_prefills_vitals_into_inquiry(async_db):
    """HIS 推来的实测体征要预填进问诊（工作台左侧「生命体征快速录入」直接显示）。

    回归的是一个真实缺口：规范 3.1 与发给厂商的参考实现都带 vitals.*，
    后端模型却没定义 → pydantic 默认忽略未知字段 → 体温血压被静默丢弃，
    联调现场会变成"我推了/我没收到"且日志无痕。
    """
    from sqlalchemy import select
    from app.models.encounter import InquiryInput

    await _mk_doctor(async_db)
    payload = _payload(vitals={"temperature": "38.5", "pulse": "96",
                               "bp_systolic": "138", "bp_diastolic": "86",
                               "spo2": "", "height": "170"})
    result = await process_admit(async_db, payload)

    inq = (await async_db.execute(
        select(InquiryInput).where(InquiryInput.encounter_id == result.encounter_id)
    )).scalars().first()
    assert inq is not None, "推送带了体征却没建问诊记录"
    assert inq.temperature == "38.5" and inq.pulse == "96"
    assert inq.bp_systolic == "138" and inq.bp_diastolic == "86"
    assert inq.height == "170"
    assert not inq.spo2  # 空串不落库，避免占位假数据


@pytest.mark.asyncio
async def test_admit_without_vitals_creates_no_inquiry(async_db):
    """不带体征的推送不该凭空建空问诊记录（保持原有行为）。"""
    from sqlalchemy import select
    from app.models.encounter import InquiryInput

    await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload())
    inq = (await async_db.execute(
        select(InquiryInput).where(InquiryInput.encounter_id == result.encounter_id)
    )).scalars().first()
    assert inq is None


@pytest.mark.asyncio
async def test_admit_profile_fills_blank_but_never_overwrites(async_db):
    """过敏史/既往史只填我方空缺，绝不覆盖医生已确认的值。

    我们的档案是医生当面问出来并确认过的，HIS 推来的可能是陈旧数据，
    覆盖等于用旧值抹掉医生的确认——临床风险。
    """
    from app.models.patient import Patient

    await _mk_doctor(async_db)
    # 先建一个已有过敏史（医生确认过）的患者，用身份证保证被复用
    existing = Patient(
        name="张三", id_card="330521199001011234", is_from_his=True,
        profile={"allergy_history": {"value": "青霉素过敏（医生确认）",
                                     "updated_at": "2026-08-01T10:00:00",
                                     "updated_by": "doc-1"}},
    )
    async_db.add(existing)
    await async_db.commit()

    await process_admit(async_db, _payload(
        id_card="330521199001011234",
        allergy_history="无",          # HIS 侧陈旧值，不该覆盖
        past_history="高血压 10 年",   # 我方为空 → 应填入
    ))

    await async_db.refresh(existing)
    assert existing.profile["allergy_history"]["value"] == "青霉素过敏（医生确认）"
    assert existing.profile["past_history"]["value"] == "高血压 10 年"


@pytest.mark.asyncio
async def test_admit_conflicting_profile_becomes_pending_not_overwrite(async_db):
    """HIS 值与我方不一致 → 挂待处理提示，既不覆盖也不丢弃。

    覆盖我方值 = 用 HIS 陈旧数据抹掉医生确认过的内容；
    直接丢弃 HIS 值 = 可能漏掉新增的过敏原（用药事故）。
    所以两边都不做，交给医生在档案卡上裁决。
    """
    from app.models.patient import Patient

    await _mk_doctor(async_db)
    existing = Patient(
        name="张三", id_card="330521199001011234", is_from_his=True,
        profile={"allergy_history": {"value": "青霉素过敏",
                                     "updated_at": "2026-08-01T10:00:00",
                                     "updated_by": "doc-1"}},
    )
    async_db.add(existing)
    await async_db.commit()

    await process_admit(async_db, _payload(
        id_card="330521199001011234",
        allergy_history="青霉素、头孢过敏",   # HIS 侧更全，但不能直接覆盖
    ))

    await async_db.refresh(existing)
    entry = existing.profile["allergy_history"]
    assert entry["value"] == "青霉素过敏"                       # 我方值没被覆盖
    assert entry["his_pending"]["value"] == "青霉素、头孢过敏"   # HIS 值挂起等裁决


@pytest.mark.asyncio
async def test_admit_same_profile_value_clears_stale_pending(async_db):
    """两边值一致时清掉残留的待处理标记，不反复打扰医生。"""
    from app.models.patient import Patient

    await _mk_doctor(async_db)
    existing = Patient(
        name="张三", id_card="330521199001011234", is_from_his=True,
        profile={"allergy_history": {"value": "青霉素过敏",
                                     "updated_at": "2026-08-01T10:00:00",
                                     "his_pending": {"value": "旧的待处理值",
                                                     "pushed_at": "2026-08-02T10:00:00"}}},
    )
    async_db.add(existing)
    await async_db.commit()

    await process_admit(async_db, _payload(
        id_card="330521199001011234", allergy_history="青霉素过敏",
    ))

    await async_db.refresh(existing)
    assert "his_pending" not in existing.profile["allergy_history"]


# 合法身份证（两次推送靠它命中同一份档案；HIS 链路禁用姓名+生日弱键，见审计 #18）
_ID = "11010519491231002X"


# ── 第七轮审计 #19：医生特意清空的档案字段不许被 HIS 旧值填回 ────────────────

@pytest.mark.asyncio
async def test_prefill_does_not_undo_doctor_cleared_field(async_db):
    """医生把过敏史清空（=已核实，无），HIS 推来的陈旧值不能悄悄填回去。

    update_profile 在医生清空时写的是 {"value": "", updated_at, updated_by}——
    一条**有医生署名**的空值。原判断用 `if not existing` 把空字符串当"从没填过"，
    于是直接用 HIS 的老记录覆盖：医生刚确认患者不对青霉素过敏，那条又冒回来了。
    现在应该走"差异提示"（his_pending），由医生自己决定采纳还是忽略。
    """
    from app.models.patient import Patient
    from app.services.patient_service import PatientService
    from app.schemas.patient import PatientProfileUpdate
    from sqlalchemy import select

    await _mk_doctor(async_db)
    # 第一次接诊：HIS 推来过敏史，我方空缺 → 直接填
    await process_admit(async_db, _payload(id_card=_ID, allergy_history="青霉素过敏"))
    patient = (await async_db.execute(select(Patient))).scalars().first()
    assert (patient.profile or {})["allergy_history"]["value"] == "青霉素过敏"

    # 医生核实后清空
    await PatientService(async_db).update_profile(
        patient.id, PatientProfileUpdate(allergy_history=""), doctor_id="doc-1"
    )

    # 第二次接诊：HIS 又推同一条陈旧过敏史
    await process_admit(
        async_db,
        _payload(visit_id="20260811000102", id_card=_ID, allergy_history="青霉素过敏"),
    )

    await async_db.refresh(patient)
    entry = (patient.profile or {})["allergy_history"]
    assert entry["value"] == "", "医生清空的过敏史被 HIS 旧值填回来了"
    assert entry.get("his_pending", {}).get("value") == "青霉素过敏", (
        "HIS 的值应挂成待处理提示交医生决定，而不是直接丢弃"
    )


@pytest.mark.asyncio
async def test_prefill_still_fills_never_set_field(async_db):
    """防过度收紧：从没填过的字段（整条不存在）仍然要直接填。"""
    from app.models.patient import Patient
    from sqlalchemy import select

    await _mk_doctor(async_db)
    await process_admit(async_db, _payload(past_history="高血压 10 年"))

    patient = (await async_db.execute(select(Patient))).scalars().first()
    assert (patient.profile or {})["past_history"]["value"] == "高血压 10 年"


@pytest.mark.asyncio
async def test_patient_no_reuses_archive_without_id_card(async_db):
    """无身份证的患者复诊：靠 patient_no 认出是同一个人，复用同一份档案。

    这是 2026-08-15 补接 patient_no 的核心价值——此前身份证与手机号都缺时，
    同一位患者每次就诊都会新建档案，医生看不到他的既往病历与过敏史。
    """
    await _mk_doctor(async_db)
    first = await process_admit(async_db, _payload(
        visit_id="V-A-1", patient_no="BA20260001", id_card=None, phone=None,
    ))
    second = await process_admit(async_db, _payload(
        visit_id="V-A-2", patient_no="BA20260001", id_card=None, phone=None,
    ))
    assert second.patient_id == first.patient_id, "同一 patient_no 应复用档案"

    # 落库到约定的键上（生产索引就建在这个键的 ->> 表达式上）
    enc = (await async_db.execute(
        select(Encounter).where(Encounter.visit_no == "V-A-1")
    )).scalar_one()
    assert enc.his_external_ref["his_patient_no"] == "BA20260001"


@pytest.mark.asyncio
async def test_patient_no_scoped_by_hospital_code(async_db):
    """院内编号只在本院唯一：机构编码不同则**不得**跨院合并成同一份档案。"""
    await _mk_doctor(async_db)
    a = await process_admit(async_db, _payload(
        visit_id="V-B-1", hospital_code="H33052300957",
        patient_no="0001", id_card=None, phone=None,
    ))
    b = await process_admit(async_db, _payload(
        visit_id="V-B-2", hospital_code="H33999999999",
        patient_no="0001", id_card=None, phone=None,
    ))
    assert a.patient_id != b.patient_id, "跨机构撞号绝不能合并档案"


@pytest.mark.asyncio
async def test_id_card_still_wins_over_patient_no(async_db):
    """身份证优先级更高：有身份证时行为与补接 patient_no 之前完全一致（零回归）。"""
    await _mk_doctor(async_db)
    first = await process_admit(async_db, _payload(
        visit_id="V-C-1", id_card="330523199001011238", patient_no="X-1",
    ))
    # HIS 换了个院内编号推同一个身份证 → 仍按身份证认人
    second = await process_admit(async_db, _payload(
        visit_id="V-C-2", id_card="330523199001011238", patient_no="X-2",
    ))
    assert second.patient_id == first.patient_id


@pytest.mark.asyncio
async def test_birth_date_compact_format_not_lost(async_db):
    """CSRQ 传 YYYYMMDD 紧凑写法时，出生日期要落库而不是被静默丢弃。

    入参容错让这条推送不再被 40004 拒收，但若这里解析不了就等于丢掉出生日期，
    而年龄影响用药与诊断判断。
    """
    from datetime import date
    await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload(
        visit_id="V-BD-1", birth_date=19680520,
    ))
    patient = await async_db.get(Patient, result.patient_id)
    assert patient.birth_date == date(1968, 5, 20)
