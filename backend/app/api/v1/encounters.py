"""
接诊路由聚合（/api/v1/encounters/*）

Round 5 瘦身：原文件 432 行超标，按职责拆到同目录子模块（各自建 router，本文件聚合）——
  encounters_quickstart : POST /quick-start（一键创建患者 + 接诊，含幂等锁/复诊回填）
  encounters_lifecycle  : POST /、GET /my、POST /{id}/discharge|cancel、
                          GET /{id}、GET /{id}/workspace（生命周期与状态流转）
  encounters_inquiry    : PUT /{id}/inquiry、GET /{id}/previous-record、
                          POST /{id}/inquiry-suggestions|exam-suggestions（问诊与 AI 建议）
本文件只保留主 router 并 include 子路由（路径/方法/依赖零改动，行为完全一致）。

端点列表：
  POST   /quick-start           一键创建患者 + 接诊记录
  POST   /                      标准创建接诊记录
  GET    /my                    获取当前医生进行中的接诊列表
  POST   /{encounter_id}/discharge  办理出院
  POST   /{encounter_id}/cancel     取消接诊
  GET    /{encounter_id}        查询单条接诊记录
  GET    /{encounter_id}/workspace  获取工作台快照
  PUT    /{encounter_id}/inquiry    保存问诊输入
  GET    /{encounter_id}/previous-record  同步上次病历
  POST   /{encounter_id}/inquiry-suggestions  问诊追问建议
  POST   /{encounter_id}/exam-suggestions     检查建议
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.schemas.encounter import EncounterCreate, EncounterResponse
from app.services.encounter_service import EncounterService

# 同目录子路由（各自持有 APIRouter，端点路径与拆分前逐字一致）
from app.api.v1 import encounters_inquiry, encounters_lifecycle, encounters_quickstart

# 主 router：仍由 app/api/v1/__init__.py 以 prefix="/encounters" 注册；
# 子路由不带额外 prefix，拼回后端点路径与原文件完全相同。
# include 顺序保持"静态路径（/quick-start、/my）先于动态 /{encounter_id}"，避免路由捕获错乱。
router = APIRouter()


# 注：POST "" 这条空路径端点必须挂在主 router 上——
# FastAPI 不允许把「空路径路由」include 进「空前缀 router」（会抛
# "Prefix and path cannot be both empty"），故不下沉到子模块。
@router.post("", response_model=EncounterResponse, status_code=201)
async def create_encounter(
    data: EncounterCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """标准接诊记录创建（患者必须已存在）。"""
    service = EncounterService(db)
    return await service.create(data, current_user.id)


router.include_router(encounters_quickstart.router)
router.include_router(encounters_lifecycle.router)
router.include_router(encounters_inquiry.router)
