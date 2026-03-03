from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.dependencies import get_current_user, oauth2_scheme
from backend.core.database import get_sessionmaker
from backend.core.security import (
    ACCESS_TOKEN_REFRESH_GRACE_MINUTES,
    create_access_token,
    decode_access_token_payload,
    extract_token_expiry,
    hash_password,
    verify_password,
)
from backend.models import User


router = APIRouter(prefix="/api/auth", tags=["auth"])
ADMIN_LOGIN_KEY = os.getenv("ADMIN_LOGIN_KEY", "").strip()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


def _get_user_by_username_or_email(session, identity: str) -> Optional[User]:
    return (
        session.query(User)
        .filter((User.username == identity) | (User.email == identity))
        .first()
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    session = get_sessionmaker()()
    try:
        user = _get_user_by_username_or_email(session, payload.username)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        password_ok = verify_password(payload.password, user.hashed_password)
        if (
            not password_ok
            and user.is_superuser
            and ADMIN_LOGIN_KEY
            and payload.password == ADMIN_LOGIN_KEY
        ):
            password_ok = True

        if not password_ok:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User inactive")

        token = create_access_token(user.username)
        user.last_login_at = datetime.now(timezone.utc)
        session.commit()
        return TokenResponse(access_token=token)
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(token: str = Depends(oauth2_scheme)) -> TokenResponse:
    session = get_sessionmaker()()
    try:
        try:
            payload = decode_access_token_payload(token, verify_exp=False)
            subject = str(payload.get("sub") or "")
            if not subject:
                raise ValueError("Missing subject")
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        expires_at = extract_token_expiry(token)
        if expires_at is not None:
            now = datetime.now(timezone.utc)
            if now - expires_at > timedelta(minutes=ACCESS_TOKEN_REFRESH_GRACE_MINUTES):
                raise HTTPException(status_code=401, detail="Token refresh window expired")

        user = session.query(User).filter(User.username == subject).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User inactive")

        fresh_token = create_access_token(user.username)
        return TokenResponse(access_token=fresh_token)
    finally:
        session.close()


@router.post("/logout")
def logout(_: User = Depends(get_current_user)) -> dict:
    return {"success": True}


@router.post("/register")
def register(payload: RegisterRequest) -> dict:
    session = get_sessionmaker()()
    try:
        username = payload.username.strip()
        email = payload.email.strip().lower()

        exists = (
            session.query(User)
            .filter((User.username == username) | (User.email == email))
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="User already exists")

        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(payload.password),
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"success": True, "data": {"id": user.id}}
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict:
    return {
        "success": True,
        "data": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "is_active": current_user.is_active,
            "is_superuser": current_user.is_superuser,
            "last_login_at": current_user.last_login_at.isoformat()
            if current_user.last_login_at
            else None,
        },
    }
