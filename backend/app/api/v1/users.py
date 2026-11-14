from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.security import hash_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter()

ADMIN_GUARD_LOCK = "users_admin_guard"


@router.get("", response_model=list[UserResponse])
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    users = (await db.scalars(select(User).order_by(User.created_at))).all()
    return list(users)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    email = str(payload.email).strip().lower()
    existing = await db.scalar(select(User.id).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None

    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": ADMIN_GUARD_LOCK},
    )

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    next_role = payload.role if payload.role is not None else user.role
    next_active = payload.is_active if payload.is_active is not None else user.is_active
    removes_active_admin = (
        user.role == "admin" and user.is_active and (next_role != "admin" or not next_active)
    )

    if removes_active_admin:
        active_admins = (
            await db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True)))
        ).all()
        if len(active_admins) <= 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot remove the last active admin",
            )

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await db.commit()
    await db.refresh(user)
    return user
