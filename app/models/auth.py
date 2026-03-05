from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    FACULTY = "faculty"
    STUDENT = "student"
    STAFF = "staff"


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    role: UserRole = UserRole.STUDENT
    student_id: Optional[str] = None
    department: str = "CITE"
    year_level: Optional[int] = Field(None, ge=1, le=5)
    
    @validator('student_id')
    def validate_student_id(cls, v, values):
        if values.get('role') == UserRole.STUDENT and not v:
            raise ValueError('Student ID is required for student role')
        return v


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)
    
    @validator('password')
    def validate_password(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    department: Optional[str] = None
    year_level: Optional[int] = Field(None, ge=1, le=5)


class UserResponse(UserBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)
    
    @validator('new_password')
    def validate_password(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v


class PasswordReset(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)