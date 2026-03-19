from pydantic import BaseModel
from typing import Optional


class DepartmentCreate(BaseModel):
    name: str
    code: str
    parent_id: Optional[str] = None


class DepartmentResponse(BaseModel):
    id: str
    name: str
    code: str
    is_active: bool

    class Config:
        from_attributes = True
