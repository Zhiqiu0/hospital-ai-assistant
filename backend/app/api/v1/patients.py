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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """搜索患者列表（支持姓名/患者编号模糊匹配，分页返回）。"""
    service = PatientService(db)
    return await service.search(keyword, page, page_size)


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
    service = PatientService(db)
    return await service.confirm_profile_field(patient_id, data.field, doctor_id=current_user.id)
