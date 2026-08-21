# -*- coding: utf-8 -*-
"""质控员工作台路由树（/api/v1/qc/*，2026-08-21 阶段4）。

与 /admin/*（require_admin 硬门禁）完全隔离的专属通道：
qc_officer 在此获得**只读**病历访问 + 复核写入，不获得任何管理/病历书写权限。
路由级挂 require_qc_officer——新增子模块 include 进来自动获得门禁。
"""
from fastapi import APIRouter, Depends

from app.core.security import require_qc_officer

from app.api.v1.qc import reviews, stats

router = APIRouter(dependencies=[Depends(require_qc_officer)])
router.include_router(reviews.router)
# 质控指标统计（2026-08-21 阶段5）
router.include_router(stats.router)
