"""
病历路由（/api/v1/medical-records/*）

端点列表：
  POST   /auto-save-draft         编辑器 5 秒防抖自动保存草稿
  POST   /quick-save              签发并快速保存病历
  GET    /by-patient/{patient_id} 查询某患者的全部已签发病历
  POST   /                        标准创建病历记录
  GET    /{record_id}             查询单条病历
  PUT    /{record_id}/content     保存病历内容
  GET    /{record_id}/versions    获取历史版本列表

历史说明（2026-08-12 清理）：
  旧范式 AI 路由 /{record_id}/generate|continue|polish 与 /{record_id}/qc/scan
  已删除——前端早已全量切到 /ai/quick-* 系列（record_gen_v2 + qc_stream），
  旧路由零调用方且零测试覆盖；qc/scan 还硬编码门诊 rubric，住院病历会被
  错误标准评分。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.authz import assert_can_write_record, assert_encounter_access
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.medical_record import (
    AutoSaveDraftRequest,
    MedicalRecordCreate,
    MedicalRecordResponse,
    QuickSaveRequest,
    RecordContentUpdate,
    RecordExportAudit,
)
from app.services.audit_service import log_action
from app.services.medical_record_service import MedicalRecordService

router = APIRouter()


@router.post("/auto-save-draft")
async def auto_save_draft(
    data: AutoSaveDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """编辑器 auto-save：5 秒防抖触发，UPSERT 当前 draft 版本，不爆版本号。

    返回 updated_at 让前端下次调用带回作为乐观锁凭证。
    409 表示多设备冲突（罕见，单医生单设备不会触发）。
    """
    # 归属校验：只能给自己的接诊自动保存草稿，防止越权写他人接诊病历
    # 角色守卫（2026-08-14 第六轮审计修复）：原先病历写端点只要求登录，
    # nurse/radiologist 与 doctor 权限完全等同——护士能写病历、签发，
    # 签发还会自动回写 HIS，署名落到护士头上，直接违反医院"病历署名必须是
    # 接诊医生本人"的硬要求。
    assert_can_write_record(current_user)
    await assert_encounter_access(db, data.encounter_id, current_user)

    # 把接诊维度写入 RequestContext（上游若有 AI 调用能用到，与 quick-generate 行为一致）
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(encounter_id=data.encounter_id)

    service = MedicalRecordService(db)
    return await service.auto_save_draft(
        encounter_id=data.encounter_id,
        record_type=data.record_type,
        content=data.content,
        user_id=current_user.id,
        expected_updated_at=data.expected_updated_at,
        # 记录时间（临床相关时点，住院文书用；见 services/record_time.py）
        recorded_at=data.recorded_at,
    )


@router.post("/quick-save")
async def quick_save_record(
    data: QuickSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """签发时快速保存病历到数据库"""
    # 归属校验：只能签发自己的接诊，防止越权在他人接诊上签发/篡改病历
    # 角色守卫（2026-08-14 第六轮审计修复）：原先病历写端点只要求登录，
    # nurse/radiologist 与 doctor 权限完全等同——护士能写病历、签发，
    # 签发还会自动回写 HIS，署名落到护士头上，直接违反医院"病历署名必须是
    # 接诊医生本人"的硬要求。
    assert_can_write_record(current_user)
    await assert_encounter_access(db, data.encounter_id, current_user)
    service = MedicalRecordService(db)
    try:
        record = await service.quick_save(
            encounter_id=data.encounter_id,
            record_type=data.record_type,
            content=data.content,
            doctor_id=current_user.id,
        )
    except ValueError as exc:
        # 状态守卫拒签（接诊已取消/不存在）→ 409，与前端约定一致
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await log_action(
        action="sign_record",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="medical_record",
        resource_id=record.id,
        detail=f"签发病历，类型：{data.record_type}，接诊ID：{data.encounter_id}",
    )
    # HIS 联动（2026-08-11）：HIS 推送来源的接诊，签发即自动触发回写（后台派发，
    # 不阻塞签发响应；结果经 SSE 推回工作台弹提示）。普通 SaaS 接诊不受影响。
    his_writeback = None
    from app.config import settings as app_settings
    if app_settings.his_adapter_enabled:
        from app.models.encounter import Encounter
        enc = await db.get(Encounter, data.encounter_id)
        if enc is not None and enc.his_external_ref:
            # 用 bg_tasks.spawn 持有引用（2026-08-11 审计延期项）：裸 create_task
            # 只被弱引用，签发响应返回后本地无引用，任务可能被 GC 中途取消致回写丢失。
            from app.his_adapter.bg_tasks import spawn
            from app.his_adapter.writeback_dispatch import dispatch_writeback
            spawn(dispatch_writeback(enc.id, current_user.id, enc.visit_no or ""),
                  name=f"writeback:{enc.id}")
            his_writeback = "dispatched"
    return {"ok": True, "record_id": record.id, "his_writeback": his_writeback}


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
    """
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


@router.post("", response_model=MedicalRecordResponse, status_code=201)
async def create_record(
    data: MedicalRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 归属校验（2026-08-13 第二轮审计修复）：本端点原先零校验，任何登录医生
    # 都能在他人接诊下凭空建病历（后续版本写入走 record_id 链路，前置 record
    # 一旦被别人建出，归属判定的起点就被污染了）。与 quick_save / auto_save_draft
    # 的既有守卫口径对齐。
    # 角色守卫（2026-08-14 第六轮审计修复）：原先病历写端点只要求登录，
    # nurse/radiologist 与 doctor 权限完全等同——护士能写病历、签发，
    # 签发还会自动回写 HIS，署名落到护士头上，直接违反医院"病历署名必须是
    # 接诊医生本人"的硬要求。
    assert_can_write_record(current_user)
    await assert_encounter_access(db, data.encounter_id, current_user)
    service = MedicalRecordService(db)
    return await service.create(data)


@router.get("/{record_id}", response_model=MedicalRecordResponse)
async def get_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = MedicalRecordService(db)
    return await service.get_by_id(record_id, doctor_id=current_user.id)


@router.put("/{record_id}/content")
async def save_record_content(
    record_id: str,
    data: RecordContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 角色守卫（2026-08-14 第八轮审计）：本文件四个病历写端点里，
    # auto_save_draft / quick_save / create_record 三个都挂了这道守卫，唯独
    # 这个漏了。归属校验在 service 层是有的（按 Encounter.doctor_id 过滤，
    # 不存在 IDOR），缺的正是角色这一层——而医院的硬要求是
    # 「病历上写的名字必须是接诊医生本人」。
    # 现实触发点不是新建（其余三个入口已堵死拿不到 record_id），而是**调岗**：
    # 医生转去影像科/护理岗后，他名下的存量接诊与病历还在，角色已不是 doctor，
    # 却仍能写出 source='doctor_edited' 的新版本。
    assert_can_write_record(current_user)
    service = MedicalRecordService(db)
    return await service.save_content(record_id, data, current_user.id)


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


@router.post("/export-audit", status_code=204)
async def log_record_export(
    data: RecordExportAudit,
    current_user=Depends(get_current_user),
):
    """记录一次病历导出/打印（2026-08-14 第六轮审计修复）。

    为什么需要这个端点：打印与导出 Word 全在客户端完成（前端直接把正文拼成
    HTML 再下载/打印），服务端根本不知道发生过——而**导出是把整份病历连同
    患者身份信息一起带走**，是所有 PHI 操作里最敏感的一个。
    放开归属校验后审计是唯一的追责手段，这条路径上却完全没有留痕。

    前端在触发导出/打印时调用本端点上报。它只写审计、不返回任何数据，
    失败也不该阻断医生导出（log_action 内部已吞异常），故返回 204。
    """
    await log_action(
        action="export_record",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="medical_record",
        resource_id=data.record_id or data.encounter_id or "",
        detail=(
            f"导出/打印病历（方式={data.method}，类型={data.record_type}，"
            f"{'已签发' if data.is_signed else '未签发草稿'}）"
        ),
    )
