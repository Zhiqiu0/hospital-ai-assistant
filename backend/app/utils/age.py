"""年龄计算工具（utils/age.py）

Patient 表只存 birth_date（出生日期），age 不入库——
凡是要给前端/AI/病案首页一个具体年龄的地方，都用本模块实时算，
确保未过生日的患者不会被算多一岁，且所有 service 间行为一致。

历史背景：
  曾经在 patient_service / encounter_service / medical_record_service /
  inpatient_service 里各 inline 写了 4-5 处同样算法，
  inpatient_service 还误用了不存在的 `pat.age` 属性导致 /inpatient/ward 500，
  统一收口到本模块后，新加的 service 不应再 inline 重写。
"""

from datetime import date
from typing import Optional


def calc_age(birth: Optional[date], today: Optional[date] = None) -> Optional[int]:
    """根据出生日期计算周岁年龄。

    Args:
        birth: 出生日期；为 None 时返回 None（如未录入出生日期的历史档案）
        today: 比较基准日，仅供单元测试注入；默认取系统当天

    Returns:
        周岁年龄。今年还没过生日的会减 1，避免显示偏大。
    """
    if not birth:
        return None
    ref = today or date.today()
    return ref.year - birth.year - (
        (ref.month, ref.day) < (birth.month, birth.day)
    )
