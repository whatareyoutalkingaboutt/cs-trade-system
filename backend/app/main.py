from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers.alerts import router as alerts_router
from backend.app.routers.arbitrage import router as arbitrage_router
from backend.app.routers.auth import router as auth_router
from backend.app.routers.items import router as items_router
from backend.app.routers.prices import router as prices_router
from backend.app.routers.scraper import router as scraper_router
from backend.app.routers.wear import router as wear_router
from backend.core.database import get_sessionmaker
from backend.core.security import hash_password
from backend.models import User


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_default_admin()
    yield


app = FastAPI(title="CS Item API", lifespan=lifespan)

DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "root")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "root")
DEFAULT_ADMIN_BOOTSTRAP_KEY = os.getenv("DEFAULT_ADMIN_BOOTSTRAP_KEY", "").strip()
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "root@local")
RESET_DEFAULT_ADMIN_ON_STARTUP = os.getenv("RESET_DEFAULT_ADMIN_ON_STARTUP", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

allowed_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if not allowed_origins:
    allowed_origins = ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(items_router)
app.include_router(prices_router)
app.include_router(arbitrage_router)
app.include_router(alerts_router)
app.include_router(scraper_router)
app.include_router(wear_router)


def ensure_default_admin() -> None:
    session = get_sessionmaker()()
    try:
        user = session.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).first()
        bootstrap_secret = DEFAULT_ADMIN_BOOTSTRAP_KEY or DEFAULT_ADMIN_PASSWORD
        if not user:
            hashed = hash_password(bootstrap_secret)
            user = User(
                username=DEFAULT_ADMIN_USERNAME,
                email=DEFAULT_ADMIN_EMAIL,
                hashed_password=hashed,
                is_active=True,
                is_superuser=True,
            )
            session.add(user)
        elif RESET_DEFAULT_ADMIN_ON_STARTUP:
            hashed = hash_password(bootstrap_secret)
            user.hashed_password = hashed
            user.is_active = True
            user.is_superuser = True
            if not user.email:
                user.email = DEFAULT_ADMIN_EMAIL
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {
        "message": "CS Item API is running",
        "docs": "/docs",
        "health": "/health",
    }
