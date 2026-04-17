"""
患者路由（/api/v1/patients/*）

端点列表：
  GET    /              搜索患者列表（关键词模糊匹配，分页）
  POST   /              新建患者档案
  GET    /{patient_id}  查询单个患者详情
  PUT    /{patient_id}  更新患者信息

所有端点均需登录认证（get_current_user）。
患者查重逻辑在 PatientService 内部处理，路由层只做参数传递。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.schemas.patient import PatientCreate, PatientListResponse, PatientResponse, PatientUpdate
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
