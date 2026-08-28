# -*- coding: utf-8 -*-
"""病历复核端点（api/v1/qc/reviews.py，2026-08-21 阶段4）

  GET  /qc/review-queue          待复核清单（已签发、按最新复核结论过滤）
  GET  /qc/records/{record_id}   复核查看（只读全文 + 患者/接诊上下文）
  POST /qc/reviews               提交复核结论（通过/退回）
  GET  /qc/reviews/{record_id}   某文书的复核历史

权限：路由树级 require_qc_officer（见 __init__）；科室质控员
（user.department_id 非空）只看/只复核本科室接诊——与方案"科主任为本科室
病案质量第一责任人、科室质控员自查"一致；院级质控员/管理员不限科室。
每次复核写审计日志（等保三级口径与 admin 一致）。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, QCReview, RecordVersion
from app.models.patient import Patient
from app.services.audit_service import log_action

router = APIRouter()


def _dept_scope(current_user) -> Optional[str]:
    """科室质控员限本科室；院级（无科室）/管理员不限。"""
    if current_user.role == "qc_officer":
        return getattr(current_user, "department_id", None) or None
    return None


@router.get("/review-queue")
async def review_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """待复核清单：已签发且（从未复核 或 最新复核=退回后医生已重签）的文书。

    口径：按 medical_record 维度；"待复核" = 无复核记录，或最新复核结论早于
    最新签发时间（退回后医生修订重签，需要再次复核）。
    """
    dept = _dept_scope(current_user)

    # 最新复核时间/结论子查询
    latest_review = (
        select(
            QCReview.medical_record_id,
            func.max(QCReview.created_at).label("last_review_at"),
        )
        .group_by(QCReview.medical_record_id)
        .subquery()
    )

    stmt = (
        select(MedicalRecord, Encounter, Patient, latest_review.c.last_review_at)
        .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
        .join(Patient, Encounter.patient_id == Patient.id)
        .outerjoin(latest_review, latest_review.c.medical_record_id == MedicalRecord.id)
        .where(
            MedicalRecord.status == "submitted",
            MedicalRecord.submitted_at.isnot(None),
            # 待复核：从未复核，或最新复核早于最新签发（修订重签需再核）
            (latest_review.c.last_review_at.is_(None))
            | (latest_review.c.last_review_at < MedicalRecord.submitted_at),
        )
        .order_by(desc(MedicalRecord.submitted_at))
    )
    if dept:
        stmt = stmt.where(Encounter.department_id == dept)

    rows = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    total = (await db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )).scalar() or 0

    return {
        "total": total,
        "items": [
            {
                "record_id": rec.id,
                "encounter_id": enc.id,
                "record_type": rec.record_type,
                "record_no": rec.record_no,
                "patient_name": pat.name,
                "patient_gender": pat.gender,
                "visit_type": enc.visit_type,
                "department_id": enc.department_id,
                "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
                # 出院后 24h 复核时限参考（方案口径；未办出院显示 null）
                "discharged_at": enc.completed_at.isoformat() if enc.completed_at else None,
            }
            for rec, enc, pat, _ in rows
        ],
    }


@router.get("/records/{record_id}")
async def review_record_detail(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """复核查看：文书全文（只读）+ 患者/接诊上下文 + 复核历史。

    每次查阅写审计（质控员看的是他人病历，等保三级要求可追溯）。
    """
    rec = await db.get(MedicalRecord, record_id)
    # 只允许查看已签发文书（2026-08-28 体检修复）：复核队列只列 submitted，
    # 但详情端点原先接受任意 id——质控员可读到医生仍在撰写的草稿全文
    # （含 AI 生成未复核内容），越出复核所需最小信息面
    if rec is None or rec.status != "submitted":
        raise HTTPException(status_code=404, detail="病历不存在或尚未签发")
    enc = await db.get(Encounter, rec.encounter_id) if rec.encounter_id else None
    dept = _dept_scope(current_user)
    if dept and (enc is None or enc.department_id != dept):
        raise HTTPException(status_code=403, detail="仅可查看本科室病历")
    patient = await db.get(Patient, enc.patient_id) if enc and enc.patient_id else None
    version = (await db.execute(
        select(RecordVersion).where(
            RecordVersion.medical_record_id == rec.id,
            RecordVersion.version_no == rec.current_version,
        )
    )).scalar_one_or_none()
    content = (version.content or {}).get("text", "") if version else ""

    await log_action(
        action="qc_review_view",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        resource_id=record_id,
        detail=f"质控复核查阅病历（患者 {patient.name if patient else '?'}）",
    )
    reviews = (await db.execute(
        select(QCReview).where(QCReview.medical_record_id == record_id)
        .order_by(desc(QCReview.created_at))
    )).scalars().all()
    return {
        "record_id": rec.id,
        "record_type": rec.record_type,
        "status": rec.status,
        "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
        "content": content,
        "patient": {
            "name": patient.name if patient else "",
            "gender": patient.gender if patient else "",
        },
        "reviews": [
            {
                "reviewer_name": r.reviewer_name,
                "conclusion": r.conclusion,
                "comment": r.comment,
                "created_at": r.created_at.isoformat(),
            }
            for r in reviews
        ],
    }


class ReviewSubmit(BaseModel):
    """复核提交入参。"""

    medical_record_id: str
    conclusion: str  # passed / returned
    # 上限 2000 字（2026-08-28 体检）：意见会整段进 audit_logs.detail 并经
    # /my-returned 原样下发医生端，不设限时一次粘贴可产生 MB 级审计行
    comment: Optional[str] = Field(None, max_length=2000)

    @field_validator("conclusion")
    @classmethod
    def _check_conclusion(cls, v: str) -> str:
        if v not in ("passed", "returned"):
            raise ValueError("conclusion 必须是 passed 或 returned")
        return v


@router.post("/reviews")
async def submit_review(
    data: ReviewSubmit,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """提交复核结论；退回必须附整改意见。"""
    if data.conclusion == "returned" and not (data.comment or "").strip():
        raise HTTPException(status_code=422, detail="退回整改必须填写整改意见")
    rec = await db.get(MedicalRecord, data.medical_record_id)
    if rec is None or rec.status != "submitted":
        raise HTTPException(status_code=404, detail="病历不存在或尚未签发")
    enc = await db.get(Encounter, rec.encounter_id) if rec.encounter_id else None
    dept = _dept_scope(current_user)
    if dept and (enc is None or enc.department_id != dept):
        raise HTTPException(status_code=403, detail="仅可复核本科室病历")

    # 幂等防重（2026-08-28 体检）：双击提交/复核"已是最新同结论"的文书时
    # 直接返回既有复核，不再插行——stats 的复核数按行计数，重复插入会虚增
    # 月度通报指标。判据：最新一条复核结论相同且晚于当前签发时间（重签后
    # 允许再核，与队列口径一致）。
    latest = (await db.execute(
        select(QCReview).where(QCReview.medical_record_id == rec.id)
        .order_by(QCReview.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if (latest is not None and latest.conclusion == data.conclusion
            and (latest.comment or "") == ((data.comment or "").strip() or "")
            and rec.submitted_at is not None
            and latest.created_at >= rec.submitted_at):
        return {"ok": True, "review_id": latest.id, "duplicate": True}

    review = QCReview(
        medical_record_id=rec.id,
        encounter_id=rec.encounter_id,
        reviewer_id=current_user.id,
        reviewer_name=getattr(current_user, "real_name", None) or current_user.username,
        conclusion=data.conclusion,
        comment=(data.comment or "").strip() or None,
        created_at=datetime.now(),
    )
    db.add(review)
    await db.commit()

    await log_action(
        action="qc_review_submit",
        user_id=current_user.id,
        user_name=review.reviewer_name,
        user_role=current_user.role,
        resource_type="medical_record",
        resource_id=rec.id,
        detail=f"复核结论：{'通过' if data.conclusion == 'passed' else '退回整改'}"
        + (f"（{review.comment}）" if review.comment else ""),
    )
    return {"ok": True, "review_id": review.id}
