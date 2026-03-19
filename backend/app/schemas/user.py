from pydantic import BaseModel
from typing import Optional


class UserCreate(BaseModel):
    username: str
    password: str
    real_name: str
    role: str
    department_id: Optional[str] = None
    employee_no: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class UserUpdate(BaseModel):
    real_name: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    username: str
    real_name: str
    role: str
    is_active: bool
    department_id: Optional[str] = None
    department_name: Optional[str] = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    total: int
    items: list[UserResponse]
