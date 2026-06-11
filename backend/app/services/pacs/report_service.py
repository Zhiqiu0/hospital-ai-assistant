# -*- coding: utf-8 -*-
# 2026-06-11 Round 5 迁移：以下函数从 app/api/v1/pacs.py 路由体内原样搬入（纯函数搬家，行为零改变）
"""
PACS 影像报告 ORM 服务（services/pacs/report_service.py）

职责（纯 DB 查询 / 状态流转，不抛 HTTPException——鉴权与 404/403 判断留在路由层）：
  - AI 分析结果落库（ImagingReport upsert + study 状态流转 → analyzed）
  - 患者已发布报告列表查询（临床医生用）
  - 影像科工作列表查询（放射科医生 / 管理员用）

未搬入本文件的部分（刻意保留在路由层）：
  - save_report（保存/签发）：与 HTTPException 404 + publish 响应组装耦合紧
  - delete_study（级联删除）：Orthanc 删除失败时抛 502 的顺序语义与路由强耦合
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imaging import ImagingReport, ImagingStudy


async def upsert_analysis_report(
    db: AsyncSession,
    study: ImagingStudy,
    study_id: str,
    selected: list[str],
    ai_result: str,
    radiologist_id: str,
) -> None:
    """AI 分析结果保存到数据库（unique 约束保证一个 study 至多一条 report）。

    - 已有 report → 覆盖 selected_frames / ai_analysis / final_report
      （radiologist_id 不覆盖：保留首次分析人审计链）
    - 没有 report → 新建，radiologist_id 记当前分析人
    - study 状态流转为 analyzed，最后统一 commit
    """
    result = await db.execute(select(ImagingReport).where(ImagingReport.study_id == study_id))
    report = result.scalar_one_or_none()

    if report:
        report.selected_frames = selected
        report.ai_analysis = ai_result
        report.final_report = ai_result
    else:
        report = ImagingReport(
            study_id=study_id,
            radiologist_id=radiologist_id,
            selected_frames=selected,
            ai_analysis=ai_result,
            final_report=ai_result,
        )
        db.add(report)

    study.status = "analyzed"
    await db.commit()


async def list_patient_published_reports(
    db: AsyncSession,
    patient_id: str,
) -> list[dict]:
    """查询某患者所有已发布（status=published）的影像报告，按创建时间倒序。

    左连接 ImagingReport（理论上 published 必有报告，isouter 防御历史脏数据），
    序列化为前端列表所需的精简字段。权限校验由路由层完成。
    """
    result = await db.execute(
        select(ImagingStudy, ImagingReport)
        .join(ImagingReport, ImagingReport.study_id == ImagingStudy.id, isouter=True)
        .where(ImagingStudy.patient_id == patient_id)
        .where(ImagingStudy.status == "published")
        .order_by(ImagingStudy.created_at.desc())
    )
    rows = result.all()
    return [
        {
            "study_id": s.id,
            "modality": s.modality,
            "body_part": s.body_part,
            "series_description": s.series_description,
            "total_frames": s.total_frames,
            "created_at": s.created_at.isoformat(),
            "final_report": r.final_report if r else None,
            "published_at": r.published_at.isoformat() if r and r.published_at else None,
        }
        for s, r in rows
    ]


async def list_studies_data(
    db: AsyncSession,
    status: Optional[str] = None,
) -> list[dict]:
    """影像科工作列表：全部 ImagingStudy 按创建时间倒序，可按状态过滤。

    序列化为前端工作列表所需字段。权限校验（仅放射科/管理员）由路由层完成。
    """
    q = select(ImagingStudy).order_by(ImagingStudy.created_at.desc())
    if status:
        q = q.where(ImagingStudy.status == status)
    result = await db.execute(q)
    studies = result.scalars().all()
    return [
        {
            "study_id": s.id,
            "patient_id": s.patient_id,
            "modality": s.modality,
            "body_part": s.body_part,
            "series_description": s.series_description,
            "total_frames": s.total_frames,
            "status": s.status,
            "created_at": s.created_at.isoformat(),
        }
        for s in studies
    ]
