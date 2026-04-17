"""
科室相关 Pydantic 模型（schemas/department.py）

包含：
  DepartmentCreate  : 创建科室的入参
  DepartmentResponse: 科室查询响应
"""

from typing import Optional

from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    """创建科室入参。

    code 在系统内唯一，用于程序内部标识科室（如 "cardiology"），
    与 HIS 系统对接时作为科室编码。
    """

    name: str              # 科室显示名称，如"心内科"
    code: str              # 科室唯一编码（英文，不可重复）
    parent_id: Optional[str] = None  # 上级科室 ID（NULL 表示顶级科室）


class DepartmentResponse(BaseModel):
    """科室查询响应。"""

    id: str
    name: str
    code: str
    is_active: bool  # False 表示科室已停用，不出现在接诊页的科室选择列表中

    class Config:
        from_attributes = True
