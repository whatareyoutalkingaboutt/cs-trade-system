from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

# Use pbkdf2 to avoid bcrypt backend issues on some environments.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "change_me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
ACCESS_TOKEN_REFRESH_GRACE_MINUTES = int(os.getenv("ACCESS_TOKEN_REFRESH_GRACE_MINUTES", "1440"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": subject,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token_payload(token: str, *, verify_exp: bool = True) -> dict[str, Any]:
    try:
        options = None if verify_exp else {"verify_exp": False}
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options=options)
        if not isinstance(payload, dict):
            raise JWTError("Invalid payload type")
        return payload
    except JWTError as exc:
        raise ValueError("Invalid token") from exc


def decode_access_token(token: str) -> str:
    payload = decode_access_token_payload(token)
    subject = payload.get("sub")
    if not subject:
        raise ValueError("Invalid token")
    return str(subject)


def extract_token_expiry(token: str) -> Optional[datetime]:
    payload = decode_access_token_payload(token, verify_exp=False)
    exp = payload.get("exp")
    if exp is None:
        return None
    if isinstance(exp, (int, float)):
        return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    if isinstance(exp, str):
        try:
            return datetime.fromtimestamp(float(exp), tz=timezone.utc)
        except ValueError:
            return None
    return None
