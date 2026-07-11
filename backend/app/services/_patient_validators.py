"""患者跨字段校验纯函数（services/_patient_validators.py）

从 patient_service 拆出（Round: 超标文件拆分）。这里只放不依赖 db session 的
纯校验函数，供 create / update 写路径调用。

patient_service.py 会 re-export `_assert_id_card_birth_date_consistent`，
保持既有导入路径不变（test_validators_identity.py 在直接 import 它）：
    from app.services.patient_service import _assert_id_card_birth_date_consistent
"""
from datetime import date

from fastapi import HTTPException

from app.core.validators.identity import extract_birth_date_from_id_card


def _assert_id_card_birth_date_consistent(id_card: str | None, birth_date: date | None) -> None:
    """断言身份证内嵌出生日期与 birth_date 字段一致。

    身份证号第 7-14 位是出生日期 YYYYMMDD（GB 11643-1999 规定）。如果两边都填了
    但对不上，多半是医生打字错位、LLM 抽取错列或者两边录的本就不是同一人。这是
    患者主索引被污染的最常见来源，必须在 service 层兜住。

    Args:
        id_card: 已经 Pydantic 校验通过的身份证号（含 normalize），或 None
        birth_date: 用户提供的出生日期字段值，或 None

    Raises:
        HTTPException(422): 两者都非空且不一致时抛出，前端可定位提示
    """
    if not id_card or not birth_date:
        return  # 任一为空时无法对比，放行（由 Pydantic 层的单字段校验兜底）
    extracted = extract_birth_date_from_id_card(id_card)
    if not extracted:
        return  # 身份证号本身有问题应该在 Pydantic 层就被挡下，这里防御性返回
    if extracted != (birth_date.year, birth_date.month, birth_date.day):
        raise HTTPException(
            status_code=422,
            detail=(
                f"身份证号与出生日期不符："
                f"身份证显示 {extracted[0]}-{extracted[1]:02d}-{extracted[2]:02d}，"
                f"出生日期字段为 {birth_date.isoformat()}"
            ),
        )
