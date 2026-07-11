# -*- coding: utf-8 -*-
"""
PACS 报告与研究管理子路由（保存/发布报告、患者报告列表、删除研究、工作列表）

从 pacs.py 拆出（Round 6 瘦身）：负责——
  PUT    /{study_id}/report              保存影像报告（body.publish=True 同时签发）
  GET    /patient/{patient_id}/reports   患者已发布报告列表
  DELETE /{study_id}                     删除未发布 study（Orthanc + DB 级联）
  GET    /studies                        影像科工作列表
行为逐字一致，路由路径/方法/依赖零改动。本模块自建 router，由 pacs.py 拼回。
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from datetime import datetime
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.core.authz import PACS_WRITE_ROLES, assert_pacs_write
from app.database import get_db
from app.models.encounter import Encounter
from app.models.imaging import ImagingReport, ImagingStudy
from app.services.orthanc_client import orthanc_client
# Round 5/6：PACS 业务逻辑服务包（渲染缓存/报告 ORM）
from app.services.pacs import render_cache, report_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── 保存 / 发布报告（合并端点） ─────────────────────────────────────────────

class SaveReportRequest(BaseModel):
    """保存影像报告 body。

    - final_report : 报告正文（必填）
    - publish      : True 表示同时签发；False 仅保存草稿
    """
    final_report: str
    publish: bool = False


@router.put("/{study_id}/report")
async def save_report(
    study_id: str,
    body: SaveReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存或同时签发影像报告。

    Audit Round 4 G4：原本拆成 PUT /report（草稿）+ POST /publish（签发）两个端点，
    实际差异只是是否设置 is_published / published_at / published_by 三个字段，
    合并成一个端点更直观——前端只需要传 publish=True 就能签发。

    审计链设计（保持 R1 后行为一致）：
      - radiologist_id : 在 analyze_study 阶段写入，本端点 **绝不覆盖**——
        否则 "A 分析、B 复核签发" 场景会把分析人记成 B。
      - published_by   : 仅在 publish=True 时写入，记录实际签发责任人。
    """
    assert_pacs_write(current_user)
    result = await db.execute(
        select(ImagingReport).where(ImagingReport.study_id == study_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "报告不存在，请先进行 AI 分析")

    report.final_report = body.final_report

    response: dict = {"ok": True}
    if body.publish:
        report.is_published = True
        report.published_at = datetime.utcnow()
        # 关键：只写 published_by，绝不覆盖 radiologist_id（保留分析人审计）
        report.published_by = current_user.id

        study = await db.get(ImagingStudy, study_id)
        if study:
            study.status = "published"

        response["published_at"] = report.published_at.isoformat()

    await db.commit()
    return response


# ─── 获取患者的已发布报告（临床医生用）────────────────────────────────────────

@router.get("/patient/{patient_id}/reports")
async def get_patient_reports(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 普通医生只能访问自己有 encounter 的患者
    if getattr(current_user, "role", "doctor") not in PACS_WRITE_ROLES:
        enc = await db.execute(
            select(Encounter.id).where(
                Encounter.patient_id == patient_id,
                Encounter.doctor_id == current_user.id,
            ).limit(1)
        )
        if not enc.scalar_one_or_none():
            raise HTTPException(403, "无权访问该患者影像资料")

    # 查询 + 序列化已搬至 report_service（行为零改变）
    return await report_service.list_patient_published_reports(db, patient_id)


# ─── 删除影像研究 ───────────────────────────────────────────────────────────

@router.delete("/{study_id}")
async def delete_study(
    study_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除影像研究（含 Orthanc 端 + 业务表 + 报告，不可逆）。

    权限：影像科医生 + 管理员。
    业务约束：
      - 已发布（status=published）的 study **禁止删除**——医疗审计合规要求
        发布报告必须保留追溯链。需要修改请走"撤销发布 → 修改 → 重发布"流程
        （撤销发布功能后续 R2 再做）。
      - 未发布的 study（pending / analyzing / analyzed）允许删除。

    级联删除：
      1. Orthanc 端：调用私有 REST 删除整个 study（含所有 series/instances/files）
      2. ImagingReport：手动 DELETE（避免 ORM cascade 配置遗漏）
      3. ImagingStudy：DELETE
    """
    assert_pacs_write(current_user)
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")

    if study.status == "published":
        raise HTTPException(
            409,
            "已发布的报告不能删除（医疗审计合规要求保留追溯链）。"
            "如需修改，请通过撤销发布流程。",
        )

    # 1) 删 Orthanc 端数据（先删 Orthanc 再删 DB；如果 Orthanc 失败 DB 还在，
    #    保留可重试机会；反之 DB 删了 Orthanc 失败会留孤儿数据）
    if study.study_instance_uid:
        try:
            await orthanc_client.delete_study(study.study_instance_uid)
        except Exception as e:
            logger.error("pacs.delete: orthanc_delete_failed study=%s err=%s", study.study_instance_uid, e)
            raise HTTPException(502, f"Orthanc 数据清理失败，DB 行未删除: {e}")
        # 清 Redis 里该 study 的所有缓存（frames 元数据 + 缩略图 + 高清预览）
        await render_cache.clear_study_cache(study.study_instance_uid)

    # 2) 删 ImagingReport（如有）
    from sqlalchemy import delete as _sql_delete
    await db.execute(
        _sql_delete(ImagingReport).where(ImagingReport.study_id == study_id)
    )

    # 3) 删 ImagingStudy
    await db.delete(study)
    await db.commit()

    return {"ok": True, "deleted_study_id": study_id}


# ─── 获取影像科工作列表 ──────────────────────────────────────────────────────

@router.get("/studies")
async def list_studies(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 只有放射科医生和管理员可查看全部影像列表
    if getattr(current_user, "role", "doctor") not in PACS_WRITE_ROLES:
        raise HTTPException(403, "仅放射科医生可访问影像列表")

    # 查询 + 序列化已搬至 report_service（行为零改变）
    return await report_service.list_studies_data(db, status)
