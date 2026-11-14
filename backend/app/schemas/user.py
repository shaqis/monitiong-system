from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, StringConstraints

from app.core.config import BCRYPT_MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH

Role = Literal["admin", "viewer"]

FullName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]


def _password_fits_bcrypt(value: str) -> str:
    if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return value


Password = Annotated[
    str,
    StringConstraints(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=BCRYPT_MAX_PASSWORD_BYTES,
    ),
    AfterValidator(_password_fits_bcrypt),
]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: FullName
    password: Password
    role: Role = "viewer"


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: FullName | None = None
    password: Password | None = None
    role: Role | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime
