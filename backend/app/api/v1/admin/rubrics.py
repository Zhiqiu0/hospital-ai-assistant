"""法定评分标准只读接口（/api/v1/admin/rubrics/*）

L3 治本路线（2026-05-18）：
  浙江省卫健委评分标准已迁移到 qc_engine.rubrics.* 代码常量，
  本接口仅暴露**只读视图**供前端 QCRulesPage 展示，admin 不能编辑。

修改评分标准 = 修改国家法定文件 → 走代码 PR review，不在 admin 后台改。
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_admin
from app.services.qc_engine.rubric import Rubric
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)

router = APIRouter()


# 评分表注册中心：所有法定 Rubric 在此登记，前端按 key 取
_RUBRIC_REGISTRY: dict[str, Rubric] = {
    "zj_outpatient_emergency_2023": ZJ_OUTPATIENT_EMERGENCY_V2023,
    # 下一期：zj_inpatient_2021
}


def _rubric_to_dict(rubric: Rubric) -> dict:
    """Rubric → 前端 JSON 视图（脱去 checker 函数，仅保留可展示数据）。"""
    return {
        "name": rubric.name,
        "version": rubric.version,
        "record_scope": rubric.record_scope,
        "total_points": rubric.total_points,
        "grade_thresholds": [
            {"min_score": t.min_score, "label": t.label}
            for t in rubric.grade_thresholds
        ],
        "items": [
            {
                "name": item.name,
                "max_points": item.max_points,
                "description": item.description,
                "deduction_rules": [
                    {
                        "code": r.code,
                        "description": r.description,
                        "deduct_points": r.deduct_points,
                    }
                    for r in item.deduction_rules
                ],
                "veto_rules": [
                    {"code": v.code, "description": v.description, "deduct_points": 10}
                    for v in item.veto_rules
                ],
            }
            for item in rubric.items
        ],
    }


@router.get("", response_model=dict)
async def list_rubrics(_=Depends(require_admin)):
    """列出所有已注册的法定评分标准（key + 元数据）。"""
    return {
        "items": [
            {
                "key": key,
                "name": rubric.name,
                "version": rubric.version,
                "record_scope": rubric.record_scope,
                "total_points": rubric.total_points,
            }
            for key, rubric in _RUBRIC_REGISTRY.items()
        ],
    }


@router.get("/{rubric_key}", response_model=dict)
async def get_rubric(rubric_key: str, _=Depends(require_admin)):
    """按 key 取完整评分标准（含所有大项、扣分规则、等级阈值）。"""
    rubric = _RUBRIC_REGISTRY.get(rubric_key)
    if rubric is None:
        raise HTTPException(status_code=404, detail=f"评分标准 {rubric_key} 不存在")
    return _rubric_to_dict(rubric)
