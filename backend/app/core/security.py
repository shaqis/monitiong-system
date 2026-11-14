from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import BCRYPT_MAX_PASSWORD_BYTES, Settings

_password_hash = PasswordHash([BcryptHasher()])


def _fits_bcrypt(password: str) -> bool:
    return len(password.encode("utf-8")) <= BCRYPT_MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    if not _fits_bcrypt(password):
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    if not _fits_bcrypt(password):
        return False
    return _password_hash.verify(password, hashed_password)


def create_access_token(user_id: UUID, settings: Settings) -> str:
    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> UUID:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise ValueError("Token is missing a subject")
    return UUID(subject)
