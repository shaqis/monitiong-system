from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import BCRYPT_MAX_PASSWORD_BYTES, Settings

_password_hash = PasswordHash([BcryptHasher()])


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    token_version: int


def _fits_bcrypt(password: str) -> bool:
    return len(password.encode("utf-8")) <= BCRYPT_MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    if not _fits_bcrypt(password):
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    if not _fits_bcrypt(password):
        return False
    try:
        return _password_hash.verify(password, hashed_password)
    except (UnknownHashError, ValueError):
        # UnknownHashError covers an unrecognized format. bcrypt raises a bare
        # ValueError for a recognized prefix with a corrupt salt or digest, so
        # both must fail closed instead of surfacing a 500.
        return False


def create_access_token(
    user_id: UUID,
    settings: Settings,
    *,
    token_version: int = 0,
) -> str:
    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.jwt_expire_minutes),
        "ver": token_version,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise ValueError("Token is missing a subject")

    # Tokens issued before versioning omit the claim. They stay valid for a
    # user who has never reset a password, and a reset raises the stored version.
    version = payload.get("ver", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError("Token has an invalid version")

    return AccessTokenClaims(user_id=UUID(subject), token_version=version)
