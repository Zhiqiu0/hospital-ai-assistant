"""
患者路由（/api/v1/patients/*）

端点列表：
  GET    /                       搜索患者列表（关键词模糊匹配，分页）
  POST   /                       新建患者档案
  GET    /{patient_id}           查询单个患者详情
  PUT    /{patient_id}            更新患者信息
  GET    /{patient_id}/profile   取患者档案（过敏/既往/用药等纵向数据）
  PUT    /{patient_id}/profile   更新患者档案

所有端点均需登录认证（get_current_user）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import assert_patient_access
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.patient import (
    PatientCreate,
    PatientListResponse,
    PatientProfile,
    PatientProfileFieldConfirm,
    PatientProfileUpdate,
    PatientResponse,
    PatientUpdate,
)
from app.services.patient_service import PatientService

router = APIRouter()


@router.get("", response_model=PatientListResponse)
async def list_patients(
    keyword: str = Query(default="", description="搜索关键词（姓名或患者编号，为空返回全部）"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，最大 100"),
    require_completed: bool = Query(
        default=False,
        description="True 时只返回至少有 1 个 status=completed 接诊的患者，复诊弹窗专用",
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """搜索患者列表（支持姓名/患者编号模糊匹配，分页返回）。

    require_completed=True 时为复诊弹窗专用语义：
    过滤掉「档案在但从未真正完成过任何接诊」的患者，避免医生把这类患者误当复诊接。

    隐私边界（2026-08-13 第二轮审计修复）：返回 PatientListItem 精简项，
    **不含身份证/住址/紧急联系人等病案首页级 PHI**——那些只在
    GET /patients/{id} 返回（带 assert_patient_access 归属校验 + view_patient 审计）。
    """
    # 空关键词=枚举全院患者，属"批量浏览"而非临床检索，留痕便于事后追溯
    # （按姓名检索是高频常规操作，逐次审计会淹没日志，故只审计枚举行为）
    if not keyword.strip():
        from app.services.audit_service import log_action
        await log_action(
            action="browse_patients",
            user_id=current_user.id,
            user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
            user_role=getattr(current_user, "role", None),
            resource_type="patient_list",
            detail=f"浏览患者列表（无关键词，第 {page} 页，每页 {page_size}）",
        )
    service = PatientService(db)
    return await service.search(keyword, page, page_size, require_completed=require_completed)


@router.post("", response_model=PatientResponse, status_code=201)
async def create_patient(
    data: PatientCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """新建患者档案。

    调用方在创建前应先调用 /patients?keyword= 或 /encounters/quick-start
    进行查重，避免重复建档。此端点本身不做查重拦截。
    """
    service = PatientService(db)
    return await service.create(data)


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """按 UUID 查询单个患者详情。"""
    # 归属校验：非管理员只能查自己接诊过的患者，防止越权读身份证号/住址等 PHI（IDOR）
    await assert_patient_access(db, patient_id, current_user)
    # PHI 访问留痕（2026-08-11 分级评审）：本端点返回身份证/住址等敏感字段，
    # 每次查阅写审计（谁在何时看了哪位患者的档案），供事后追溯。
    from app.services.audit_service import log_action
    await log_action(
        action="view_patient",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="patient", resource_id=patient_id,
        detail="查阅患者档案详情（含身份证/住址等 PHI）",
    )
    service = PatientService(db)
    return await service.get_by_id(patient_id)


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: str,
    data: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新患者信息（只更新传入的非 None 字段）。"""
    # 归属校验：只能改自己接诊过的患者，防止越权篡改他人档案
    await assert_patient_access(db, patient_id, current_user)
    # 档案修改留痕（2026-08-11 分级评审）：改了哪些字段名进审计（不含值，避免 PHI 入日志）
    from app.services.audit_service import log_action
    await log_action(
        action="update_patient",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="patient", resource_id=patient_id,
        detail=f"修改患者档案字段：{', '.join(data.model_dump(exclude_none=True).keys())}",
    )
    service = PatientService(db)
    return await service.update(patient_id, data)


@router.get("/{patient_id}/profile", response_model=PatientProfile)
async def get_patient_profile(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """取患者档案（过敏/既往/家族史/用药等纵向持久数据）。

    该档案跟随患者本身，不跟随单次接诊，符合 FHIR 标准。
    复诊/再次住院时前端自动加载，医生无需重复询问。
    """
    # 归属校验：只能读自己接诊过的患者档案，防止越权读过敏史/既往史等纵向 PHI
    await assert_patient_access(db, patient_id, current_user)
    service = PatientService(db)
    return await service.get_profile(patient_id)


@router.put("/{patient_id}/profile", response_model=PatientProfile)
async def update_patient_profile(
    patient_id: str,
    data: PatientProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新患者档案。只覆盖传入的非 None 字段，已有数据保留。

    医生在问诊时发现新过敏史/新用药等，写入该接口持久化到患者档案。
    每个被改动的字段独立刷新 updated_at + updated_by（FHIR 字段级 verification 思路）。
    """
    # 归属校验：只能改自己接诊过的患者档案
    await assert_patient_access(db, patient_id, current_user)
    # 档案写入留痕（2026-08-13 第二轮审计修复）：过敏史/既往史等纵向 PHI 被改动
    # 原先零审计，且档案是原地覆盖无历史版本——出事后既查不到谁改的、也回不去。
    # 与 update_patient 的既有审计口径一致，只记字段名不记内容（避免 PHI 进日志）。
    from app.services.audit_service import log_action
    await log_action(
        action="update_patient_profile",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="patient_profile", resource_id=patient_id,
        detail=f"修改患者档案字段：{', '.join(data.model_dump(exclude_none=True).keys())}",
    )
    service = PatientService(db)
    return await service.update_profile(patient_id, data, doctor_id=current_user.id)


@router.post("/{patient_id}/profile/confirm", response_model=PatientProfile)
async def confirm_patient_profile_field(
    patient_id: str,
    data: PatientProfileFieldConfirm,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """确认档案字段仍准确（"✓ 仍准确"按钮）：仅刷新该字段 updated_at + updated_by。

    用于场景：医生看了既往史，确认 3 年前录入的内容现在还是这样，点一下让"X 天前确认"
    重新计时，但不需要真的修改值。对应 FHIR verificationStatus: confirmed。
    """
    # 归属校验：只能确认自己接诊过的患者档案字段
    await assert_patient_access(db, patient_id, current_user)
    service = PatientService(db)
    return await service.confirm_profile_field(patient_id, data.field, doctor_id=current_user.id)
