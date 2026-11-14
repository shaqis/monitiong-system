from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse
from app.schemas.user import UserResponse

router = APIRouter()

_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    email = str(payload.email).strip().lower()
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    hashed_password = user.hashed_password if user else _DUMMY_HASH
    password_ok = verify_password(payload.password, hashed_password)

    if user is None or not user.is_active or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id, settings)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return LoginResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> None:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


@router.get("/me", response_model=UserResponse)
async def read_current_user(user: User = Depends(get_current_user)) -> User:
    return user
