from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserResponse
