from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import normalize_email
from app.schemas.admin import AdminResponse


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_login_email(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_email(value)
        return value


class AuthResponse(BaseModel):
    admin: AdminResponse


class MessageResponse(BaseModel):
    message: str
