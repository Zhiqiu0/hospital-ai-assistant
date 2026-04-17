"""
AI 建议类 Pydantic 模型（schemas/ai_suggestion.py）

包含：
  InquirySuggestionRequest : 问诊追问建议的入参
  ExamSuggestionRequest    : 辅助检查建议的入参

这两个 Schema 由接诊路由（encounters.py）和独立建议路由使用，
AI 根据入参生成差异化的建议内容。
"""

from typing import Optional

from pydantic import BaseModel


class InquirySuggestionRequest(BaseModel):
    """生成问诊追问建议的入参。

    AI 根据主诉和现病史，推断可能遗漏的问诊要点，
    以"追问建议"形式展示，帮助医生提高问诊完整性。
    """

    chief_complaint: str                         # 主诉（必填，建议生成的核心依据）
    history_present_illness: Optional[str] = None  # 现病史（有则参考，无则仅基于主诉推断）
    department: Optional[str] = None             # 科室（如"心内科"，影响专科问诊方向）
    patient_age: Optional[int] = None            # 患者年龄（影响年龄相关风险提示）
    patient_gender: Optional[str] = None         # 患者性别（影响性别特异性问题）


class ExamSuggestionRequest(BaseModel):
    """生成辅助检查建议的入参。

    AI 根据主诉、现病史和初步诊断，推荐合适的检查项目，
    分为基本检查、鉴别诊断检查和高风险筛查三类。
    """

    chief_complaint: str                         # 主诉（必填）
    history_present_illness: Optional[str] = None  # 现病史
    initial_impression: Optional[str] = None     # 初步诊断（有助于针对性推荐检查）
    department: Optional[str] = None             # 科室（影响检查项目范围）
