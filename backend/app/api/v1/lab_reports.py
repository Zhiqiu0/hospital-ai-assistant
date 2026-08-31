"""
检验报告路由（/api/v1/lab-reports/*）

端点：
  POST   /upload             上传并 OCR（PDF/图片 → 结构化文本）
  GET    /?encounter_id=X    列出某接诊的报告
  DELETE /{report_id}        删除报告（先鉴权）

OCR 业务和 SQL 全在 services/lab_reports_service.py；本文件仅做请求/响应/鉴权。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.authz import assert_encounter_access
from app.core.upload_limits import MAX_LAB_BYTES, read_upload_capped
from app.database import get_db
from app.services import lab_reports_service
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)

router = APIRouter()


def _report_to_dict(r) -> dict:
    return {
        "id": r.id,
        "original_filename": r.original_filename,
        "ocr_text": r.ocr_text,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/upload")
async def upload_lab_report(
    file: UploadFile = File(...),
    encounter_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """上传检验报告（PDF/图片），自动调 OCR。"""
    if file.content_type not in lab_reports_service.ALLOWED_TYPES:
        raise HTTPException(400, "仅支持 JPG / PNG / WEBP / PDF 格式")
    if encounter_id:
        await assert_encounter_access(db, encounter_id, current_user)
    # 孤儿写角色收口（2026-08-29 第七轮渗透审计）：不带 encounter_id 时
    # 原先只要登录即可写入并触发付费 OCR/ASR——nurse/qc_officer 等只读
    # 角色不该有此面。带 encounter_id 的路径由归属校验兜底（医生本人）。
    if not encounter_id:
        from app.core.authz import RECORD_WRITE_ROLES
        if getattr(current_user, "role", None) not in RECORD_WRITE_ROLES:
            raise HTTPException(status_code=403, detail="仅医生可上传")

    # 分块读 + 超 20MB 即 413
    content = await read_upload_capped(file, MAX_LAB_BYTES)
    report = await lab_reports_service.process_and_create_report(
        db,
        content=content,
        filename=file.filename,
        mime_type=file.content_type,
        encounter_id=encounter_id,
        doctor_id=current_user.id,
    )
    # 业务里程碑：检验报告上传成功（含 OCR 状态，便于复盘 OCR 失败率）
    logger.info(
        "lab_report.upload: ok report_id=%s encounter_id=%s mime=%s size=%d ocr_status=%s",
        report.id, encounter_id, file.content_type, len(content), report.status,
    )
    return _report_to_dict(report)


@router.get("/")
async def list_lab_reports(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """列出某接诊的所有检验报告。"""
    await assert_encounter_access(db, encounter_id, current_user)
    reports = await lab_reports_service.list_reports(db, encounter_id)
    return [_report_to_dict(r) for r in reports]


@router.delete("/{report_id}")
async def delete_lab_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除检验报告（通过 encounter_id 反查权限）。

    合规约束（2026-08-31 法规逐条对照审计）：检验报告是**客观病历资料**，
    《医疗纠纷预防和处理条例》明令不得隐匿、销毁；《电子病历应用管理规范》
    第二十四条要求门诊病历至少保存 15 年。而本端点此前是**硬删除**（磁盘原图
    连同数据库行一起没），且是全仓唯一一类既不可逆、又完全不留审计痕迹的操作。

    典型出事场景：病历正文写着"血常规示 WBC 12.3×10⁹/L 支持感染诊断"，
    对应化验单原图被某位轮转医生误删。三年后发生纠纷，法院要求提交客观检验
    资料——文件和数据库行都不在了，审计日志里也查不到任何人删过它，医院既拿不
    出证据，也说不清是谁销毁的。

    这里补两道，与 PACS 报告删除（pacs_reports.py 已发布报告 409 拒删）对齐：
      ① 该接诊已有签发病历时拒删——病历一旦成为正式病案，它依据的客观资料
         就不能再销毁；
      ② 无论成功与否都写审计日志，删除必须留痕。
    """
    report = await lab_reports_service.get_report(db, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    if report.encounter_id:
        await assert_encounter_access(db, report.encounter_id, current_user)
        # ① 已签发病历的客观资料不得销毁
        from sqlalchemy import select

        from app.models.medical_record import MedicalRecord
        signed = (await db.execute(
            select(MedicalRecord.id).where(
                MedicalRecord.encounter_id == report.encounter_id,
                MedicalRecord.status == "submitted",
            ).limit(1)
        )).scalar_one_or_none()
        if signed:
            await log_action(
                action="delete_lab_report",
                user_id=current_user.id,
                user_name=getattr(current_user, "real_name", None)
                or getattr(current_user, "username", None),
                user_role=getattr(current_user, "role", None),
                resource_type="lab_report",
                resource_id=report_id,
                detail=f"删除被拒（该接诊病历已签发）接诊ID：{report.encounter_id}",
                status="denied",
            )
            raise HTTPException(
                409,
                "该接诊的病历已签发，检验报告作为客观病历资料不能删除"
                "（医疗纠纷预防和处理条例要求保留）。如报告有误，请联系管理员处理。",
            )
    else:
        # 孤儿报告（未挂接诊）原先直接放行删除（2026-08-13 第二轮审计修复）：
        # 任何登录医生可删任意孤儿报告，且删除不可撤销。收紧为仅上传者本人或
        # 管理员——普通医生删不到别人传的报告。
        from app.core.authz import ADMIN_ROLES
        owner_id = getattr(report, "uploaded_by", None) or getattr(report, "doctor_id", None)
        is_admin = getattr(current_user, "role", "") in ADMIN_ROLES
        if not is_admin and (owner_id is None or str(owner_id) != str(current_user.id)):
            raise HTTPException(403, "无权删除该检验报告（非本人上传）")
    # ② 先取待记录的信息再删——删完 report 对象的属性就取不到了
    _detail = (f"删除检验报告 {getattr(report, 'original_filename', None) or report_id}，"
               f"接诊ID：{report.encounter_id or '(无)'}")
    await lab_reports_service.delete_report(db, report)
    await log_action(
        action="delete_lab_report",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None)
        or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="lab_report",
        resource_id=report_id,
        detail=_detail,
    )
    return {"ok": True}
