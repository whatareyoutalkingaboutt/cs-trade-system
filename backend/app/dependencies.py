from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from backend.core.database import get_sessionmaker
from backend.core.security import decode_access_token
from backend.models import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    try:
        username = decode_access_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    session = get_sessionmaker()()
    try:
        user = session.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User inactive")
        return user
    finally:
        session.close()
