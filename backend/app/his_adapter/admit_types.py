# -*- coding: utf-8 -*-
"""HIS 接诊推送·共享类型（三拆基座，2026-09-19）。

AdmitError/AdmitResult 供 admit_service 与其两个子模块共用——放独立
基座避免"主文件 import 子模块、子模块又要主文件的类"的循环依赖。
admit_service 保留同名 re-export，外部 import 路径不变。
"""
from dataclasses import dataclass


class AdmitError(Exception):
    """接诊推送业务错误：code 用于 ack 回执（规范 2.4 错误码体系）。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AdmitResult:
    """接诊推送处理结果（ack data 与叫号事件的数据源）。"""

    encounter_id: str
    patient_id: str
    patient_name: str
    doctor_id: str
    reused: bool  # True=visit_id 已有接诊，本次为重复推送（幂等复用）


