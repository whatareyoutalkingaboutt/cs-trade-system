from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


def _build_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "cs_items")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _build_database_url()
ASYNC_DATABASE_URL = os.getenv("ASYNC_DATABASE_URL")

_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_sessionmaker = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

_async_engine = None
_async_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine():
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    return _sessionmaker


def get_async_engine():
    if not ASYNC_DATABASE_URL:
        raise RuntimeError("ASYNC_DATABASE_URL is not set")

    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(ASYNC_DATABASE_URL, pool_pre_ping=True)
    return _async_engine


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _async_sessionmaker
    if _async_sessionmaker is None:
        _async_sessionmaker = async_sessionmaker(
            get_async_engine(),
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _async_sessionmaker


@contextmanager
def db_session() -> Iterator[Session]:
    session = _sessionmaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def async_db_session() -> AsyncIterator[AsyncSession]:
    session = get_async_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
