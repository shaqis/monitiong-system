import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

_SECRET_NAMESPACE = "notification-settings:"


class SecretDecryptionError(Exception):
    """A stored secret cannot be decrypted with the current key."""


def _fernet(jwt_secret: str) -> Fernet:
    digest = hashlib.sha256(f"{_SECRET_NAMESPACE}{jwt_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str, *, jwt_secret: str) -> str:
    return _fernet(jwt_secret).encrypt(value.encode()).decode()


def decrypt_secret(token: str, *, jwt_secret: str) -> str:
    try:
        return _fernet(jwt_secret).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        raise SecretDecryptionError("Stored notification secret cannot be decrypted") from None
