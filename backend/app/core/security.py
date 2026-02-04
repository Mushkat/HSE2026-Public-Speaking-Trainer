from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _bcrypt_72_bytes_guard(password: str) -> None:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("The password after UTF-8 encoding cannot exceed 72 bytes.")

def hash_password(password: str) -> str:
    _bcrypt_72_bytes_guard(password)
    try:
        return pwd_context.hash(password)
    except ValueError as e:
        if "72 bytes" in str(e):
            raise ValueError("The password after UTF-8 encoding cannot exceed 72 bytes.")
        raise

def verify_password(password: str, password_hash: str) -> bool:
    _bcrypt_72_bytes_guard(password)
    try:
        return pwd_context.verify(password, password_hash)
    except ValueError as e:
        if "72 bytes" in str(e):
            return False
        raise


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
