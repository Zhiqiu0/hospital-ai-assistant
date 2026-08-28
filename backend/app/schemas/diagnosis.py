# -*- coding: utf-8 -*-
"""诊断条目 Pydantic 模型（schemas/diagnosis.py，2026-08-21 阶段1a）。

诊断条目是病历/病案首页的结构化权威源，见 models/encounter.Diagnosis 类注释。
"""
from typing import Optional

from pydantic import BaseModel, field_validator

# 与 HIS 回写 diagnoses[].category 枚举一致
VALID_CATEGORIES = {"western", "tcm_disease", "tcm_syndrome"}
# 国家病案首页规范"入院病情"四值枚举
VALID_ADMISSION_CONDITIONS = {"有", "临床未确定", "情况不明", "无"}


class DiagnosisItemIn(BaseModel):
    """单条诊断条目（写入）。"""

    category: str
    name: str
    code: Optional[str] = None
    code_type: Optional[str] = None
    is_primary: bool = False
    admission_condition: Optional[str] = None
    sort_order: int = 0

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category 必须是 {sorted(VALID_CATEGORIES)} 之一")
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """诊断名清洗（2026-08-28 极端字符审计）。

        中间夹换行的诊断名会让投影产出多行"西医诊断：A/B"，QC 行级解析
        只取首行——第二条诊断对质控完全隐形；HIS 回写单行字段也会收到
        换行。压平换行/制表，顺带剥零宽字符与 NUL。
        """
        for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060", "\x00"):
            v = (v or "").replace(ch, "")
        v = v.replace("\n", " ").replace("\r", " ").replace("\t", " ").strip()
        if not v:
            raise ValueError("诊断名称不能为空")
        if len(v) > 200:
            raise ValueError("诊断名称最长 200 字")
        return v

    @field_validator("admission_condition")
    @classmethod
    def _check_condition(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "" and v not in VALID_ADMISSION_CONDITIONS:
            raise ValueError(f"入院病情必须是 {sorted(VALID_ADMISSION_CONDITIONS)} 之一")
        return v or None


class DiagnosisListUpdate(BaseModel):
    """整组替换写入（前端保存整个列表，避免逐条 diff 的一致性问题）。"""

    items: list[DiagnosisItemIn] = []


class DiagnosisItemOut(BaseModel):
    """单条诊断条目（读出）。"""

    id: str
    category: str
    name: str
    code: Optional[str] = None
    code_type: Optional[str] = None
    is_primary: bool = False
    admission_condition: Optional[str] = None
    sort_order: int = 0

    class Config:
        from_attributes = True
