# -*- coding: utf-8 -*-
"""诊断编码字典检索（api/v1/diagnosis_codes.py，2026-08-21 阶段2）

  GET /diagnosis-codes/search?q=&code_type=&limit=

三路匹配（按优先级排序返回）：
  1. 名称前缀 / 名称包含
  2. 拼音首字母前缀（"gxy" → 高血压…）
  3. 编码前缀（"I10" → I10.x00…）
别名（中医"可选词"）与名称同权重命中。字典是公开标准数据，登录即可查。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.encounter import DiagnosisCode

router = APIRouter()

_VALID_TYPES = {"ICD10", "ICD9CM3", "TCD_DIS", "TCD_SYN"}


@router.get("/search")
async def search_codes(
    q: str = Query(..., min_length=1, max_length=60),
    code_type: str = Query(...),
    limit: int = Query(15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """按名称/拼音首字母/编码联想检索字典。"""
    if code_type not in _VALID_TYPES:
        return []
    term = q.strip()
    if not term:
        return []
    lowered = term.lower()
    # 编码匹配忽略点号（2026-08-22 用户实测）：国标码带层级点（A01.01.02），
    # 医生记不住点在哪——"a010102"应与"a01.01.02"同样命中。
    # 大小写不敏感（2026-08-22 终验实锤）：ICD 医保码含小写 x（I10.x05），
    # 只把输入 upper 会让含 x 码段永不命中——两侧都 upper 再比
    code_term = term.upper().replace(".", "")

    rows = (await db.execute(
        select(DiagnosisCode)
        .where(
            DiagnosisCode.code_type == code_type,
            or_(
                DiagnosisCode.name.contains(term),
                DiagnosisCode.aliases.contains(term),
                DiagnosisCode.pinyin_initial.startswith(lowered),
                func.upper(func.replace(DiagnosisCode.code, ".", "")).startswith(code_term),
            ),
        )
        # 短名靠前（"高血压"排在"高血压性心脏病…"前），同长按编码稳定排序
        .order_by(DiagnosisCode.name, DiagnosisCode.code)
        .limit(limit * 3)
    )).scalars().all()

    # 应用层重排：名称前缀命中 > 名称包含 > 拼音 > 编码；短名优先
    def rank(r: DiagnosisCode) -> tuple:
        if r.name.startswith(term):
            group = 0
        elif term in r.name or (r.aliases and term in r.aliases):
            group = 1
        elif r.pinyin_initial and r.pinyin_initial.startswith(lowered):
            group = 2
        else:
            group = 3  # 编码命中（含去点匹配）排最后
        return (group, len(r.name), r.code)

    ranked = sorted(rows, key=rank)[:limit]
    return [
        {"code": r.code, "name": r.name, "code_type": r.code_type, "aliases": r.aliases}
        for r in ranked
    ]
