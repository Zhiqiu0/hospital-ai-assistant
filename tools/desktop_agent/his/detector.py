"""探测金算盘 HIS 窗口(detector.py)

策略:
  1. 按 ClassName='Chrome_WidgetWin_1' 找所有 Chromium 窗口
  2. 在里面找窗口标题含"全科医生"的(YAML window.title_pattern)
  3. 优先选当前前台窗口(医生可能开多个 Chromium 实例)

骨架版:函数签名定下来,真实实现用 uiautomation 完成。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mediscribe.agent.detector")


def find_jinsuanpan_window() -> Any | None:
    """找到金算盘主窗口对象。

    Returns:
        uiautomation 的 ControlFromControl 对象,或者 None(没找到)。
    """
    # TODO: 真实实现
    # import uiautomation as auto
    # root = auto.GetRootControl()
    # for window in root.GetChildren():
    #     if window.ClassName == "Chrome_WidgetWin_1" and "全科医生" in (window.Name or ""):
    #         return window
    # return None
    logger.debug("detector.find_jinsuanpan_window: 骨架版 stub,返回 None")
    return None


def is_his_alive(window: Any) -> bool:
    """检查 HIS 窗口是否还活着(医生可能中途关掉)。"""
    if window is None:
        return False
    try:
        return window.Exists()
    except Exception:
        return False
