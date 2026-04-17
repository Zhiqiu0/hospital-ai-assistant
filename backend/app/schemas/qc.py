"""
质控相关 Pydantic 模型（schemas/qc.py）

包含：
  QCIssueStatusUpdate : 更新质控问题处理状态的入参

用于管理后台中标记质控问题为"已解决"或"已忽略"。
"""

from pydantic import BaseModel


class QCIssueStatusUpdate(BaseModel):
    """更新单条质控问题状态的入参。

    status 可选值：
      "resolved" : 医生已修复该问题
      "ignored"  : 医生主动忽略（有合理理由不修复）
    """

    status: str  # "resolved" / "ignored"
