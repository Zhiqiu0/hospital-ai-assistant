# -*- coding: utf-8 -*-
"""病历·读路径路由（api/v1/medical_records_read.py，2026-09-19 读写两拆）。

纯机械搬移，零逻辑改动（497 行超路由文件合理规模）。本文件只放查询类
端点：draft-by-type / by-patient / my-returned / 详情 / versions。
⚠ 路由注册顺序不可打乱：/draft-by-type、/my-returned 这类具体路径必须
先于 /{record_id} 通配注册，否则会被当成 record_id 吞掉——本文件保持
拆分前的原始相对顺序，新增端点时想清楚往哪个位置插。
写路径见 medical_records_write.py；聚合挂载在 medical_records.py。
"""
# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.authz import assert_encounter_access
from app.core.security import get_current_user
from app.database import get_db
from app.models.medical_record import MedicalRecord, RecordVersion
from app.schemas.medical_record import (
    MedicalRecordResponse,
)
from app.services.audit_service import log_action
from app.services.medical_record_service import MedicalRecordService

router = APIRouter()


@router.get("/draft-by-type")
async def get_draft_by_type(
    encounter_id: str = Query(...),
    record_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """按 (接诊, 文书类型) 查最新一份病历草稿/签发内容。

    2026-08-21 第四轮走查：住院切文书类型时前端只认本地缓存，服务端明明有该
    类型的草稿却显示空编辑器——医生会以为入院记录丢了，甚至重写一份覆盖。
    workspace 快照只回 active_record（updated_at 最新的一行），拿不到指定类型。

    返回 {"exists": false} 而非 404：切到还没写过的文书类型是常态，不该在
    浏览器 console 留一条红色 404。
    """
    # 归属校验口径与 auto_save_draft 相同：只能读自己接诊下的草稿
    await assert_encounter_access(db, encounter_id, current_user)
    row = (await db.execute(
        select(MedicalRecord)
        .where(
            MedicalRecord.encounter_id == encounter_id,
            MedicalRecord.record_type == record_type,
        )
        .order_by(MedicalRecord.updated_at.desc())
    )).scalars().first()
    if row is None:
        return {"exists": False}
    version = (await db.execute(
        select(RecordVersion).where(
            RecordVersion.medical_record_id == row.id,
            RecordVersion.version_no == row.current_version,
        )
    )).scalar_one_or_none()
    content = (version.content or {}).get("text", "") if version else ""
    return {
        "exists": True,
        "record_id": row.id,
        "status": row.status,
        "content": content,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "submitted_at": row.submitted_at.isoformat() if getattr(row, "submitted_at", None) else None,
    }


@router.get("/by-patient/{patient_id}")
async def list_by_patient(
    patient_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """查询某患者的全部已签发病历（门诊/急诊/住院），任意登录医生可读。

    权限设计：
      已签发病历是医院共享医疗数据，任意登录医生为诊疗目的均可查阅
      （初诊/复诊可能不同医生，复诊看历史是刚需）。本接口不做接诊关系拦截。
      写入仍受限：只能改自己开的接诊/病历——save_content 走 join(Encounter.doctor_id)
      校验，quick_save / auto_save_draft 在路由层 assert_encounter_access 校验。
      合规：每次查阅都写审计日志（action='view_records'），admin 可在
      "操作日志"页面追溯任何医生何时查阅了哪个患者，符合等保 2.0 三级要求。

      角色收口（2026-08-29 第六轮渗透审计）：注释一直写的是"任意登录**医生**"，
      实现却放行全部角色——科室质控员本被 /qc/* 的 _dept_scope 限在本科室，
      经此端点却能读全院任意患者全文，科室隔离被架空。按声明收紧到
      医生 + 管理角色；qc_officer/nurse/radiologist 的病历读取走各自专属通道。
    """
    from app.core.authz import ADMIN_ROLES
    if getattr(current_user, "role", None) not in {"doctor", *ADMIN_ROLES}:
        raise HTTPException(status_code=403, detail="仅医生可查阅患者历史病历")
    await log_action(
        action="view_records",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="patient_record",
        resource_id=patient_id,
        detail=f"查阅患者 {patient_id} 的全部签发病历列表（page={page}）",
    )
    service = MedicalRecordService(db)
    return await service.list_by_patient(patient_id, page, page_size)



@router.get("/my-returned")
async def my_returned_records(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """当前医生被质控退回待整改的文书清单（2026-08-22 退回闭环）。

    口径：本医生接诊下的已签发文书，其**最新一条复核结论为 returned**，且
    退回之后没有再签发过同接诊同类型的文书。住院重签不覆盖旧文书而是
    新建一份（record_no 递增，见 _medical_record_sign），所以"整改完成"
    的判据必须落在 (encounter, record_type) 维度而不是单条 record 上：
    只要退回时间之后签发过同类型文书（同条覆盖或新建皆可），即视为已
    整改自动出清单——新文书会重新进入质控复核队列，语义互为镜像。
    """
    from sqlalchemy import func
    from sqlalchemy.orm import aliased

    from app.models.encounter import Encounter
    from app.models.medical_record import QCReview

    # 同接诊同类型的"另一份/同一份"文书别名，用于判定退回后是否已重签
    resigned = aliased(MedicalRecord)

    latest_review_at = (
        select(
            QCReview.medical_record_id.label("rid"),
            func.max(QCReview.created_at).label("mx"),
        )
        .group_by(QCReview.medical_record_id)
        .subquery()
    )
    from app.models.patient import Patient

    rows = (await db.execute(
        select(MedicalRecord, QCReview, Encounter, Patient)
        .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
        .join(Patient, Encounter.patient_id == Patient.id)
        .join(latest_review_at, latest_review_at.c.rid == MedicalRecord.id)
        .join(QCReview, (QCReview.medical_record_id == MedicalRecord.id)
              & (QCReview.created_at == latest_review_at.c.mx))
        .where(
            Encounter.doctor_id == current_user.id,
            QCReview.conclusion == "returned",
            # 退回后又签发过同接诊同类型文书（含同条覆盖与住院新建）→ 已整改出清单
            ~select(resigned.id).where(
                resigned.encounter_id == MedicalRecord.encounter_id,
                resigned.record_type == MedicalRecord.record_type,
                resigned.submitted_at > QCReview.created_at,
            ).exists(),
            # 门急诊整改通道 = 管理员修订（2026-08-28 口径对拍修复）：修订只建
            # RecordVersion(source=admin_revise) 不动 submitted_at，原判据认不出
            # → 横幅永不消失。退回后存在更晚的管理员修订版本同样视为已整改。
            ~select(RecordVersion.id).where(
                RecordVersion.medical_record_id == MedicalRecord.id,
                RecordVersion.source == "admin_revise",
                RecordVersion.created_at > QCReview.created_at,
            ).exists(),
        )
        .order_by(QCReview.created_at.desc())
        .limit(50)
    )).all()
    return [
        {
            "record_id": rec.id,
            "encounter_id": enc.id,
            "record_type": rec.record_type,
            "visit_type": enc.visit_type,
            "patient_id": enc.patient_id,
            # 患者姓名与就诊时间（2026-09-02 质控闭环实测补）：原先只给
            # record_type + 整改意见 + 复核人，医生一天看几十个门诊病人，
            # 提醒里说不出是哪一位——想整改只能凭复核时间倒推，或挨个翻历史
            # 病历。整改意见本身也常是"现病史过简"这类通用措辞，认不出人。
            "patient_name": pat.name,
            "visited_at": enc.visited_at.isoformat() if enc.visited_at else None,
            "returned_at": rv.created_at.isoformat(),
            "reviewer_name": rv.reviewer_name,
            "comment": rv.comment,
        }
        for rec, rv, enc, pat in rows
    ]


@router.get("/{record_id}", response_model=MedicalRecordResponse)
async def get_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = MedicalRecordService(db)
    return await service.get_by_id(record_id, doctor_id=current_user.id)



@router.get("/{record_id}/versions")
async def get_record_versions(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = MedicalRecordService(db)
    # 先校验归属权，再读版本列表
    await service.get_by_id(record_id, doctor_id=current_user.id)
    return await service.get_versions(record_id)


