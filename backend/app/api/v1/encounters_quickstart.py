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
from app.core.authz import assert_can_write_record
from app.core.security import get_current_user
from app.core.logging_config import mask_name
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
    # 角色守卫（2026-08-14 第六轮审计修复）：本端点会把 current_user 设为接诊医生，
    # 原先只要求登录——护士自建接诊后就成了"接诊医生"，后续病历署名落到护士头上，
    # 违反医院"病历署名必须是接诊医生本人"的硬要求。
    assert_can_write_record(current_user)
    # 解析出生日期（前端统一传 YYYY-MM-DD），格式无效则忽略，patient 仍可创建
    birth_date_val: Optional[date] = None
    if data.birth_date:
        try:
            birth_date_val = date.fromisoformat(data.birth_date)
        except ValueError:
            # 记的是**非法**的原始输入（如 "1990/13/45"），用于排查前端或 HIS
            # 传了什么格式；非法值本身不构成可识别信息。截断防超长串刷屏。
            logger.warning("encounter.quick_start: invalid birth_date=%r ignored",
                           str(data.birth_date)[:20])

    patient_service = PatientService(db)

    # 同名同生日的候选档案（非阻断提示，交前端让医生确认是不是同一人）
    similar_patients: list[dict] = []

    # 前端传入已知患者 ID 时（复诊场景）直接复用，跳过模糊匹配
    if data.patient_id:
        patient = await patient_service.get_by_id(data.patient_id)
        patient_reused = True
    else:
        # allow_weak_match=False（2026-08-14 第七轮审计修复）：
        # 原先这里用默认值 True，「姓名+出生日期」命中就**静默复用**别人的档案，
        # 紧接着 get_profile 把那个人的过敏史/既往史预填进表单。医生看到"系统
        # 已有资料"通常不会逐条核对，按别人的过敏史用药可能致命，病历也写进了
        # 错误的档案。同名同生日在几万份档案里是必然会撞的。
        # 现在弱键改成非阻断提示：强键没命中就新建档案（重复档案可事后人工合并，
        # 误合并两个人不可逆），同时把候选人返回前端让医生自己认。
        patient = await patient_service.find_existing(
            id_card=data.id_card,
            phone=data.phone,
            name=data.patient_name,
            birth_date=birth_date_val,
            allow_weak_match=False,
        )
        patient_reused = patient is not None
        if not patient:
            similar_patients = await patient_service.find_weak_candidates(
                name=data.patient_name, birth_date=birth_date_val
            )
            if similar_patients:
                # 姓名脱敏入日志（2026-09-02 可观测性专项）：app.log 保留 30 天，
                # 而本项目既定口径是日志里用 ID 不用姓名（审计日志 detail 全是
                # UUID）。这条日志的价值在于知道"发生了同名查重"，首字足够运维
                # 在几个候选里对上号，全名则是没有必要的个人信息留存。
                logger.info(
                    "encounter.quick_start: 同名同生日候选 %d 位，已交前端确认 name=%s",
                    len(similar_patients), mask_name(data.patient_name),
                )

    if not patient:
        # commit=False（2026-08-14 第八轮审计修复）：与 admit_service 同一约定
        # ——「建患者与建接诊合并为同一事务，接诊失败不留孤儿档案」。
        # 原先这里默认 commit=True 先把患者提交掉，随后还要跑复诊判断、取档案、
        # 写审计日志（另开会话写库），最后才建接诊。这中间任一环节失败，
        # 结果就是患者档案已落库、接诊没建成；医生看到报错重试，而如果这位患者
        # 既没身份证也没手机号（老人、无证儿童、代挂号，都很常见），
        # find_existing 的强键全 miss、弱键又在第七轮被有意禁用，
        # 重试就再建一份档案——同一个人散成多份，正是第七轮刚修过的痛点。
        patient = await patient_service.create(commit=False, data=PatientCreate(
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

    # PHI 查阅留痕（2026-08-13 第三轮审计修复）：本端点返回完整患者信息 + 完整
    # 纵向档案，与 GET /patients/{id} 同等敏感，原先零审计。归属校验放开后审计
    # 是唯一的追责手段，留一条不留痕的旁路等于把那道防线作废。
    from app.services.audit_service import log_action
    await log_action(
        action="view_patient",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="patient", resource_id=patient["id"],
        detail="接诊开始时调阅患者完整信息与纵向档案（quick-start）",
    )

    # ── pending_encounters：别的医生在这个患者身上留下的进行中接诊（非阻断警示）──
    # 业务场景：值班交接、急诊副班接管，硬拦截会阻断真实业务，所以仅返回列表，
    # 让前端弹 Modal 让医生看到自行决策"继续接诊 / 联系原医生"。
    pending_other = await encounter_service.list_pending_by_other_doctors(
        patient["id"], current_user.id
    )

    # 若该医生对该患者已有**同类型**进行中的接诊，直接续接，不再新建。
    # 必须同类型：门诊未签发的接诊不能被急诊续接，否则急诊病历会落进门诊接诊，
    # 质控用错评分表、回写 HIS 的类型也错（2026-08-13 第五轮审计修复）。
    existing = await encounter_service.find_in_progress(
        patient["id"], current_user.id, visit_type=data.visit_type
    )
    if existing:
        # 续接时也查上次已签发病历供参考（排除当前续接的接诊本身）。
        # 过滤条件同新建分支，理由见下方注释。
        resume_prev_stmt = (
            select(RecordVersion.content)
            .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
            .join(EncounterModel, MedicalRecord.encounter_id == EncounterModel.id)
            .where(
                EncounterModel.patient_id == patient["id"],
                EncounterModel.id != existing.id,
                EncounterModel.visit_type == existing.visit_type,
                MedicalRecord.status == "submitted",
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
            # 同名同生日候选（第七轮审计）：仅提示，前端弹框让医生确认是否同一人
            "similar_patients": similar_patients,
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

        # 取最近一次**已签发**病历版本的全文，供生成时参考。
        #
        # 三个过滤条件缺一不可（2026-08-14 第六轮审计修复）：原查询只按患者过滤，
        # 于是带进来的可能是——
        #   · 未签发的草稿（别人写了一半的东西被当成"上次病历"参考）
        #   · 门诊病历（住院接诊却带入门诊内容）
        #   · 其他医生的病历
        # 注释一直写着"最近一次签发病历"，但代码里从来没有这个条件。
        record_stmt = (
            select(RecordVersion.content)
            .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
            .join(EncounterModel, MedicalRecord.encounter_id == EncounterModel.id)
            .where(
                EncounterModel.patient_id == patient["id"],
                EncounterModel.id != encounter.id,
                # 只参考同类型接诊：住院不带门诊内容，反之亦然
                EncounterModel.visit_type == data.visit_type,
                # 只参考已签发的正式病历，不带任何人的草稿
                MedicalRecord.status == "submitted",
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
        # 同名同生日候选（第七轮审计）：仅提示，前端弹框让医生确认是否同一人。
        # 新建分支才是真正会出现候选的场景（续接说明患者早就定了）。
        "similar_patients": similar_patients,
        "resumed": False,
    }
