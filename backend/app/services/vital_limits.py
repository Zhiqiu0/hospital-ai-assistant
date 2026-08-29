# -*- coding: utf-8 -*-
"""生命体征生理极限口径（单一来源，2026-08-29 第七轮临床合理性审计）。

为什么要抽共享模块：
  同一个"体征"概念此前三条录入路径三种口径——住院体征表（inpatient_vitals）
  2026-08-28 已加生理极限硬拦，问诊路径（InquiryInputUpdate）与 HIS 推送预填
  （admit_service._prefill_from_push）却零校验，体温 45℃/SpO2 120% 畅通进
  签发正文与 HIS 回写。极限值收口到这里，三条路径引用同一组数。

区间哲学（沿用 2026-08-28 口径对拍结论）：
  两端取**生理极限**而非常见值——低体温症 25℃、心动过速 300 都是真实
  可能出现的极端病例，绝不误伤；只拒收物理上不可能的值（45℃/500 次/分）。
  无法解析为数字的字符串一律放行（问诊字段是自由文本，可能带单位/备注）。
"""
from typing import Optional

# 字段 → (下限, 上限)，与 inpatient_vitals.VitalSignIn 的 Field 区间逐项一致
VITAL_LIMITS: dict[str, tuple[float, float]] = {
    "temperature": (25, 45),
    "pulse": (0, 300),
    "respiration": (0, 80),
    "bp_systolic": (20, 300),
    "bp_diastolic": (10, 200),
    "spo2": (0, 100),
    "weight": (0.3, 400),
    "height": (20, 260),
}

# 中文名（错误提示用，医生要能看懂拒收原因）
VITAL_LABELS: dict[str, str] = {
    "temperature": "体温", "pulse": "脉搏", "respiration": "呼吸",
    "bp_systolic": "收缩压", "bp_diastolic": "舒张压",
    "spo2": "血氧饱和度", "weight": "体重", "height": "身高",
}


def parse_vital_number(value) -> Optional[float]:
    """宽容解析体征字符串为数字：解析不了返回 None（自由文本放行不校验）。"""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def check_vital_range(field: str, value) -> Optional[str]:
    """校验单个体征值：出生理极限返回中文错误信息，可解析且在界内/不可解析返回 None。"""
    num = parse_vital_number(value)
    if num is None:
        return None
    lo, hi = VITAL_LIMITS.get(field, (float("-inf"), float("inf")))
    if not (lo <= num <= hi):
        label = VITAL_LABELS.get(field, field)
        return f"{label} {value} 超出生理极限范围（{lo:g}-{hi:g}），请核对录入"
    return None


def vital_out_of_range(field: str, value) -> bool:
    """HIS 预填用：值可解析且出界返回 True（调用方丢弃该字段并留痕）。"""
    return check_vital_range(field, value) is not None
