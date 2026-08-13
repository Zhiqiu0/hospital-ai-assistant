"""接诊推送业务处理（his_adapter/admit_service.py）

2026-08-11 业务联动冲刺：把 WS/HTTP 通道收到的接诊推送落成真实业务——
  1. 患者自动建档：先按 身份证 → 手机+姓名 → 姓名+生日 三级查重复用档案，
     查不到才新建（is_from_his=True 标记来源）
  2. 医生映射：doctor_code（HIS 工号）→ User.employee_no（批量开户时用户名=工号，
     所以再兜底匹配 username），映射不上返回业务错误 ack，厂商日志可见
  3. 接诊幂等：visit_id 为幂等键——同一就诊重复推送（医生在 HIS 反复打开患者）
     复用现存非取消接诊，不重复建档
  4. 工作台叫号：处理成功后向该医生的事件频道发布 admit 事件（SSE 推给浏览器）

调用方：api/v1/his_ws.py（方案 B 长连接）与 api/v1/his.py（方案 A HTTP）。
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime as _dt
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.his_adapter.event_bus import his_event_bus
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User

logger = logging.getLogger(__name__)

# 推送里的 visit_type 口径宽容映射（厂商可能给中文/英文/编码，统一收敛）
_VISIT_TYPE_MAP = {
    "outpatient": "outpatient", "门诊": "outpatient", "1": "outpatient",
    "emergency": "emergency", "急诊": "emergency", "2": "emergency",
    "inpatient": "inpatient", "住院": "inpatient", "3": "inpatient",
}
# 推送 gender（接口枚举 male/female/unknown）→ patients 表中文口径
_GENDER_MAP = {"male": "男", "female": "女", "unknown": "未知"}


class AdmitError(Exception):
    """接诊推送业务错误：code 用于 ack 回执（规范 2.4 错误码体系）。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AdmitResult:
    """接诊推送处理结果（ack data 与叫号事件的数据源）。"""

    encounter_id: str
    patient_id: str
    patient_name: str
    doctor_id: str
    reused: bool  # True=visit_id 已有接诊，本次为重复推送（幂等复用）


async def process_admit(db: AsyncSession, payload: AdmitPushRequest) -> AdmitResult:
    """接诊推送 → 医生映射 + 患者建档 + 接诊创建（visit_id 幂等）。

    Raises:
        AdmitError: 医生工号缺失/未注册（code=40007），厂商 ack 可见
    """
    doctor = await _map_doctor(db, payload.doctor_code)

    # 并发幂等护栏（2026-08-13 复检修复）：下面的「先查后插」在并发下不安全——
    # 厂商超时重发（换新 nonce 绕过防重放）或 WS/HTTP 双通道同推一个 visit_id 时，
    # 两个请求都查不到既有接诊，各自建一条，同一次就诊出现重复接诊+重复患者档案。
    # 用事务级 advisory lock 把「同机构同就诊号」的处理串行化：同 key 的第二个请求
    # 阻塞到第一个提交后再查，就能查到既有接诊走复用分支。锁随事务结束自动释放。
    # 仅 PG 生效（SQLite 测试库无此函数，跳过——测试是单线程无并发）。
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"his_admit:{payload.hospital_code}:{payload.visit_id}"},
        )

    # 幂等：同一机构同 visit_id 已有非取消接诊 → 复用（医生在 HIS 反复打开患者会重推）。
    # 用 hospital_code + visit_id 双键（2026-08-11 审计修复）：visit_id 只在机构内唯一，
    # 且限定 source=admit_push，与历史其它链路数据的命名空间隔离，避免跨机构/跨链路撞号。
    # JSONB 字段的 source/hospital_code 过滤放 Python 侧做（SQLite 测试库不支持 .astext，
    # 生产 PG 用 GIN 索引命中 visit_no 后候选很少，内存过滤开销可忽略）。
    candidates = (await db.execute(
        select(Encounter).where(
            Encounter.visit_no == payload.visit_id,
            Encounter.status != "cancelled",
            Encounter.his_external_ref.isnot(None),
        ).order_by(Encounter.created_at.desc())
    )).scalars().all()
    enc = next(
        (e for e in candidates
         if (e.his_external_ref or {}).get("source") == "admit_push"
         and (e.his_external_ref or {}).get("hospital_code") == payload.hospital_code),
        None,
    )
    if enc is not None:
        # 换医生接诊（2026-08-11 审计修复）：HIS 重推带了新 doctor_code（转接/交接）时，
        # 把接诊改派给新医生并更新科室，否则新医生工作台永远收不到叫号。
        #
        # 但**已结束的接诊不能改派**（2026-08-13 第五轮审计修复）：原先不看状态，
        # 门急诊签发后接诊已 completed、病历也已用原医生的名字签发并回写 HIS，
        # 此时 HIS 若重推一次（重试、补推、visit_id 复用），接诊就被划到另一位
        # 医生名下——他的"我的接诊"里凭空多出一个陌生病人，而那份病历署的是
        # 原医生的名字，责任归属直接错乱。改派只在接诊仍在进行中时才有意义。
        if enc.status in ("completed", "cancelled"):
            logger.info(
                "his.admit: 接诊已结束不改派 encounter_id=%s status=%s doctor_code=%s",
                enc.id, enc.status, payload.doctor_code,
            )
        elif enc.doctor_id != doctor.id:
            prev_doctor_id = enc.doctor_id
            enc.doctor_id = doctor.id
            enc.department_id = doctor.department_id
            ref = dict(enc.his_external_ref or {})
            ref["doctor_code"] = payload.doctor_code
            enc.his_external_ref = ref
            await db.commit()
            await db.refresh(enc)
            # 失效两位医生的接诊列表缓存（2026-08-13 第二轮审计修复）：改派后
            # 原医生的"我的接诊"仍缓存着这条、新医生的缓存里还没有，缓存过期前
            # 两边看到的都是错的——而改派的初衷正是让新医生立刻接手。
            # 接诊快照也一并失效（doctor_id 变了）。
            from app.services.encounter_cache import (
                invalidate_encounter_snapshot,
                invalidate_my_encounters,
            )
            await invalidate_my_encounters(prev_doctor_id)
            await invalidate_my_encounters(doctor.id)
            await invalidate_encounter_snapshot(enc.id)
            logger.info("his_admit.reassigned: visit_id=%s 改派医生 %s",
                        payload.visit_id, doctor.username)
        patient = await db.get(Patient, enc.patient_id)
        return AdmitResult(
            encounter_id=enc.id, patient_id=enc.patient_id,
            patient_name=patient.name if patient else payload.patient_name,
            doctor_id=enc.doctor_id, reused=True,
        )

    patient_id = await _find_or_create_patient(db, payload)

    encounter = Encounter(
        patient_id=patient_id,
        doctor_id=doctor.id,
        department_id=doctor.department_id,
        visit_type=_VISIT_TYPE_MAP.get((payload.visit_type or "").strip(), "outpatient"),
        visit_no=payload.visit_id,
        is_first_visit=payload.is_first_visit if payload.is_first_visit is not None else True,
        status="in_progress",
        # 回写与审计要用的 HIS 上下文全放 his_external_ref（JSONB 灵活适配）
        his_external_ref={
            "source": "admit_push",
            "hospital_code": payload.hospital_code,
            "his_visit_no": payload.visit_id,
            "dept_code": payload.dept_code,
            "dept_name": payload.dept_name,
            "doctor_code": payload.doctor_code,
            "agent_device_ip": payload.agent_device_ip,
        },
    )
    db.add(encounter)
    await db.commit()
    await db.refresh(encounter)
    # 选填体征/档案预填（2026-08-13 补接规范 3.1）：只在新建接诊时做，
    # 重复推送复用既有接诊时不碰——那时医生可能已经改过，不能被 HIS 覆盖。
    await _prefill_from_push(db, encounter.id, patient_id, payload)
    patient = await db.get(Patient, patient_id)
    # 日志不落患者姓名（2026-08-13 第二轮审计修复：PHI 不进日志文件）——
    # 排障靠 patient_id/visit_id 关联查库即可，姓名对定位问题没有增量价值。
    logger.info("his_admit.created: visit_id=%s encounter=%s doctor=%s patient_id=%s",
                payload.visit_id, encounter.id, doctor.username, patient_id)
    return AdmitResult(
        encounter_id=encounter.id, patient_id=patient_id,
        patient_name=patient.name if patient else payload.patient_name,
        doctor_id=doctor.id, reused=False,
    )


_VITALS_KEYS = ("temperature", "pulse", "respiration", "bp_systolic",
                "bp_diastolic", "spo2", "height", "weight")


async def _prefill_from_push(
    db: AsyncSession, encounter_id: str, patient_id: str, payload: AdmitPushRequest
) -> None:
    """把推送里的选填体征/档案预填进工作台（规范 3.1，2026-08-13 补接）。

    落点分两处，与前端读取位置对齐：
      - vitals.*        → InquiryInput（工作台左侧「生命体征快速录入」直接显示）
      - allergy/past    → 患者档案 profile（PatientProfileCard 显示，纵向跟随患者）

    安全边界：
      - 档案**只填空缺**，绝不覆盖我方已有值——我们的档案是医生确认过的，
        HIS 推来的可能是陈旧数据，覆盖等于用旧值抹掉医生的确认。
      - 预填失败不影响接诊建立（体征是锦上添花，接诊本身是命门），只记 warning。
    """
    from app.models.encounter import InquiryInput

    vitals = payload.vitals
    vitals_data = {
        k: (getattr(vitals, k) or "").strip()
        for k in _VITALS_KEYS
    } if vitals else {}
    vitals_data = {k: v for k, v in vitals_data.items() if v}

    try:
        if vitals_data:
            db.add(InquiryInput(encounter_id=encounter_id, version=1, **vitals_data))
            await db.commit()
            logger.info("his_admit.prefill_vitals: encounter=%s 字段=%s",
                        encounter_id, ",".join(sorted(vitals_data)))

        # 档案字段：我方为空 → 直接填；我方已有且不同 → 挂待处理提示，绝不覆盖
        profile_patch = {
            "allergy_history": (payload.allergy_history or "").strip(),
            "past_history": (payload.past_history or "").strip(),
        }
        profile_patch = {k: v for k, v in profile_patch.items() if v}
        if profile_patch:
            patient = await db.get(Patient, patient_id)
            if patient is not None:
                profile = dict(patient.profile or {})
                changed = False
                for field, value in profile_patch.items():
                    entry = dict(profile.get(field) or {})
                    existing = entry.get("value")
                    if not existing:
                        # 我方空缺 → 直接填（复诊首次拿到 HIS 档案的常见情况）
                        profile[field] = {
                            "value": value,
                            "updated_at": _dt.now().isoformat(),
                            "updated_by": None,  # 来源是 HIS 推送，非某个医生手填
                        }
                        changed = True
                        continue
                    if existing.strip() == value:
                        # 两边一致：清掉可能残留的旧提示，不打扰医生
                        if entry.pop("his_pending", None) is not None:
                            profile[field] = entry
                            changed = True
                        continue
                    # 两边不一致（2026-08-13）：既不能用 HIS 陈旧值覆盖医生确认过的内容，
                    # 也不能默默丢弃 HIS 的更新——过敏史漏一项会出用药事故。
                    # 挂成待处理提示，由医生在档案卡上看到差异后自己决定采纳/忽略。
                    entry["his_pending"] = {
                        "value": value,
                        "pushed_at": _dt.now().isoformat(),
                    }
                    profile[field] = entry
                    changed = True
                if changed:
                    patient.profile = profile
                    flag_modified(patient, "profile")
                    await db.commit()
                    # 失效档案缓存（2026-08-13 第五轮审计修复）：档案有 5 分钟
                    # Redis 缓存，写完不失效的话 HIS 推来的过敏史/既往史更新
                    # 最长 5 分钟对医生不可见——他可能正好在这窗口里开药。
                    # 患者档案的所有其他写路径（update_profile/confirm/resolve_his）
                    # 都调了这个，唯独 HIS 预填这条漏了。
                    from app.services.patient_cache import _invalidate_patient_cache
                    await _invalidate_patient_cache(patient_id)
                    logger.info("his_admit.prefill_profile: patient=%s 字段=%s",
                                patient_id, ",".join(sorted(profile_patch)))
    except Exception:
        # 预填失败绝不能连累接诊建立（接诊在则医生还能自己录，接诊没了就啥都没了）
        logger.exception("his_admit.prefill_failed: encounter=%s", encounter_id)
        await db.rollback()


async def _map_doctor(db: AsyncSession, doctor_code: Optional[str]) -> User:
    """HIS 工号 → 系统医生账号。

    匹配顺序（2026-08-13 改为多工号）：
      1. doctor_codes 表——一位医生名下可挂多个工号（本人门诊/本人住院/助理），
         这是主通道。医院名单证实同一医生有 2~3 个工号，HIS 推任一个都要认得。
      2. users.employee_no——存量主工号（迁移已回填进 doctor_codes，这里兜底）
      3. users.username——批量开户约定「用户名=工号」时的兜底

    **助理工号命中的也是本人账号**，因此签发病历署名恒为本人（医院硬要求：
    病历上不能出现助理名字）。
    """
    from app.models.user import DoctorCode

    code = (doctor_code or "").strip()
    if not code:
        raise AdmitError(40007, "接诊推送缺少医生工号（doctor_code）")

    doctor = (await db.execute(
        select(User)
        .join(DoctorCode, DoctorCode.user_id == User.id)
        .where(DoctorCode.code == code, User.is_active.is_(True))
    )).scalars().first()
    if doctor is None:
        result = await db.execute(
            select(User).where(User.employee_no == code, User.is_active.is_(True))
        )
        doctor = result.scalars().first()
    if doctor is None:
        result = await db.execute(
            select(User).where(User.username == code, User.is_active.is_(True))
        )
        doctor = result.scalars().first()
    if doctor is None:
        raise AdmitError(40007, f"医生工号 {code} 未在 MediScribe 注册或已停用")
    return doctor


async def _find_or_create_patient(db: AsyncSession, payload: AdmitPushRequest) -> str:
    """三级查重复用患者档案，查不到新建（is_from_his=True）。

    HIS 推来的身份证/手机号可能不过我方严格校验（历史脏数据），
    校验失败时丢弃该字段继续建档，绝不因脏数据拒收接诊。
    """
    from app.schemas.patient import PatientCreate
    from app.services.patient_service import PatientService

    birth_date: Optional[date] = None
    if payload.birth_date:
        try:
            birth_date = date.fromisoformat(payload.birth_date)
        except ValueError:
            pass  # 解析不了就留空，不阻塞建档

    service = PatientService(db)
    # allow_weak_match=False：HIS 全自动链路禁用「姓名+生日」弱键匹配，
    # 避免同名同生日的不同患者被误合并成一份档案（跨人病历污染是临床事故）。
    # 只有身份证 / 手机号+姓名 强键命中才复用；否则一律新建（可事后人工合并）。
    found = await service.find_existing(
        id_card=payload.id_card or None,
        phone=payload.phone or None,
        name=payload.patient_name,
        birth_date=birth_date,
        allow_weak_match=False,
    )
    if found:
        return found["id"]

    fields = {
        "name": payload.patient_name,
        "gender": _GENDER_MAP.get(payload.gender, "未知"),
        "birth_date": birth_date,
        "id_card": payload.id_card or None,
        "phone": payload.phone or None,
    }
    try:
        create_data = PatientCreate(**fields)
    except ValidationError:
        # 身份证/手机号校验不过（HIS 脏数据）：丢弃这两个字段重建
        fields["id_card"] = None
        fields["phone"] = None
        create_data = PatientCreate(**fields)

    # commit=False：建患者与建接诊合并为同一事务，接诊失败不留孤儿档案
    created = await service.create(create_data, commit=False)
    patient = await db.get(Patient, created["id"])
    patient.is_from_his = True  # 标记 HIS 来源，与手动录入档案区分
    return created["id"]


async def publish_admit_event(result: AdmitResult, payload: AdmitPushRequest) -> None:
    """向医生工作台事件频道发布叫号事件（SSE 端点订阅同一频道）。

    事件带齐队列条目所需字段，前端可直接插入队列不必回查。
    """
    await his_event_bus.publish(f"his:doctor:{result.doctor_id}", {
        "type": "admit",
        "encounter_id": result.encounter_id,
        "visit_no": payload.visit_id,
        "patient_id": result.patient_id,
        "patient_name": result.patient_name,
        "gender": payload.gender,
        "birth_date": payload.birth_date,
        "dept_name": payload.dept_name,
        "is_first_visit": payload.is_first_visit,
        "reused": result.reused,
    })


async def handle_admit(payload: AdmitPushRequest) -> AdmitResult:
    """通道层入口：自管 DB 会话，处理推送并发布叫号事件。

    WS 消息循环没有 FastAPI 依赖注入，这里直接用全局会话工厂；
    单测通过 monkeypatch 本函数（或 process_admit）隔离 DB。
    """
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await process_admit(db, payload)
    await publish_admit_event(result, payload)
    # 失效该医生「进行中接诊」列表缓存（2026-08-11 审计修复）：新建/改派接诊后
    # /encounters/my 有 30s 缓存，不失效则续接诊面板最多滞后 30 秒才见到新病人。
    if not result.reused:
        try:
            from app.services.encounter_service import invalidate_my_encounters
            await invalidate_my_encounters(result.doctor_id)
        except Exception:
            logger.warning("his_admit: 失效 my_encounters 缓存失败 doctor=%s", result.doctor_id)
    return result
