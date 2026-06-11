"""读 HIS 当前患者信息(reader.py)

医生在金算盘选中患者后,按 Ctrl+Alt+M 触发 → Agent 调本模块读患者上下文,
然后用这些信息调云端 /api/v1/embed/start 签发 token。

读取策略:
  按 jinsuanpan_map.yaml 的 intake_dialog.fields 配置定位 EditControl,
  读 .Value 属性。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("mediscribe.agent.reader")


@dataclass
class HISPatient:
    """从金算盘读到的患者信息(用于后续调 /embed/start)。"""

    patient_no: str
    visit_no: str | None
    name: str
    gender: str | None = None  # "男"/"女"
    birth_date: str | None = None
    his_brand: str = "jinsuanpan"
    hospital_code: str = "H33052300957"


def read_current_patient(window: Any) -> HISPatient | None:
    """从当前打开的接诊状态读患者信息。

    Args:
        window: detector.find_jinsuanpan_window() 返回的窗口对象。

    Returns:
        HISPatient 实例,如果 HIS 当前不在接诊状态(没选患者)返回 None。
    """
    # TODO: 真实实现
    # patient_no = _read_edit(window, 'tbPatCardData$text')
    # if not patient_no:
    #     return None  # 没选患者
    # return HISPatient(
    #     patient_no=patient_no,
    #     visit_no=_read_edit(window, 'tbOpcNo$text'),
    #     name=_read_edit(window, 'tbName$text') or '',
    #     gender=_read_radio(window, 'rblGender'),
    #     birth_date=_read_edit(window, 'dtDateOfBirth$text'),
    # )
    logger.debug("reader.read_current_patient: 骨架版 stub,返回 None")
    return None


def _read_edit(window: Any, automation_id: str) -> str | None:
    """从 window 里按 AutomationId 找 EditControl 读取值。"""
    if window is None:
        return None
    try:
        ctrl = window.EditControl(AutomationId=automation_id, searchDepth=100)
        if ctrl.Exists(0.5):
            return ctrl.GetValuePattern().Value
    except Exception as e:
        logger.warning("read_edit failed: aid=%s err=%s", automation_id, e)
    return None
