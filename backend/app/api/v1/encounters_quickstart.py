"""
接诊「一键开始」子路由（POST /api/v1/encounters/quick-start）

从 encounters.py 拆出（Round 5 瘦身）：只负责 quick-start（创建患者 + 接诊，
带幂等锁、复诊判断、上次问诊/病历回填）。行为与拆分前逐字一致，
路由路径/方法/依赖零改动。本模块自建 router，由 encounters.py 主 router 拼回。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from datetime import date
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.encounter import EncounterCreate, QuickStartRequest
from app.schemas.patient import PatientCreate
from app.services.encounter_service import EncounterService
from app.services.patient_service import PatientService
from app.services.redis_cache import redis_cache
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.encounter import Encounter as EncounterModel, InquiryInput

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/quick-start")
async def quick_start_encounter(
    data: QuickStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """快速开始接诊：创建患者（如已存在则复用）并创建接诊记录。"""
    # 幂等锁：防止用户双击「开始接诊」时建出两条 encounter / 两条 patient。
    # 锁 key 选择：优先 patient_id，其次身份证号，再次姓名（最弱，但有总比没有强）。
    # ttl 5s 够走完整个 quick-start 流程；崩溃也会自动释放。
    lock_id = data.patient_id or data.id_card or data.patient_name or "anon"
    lock_key = f"lock:quickstart:{current_user.id}:{lock_id}"
    lock_token = await redis_cache.acquire_lock(lock_key, ttl=5)
    if lock_token is None:
        raise HTTPException(status_code=409, detail="操作过于频繁，请稍候再试")

    try:
        return await _quick_start_inner(data, db, current_user)
    finally:
        await redis_cache.release_lock(lock_key, lock_token)


async def _quick_start_inner(data, db, current_user):
    """quick-start 主体逻辑（外层包了幂等锁）。"""
    # 解析出生日期（前端统一传 YYYY-MM-DD），格式无效则忽略，patient 仍可创建
    birth_date_val: Optional[date] = None
    if data.birth_date:
        try:
            birth_date_val = date.fromisoformat(data.birth_date)
        except ValueError:
            logger.warning("encounter.quick_start: invalid birth_date=%r ignored", data.birth_date)

    patient_service = PatientService(db)

    # 前端传入已知患者 ID 时（复诊场景）直接复用，跳过模糊匹配
    if data.patient_id:
        patient = await patient_service.get_by_id(data.patient_id)
        patient_reused = True
    else:
        patient = await patient_service.find_existing(
            id_card=data.id_card,
            phone=data.phone,
            name=data.patient_name,
            birth_date=birth_date_val,
        )
        patient_reused = patient is not None

    if not patient:
        patient = await patient_service.create(PatientCreate(
            name=data.patient_name,
            gender=data.gender,
            birth_date=birth_date_val,
            id_card=data.id_card,
            phone=data.phone,
            address=data.address,
            ethnicity=data.ethnicity,
            marital_status=data.marital_status,
            occupation=data.occupation,
            workplace=data.workplace,
            contact_name=data.contact_name,
            contact_phone=data.contact_phone,
            contact_relation=data.contact_relation,
            blood_type=data.blood_type,
        ))

    encounter_service = EncounterService(db)

    # ── 2026-05-03 复诊判断改写 ───────────────────────────────────────────────
    # 旧逻辑：is_first_visit = not patient_reused（只看患者表是否存在）
    # 问题：上次接诊未签发就被标"复诊"——上次都没完成怎么算"已复一次"？
    # 新逻辑：用接诊状态机（completed = 至少完成过一次接诊，包含病历签发）
    #   - 患者新建 → 必为初诊
    #   - 患者老 + 有任一 completed 接诊 → 复诊
    #   - 患者老 + 所有接诊都被 cancelled / 还在 in_progress → 仍按初诊
    if not patient_reused:
        is_first_visit = True
    else:
        is_first_visit = not await encounter_service.has_completed_encounter(patient["id"])

    # 取患者档案（档案数据跟随患者，不跟随接诊）
    patient_profile = await patient_service.get_profile(patient["id"])

    # ── pending_encounters：别的医生在这个患者身上留下的进行中接诊（非阻断警示）──
    # 业务场景：值班交接、急诊副班接管，硬拦截会阻断真实业务，所以仅返回列表，
    # 让前端弹 Modal 让医生看到自行决策"继续接诊 / 联系原医生"。
    pending_other = await encounter_service.list_pending_by_other_doctors(
        patient["id"], current_user.id
    )

    # 若该医生对该患者已有进行中的接诊，直接续接，不再新建
    existing = await encounter_service.find_in_progress(patient["id"], current_user.id)
    if existing:
        # 续接时也查上次已签发病历供参考（排除当前续接的接诊本身）
        resume_prev_stmt = (
            select(RecordVersion.content)
            .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
            .join(EncounterModel, MedicalRecord.encounter_id == EncounterModel.id)
            .where(
                EncounterModel.patient_id == patient["id"],
                EncounterModel.id != existing.id,
                RecordVersion.content.isnot(None),
            )
            .order_by(desc(RecordVersion.created_at))
            .limit(1)
        )
        resume_row = (await db.execute(resume_prev_stmt)).scalar_one_or_none()
        resume_prev_content = (resume_row if isinstance(resume_row, dict) else {}).get("text") or None
        # 业务里程碑：自动续接进行中的接诊（避免重复创建）
        logger.info(
            "encounter.quick_start: resumed encounter_id=%s patient_id=%s",
            existing.id, patient["id"],
        )
        return {
            "encounter_id": existing.id,
            "patient": patient,
            "patient_profile": patient_profile,
            "visit_type": existing.visit_type,
            "patient_reused": patient_reused,
            # is_first_visit 取被续接接诊本身存的值，避免前端用 patient_reused 推算
            # 把"上次初诊未签发续接"误显示成"复诊"
            "is_first_visit": existing.is_first_visit,
            "previous_record_content": resume_prev_content,
            "pending_encounters": pending_other,
            "resumed": True,
        }

    encounter = await encounter_service.create(
        EncounterCreate(
            patient_id=patient["id"],
            visit_type=data.visit_type,
            department_id=data.department_id or current_user.department_id,
            is_first_visit=is_first_visit,
            bed_no=data.bed_no,
            admission_route=data.admission_route,
            admission_condition=data.admission_condition,
        ),
        current_user.id,
    )

    # 复诊时查询该患者最近一次接诊的稳定问诊字段 + 病历参考
    previous_record_content: Optional[str] = None
    previous_inquiry: Optional[dict] = None
    if patient_reused:
        # 取最近一次接诊中最新版本问诊的稳定字段（既往史/过敏史/个人史等不随症状变化的信息）
        stable_stmt = (
            select(
                InquiryInput.past_history,
                InquiryInput.allergy_history,
                InquiryInput.personal_history,
                InquiryInput.marital_history,
                InquiryInput.family_history,
            )
            .join(EncounterModel, InquiryInput.encounter_id == EncounterModel.id)
            .where(
                EncounterModel.patient_id == patient["id"],
                EncounterModel.id != encounter.id,
            )
            .order_by(desc(InquiryInput.created_at))
            .limit(1)
        )
        stable_row = (await db.execute(stable_stmt)).one_or_none()
        if stable_row:
            # 只带入非空字段，避免用空字符串覆盖当次新填的内容
            previous_inquiry = {
                k: v for k, v in {
                    "past_history": stable_row.past_history,
                    "allergy_history": stable_row.allergy_history,
                    "personal_history": stable_row.personal_history,
                    "marital_history": stable_row.marital_history,
                    "family_history": stable_row.family_history,
                }.items() if v
            }

        # 取最近一次签发病历版本的全文，供生成时参考
        record_stmt = (
            select(RecordVersion.content)
            .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
            .join(EncounterModel, MedicalRecord.encounter_id == EncounterModel.id)
            .where(
                EncounterModel.patient_id == patient["id"],
                EncounterModel.id != encounter.id,
                RecordVersion.content.isnot(None),
            )
            .order_by(desc(RecordVersion.created_at))
            .limit(1)
        )
        row = (await db.execute(record_stmt)).scalar_one_or_none()
        if row:
            # content 列是 JSONB，quick_save 格式为 {"text": "病历全文..."}
            previous_record_content = (row if isinstance(row, dict) else {}).get("text") or None

    # 业务里程碑：接诊创建（区分初诊/复诊；患者复用与否）
    logger.info(
        "encounter.quick_start: created encounter_id=%s patient_id=%s visit_type=%s first_visit=%s reused=%s",
        encounter.id, patient["id"], data.visit_type, is_first_visit, patient_reused,
    )
    return {
        "encounter_id": encounter.id,
        "patient": patient,
        "patient_profile": patient_profile,
        "visit_type": data.visit_type,
        "patient_reused": patient_reused,
        # 跟 resumed 分支一致地显式返回 is_first_visit，让前端不再用 patient_reused 推算
        "is_first_visit": is_first_visit,
        "previous_record_content": previous_record_content,
        "previous_inquiry": previous_inquiry,
        "pending_encounters": pending_other,
        "resumed": False,
    }
