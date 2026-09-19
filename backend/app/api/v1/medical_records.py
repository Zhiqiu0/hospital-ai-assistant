# -*- coding: utf-8 -*-
"""病历路由聚合（api/v1/medical_records.py，2026-09-19 读写两拆后的薄壳）。

原 497 行 12 端点按读/写职责拆为 medical_records_read / _write 两个子
路由文件（各自头注有说明），本文件仅聚合挂载，对外 `medical_records.router`
符号与 URL 全部不变。
⚠ include 顺序有讲究：读组里的 /draft-by-type 等具体路径与写组的
/{record_id} 通配之间，FastAPI 按注册顺序匹配——读组在前保证具体路径
优先（GET 全在读组、写组无 GET，当前无跨组冲突；新增端点时想清楚）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import medical_records_read, medical_records_write
from app.core.authz import assert_can_write_record, assert_encounter_access
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.medical_record import MedicalRecordCreate, MedicalRecordResponse
from app.services.medical_record_service import MedicalRecordService

router = APIRouter()
router.include_router(medical_records_read.router)
router.include_router(medical_records_write.router)


# 注：POST "" 空路径端点必须直接挂在本聚合 router 上——FastAPI 不允许把
# 「空路径路由」include 进「空前缀 router」（encounters.py 同款先例，两拆
# 时实测再撞一次）。本 router 经 __init__ 带 /medical-records 前缀挂载，合法。
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
