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
from datetime import date
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    # 幂等：同 visit_id 已有非取消接诊 → 复用（医生在 HIS 反复打开患者会重推）
    existing = await db.execute(
        select(Encounter).where(
            Encounter.visit_no == payload.visit_id,
            Encounter.status != "cancelled",
            Encounter.his_external_ref.isnot(None),
        ).order_by(Encounter.created_at.desc()).limit(1)
    )
    enc = existing.scalars().first()
    if enc is not None:
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
    patient = await db.get(Patient, patient_id)
    logger.info("his_admit.created: visit_id=%s encounter=%s doctor=%s patient=%s",
                payload.visit_id, encounter.id, doctor.username, payload.patient_name)
    return AdmitResult(
        encounter_id=encounter.id, patient_id=patient_id,
        patient_name=patient.name if patient else payload.patient_name,
        doctor_id=doctor.id, reused=False,
    )


async def _map_doctor(db: AsyncSession, doctor_code: Optional[str]) -> User:
    """HIS 工号 → 系统医生账号（employee_no 优先，username 兜底）。"""
    code = (doctor_code or "").strip()
    if not code:
        raise AdmitError(40007, "接诊推送缺少医生工号（doctor_code）")
    result = await db.execute(
        select(User).where(User.employee_no == code, User.is_active.is_(True))
    )
    doctor = result.scalars().first()
    if doctor is None:
        # 批量开户约定「用户名=HIS 工号」，employee_no 未回填时兜底匹配用户名
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
    found = await service.find_existing(
        id_card=payload.id_card or None,
        phone=payload.phone or None,
        name=payload.patient_name,
        birth_date=birth_date,
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
    return result
