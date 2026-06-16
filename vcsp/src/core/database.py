"""
Database configuration using SQLAlchemy with async support.

Why async?
- FastAPI is async-first
- Async DB calls don't block the server
- Better performance under load (many concurrent users)
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
from sqlalchemy import DateTime, func
import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


# Create async engine - the connection pool to PostgreSQL
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,       # Log SQL queries in debug mode
    pool_pre_ping=True,        # Check connection health before using
    pool_size=10,              # Keep 10 connections ready
    max_overflow=20,           # Allow 20 extra connections under load
)

# Session factory - creates new DB sessions
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,    # Don't expire objects after commit (avoids lazy loading issues)
)


class Base(DeclarativeBase):
    """
    Base class for all database models.

    Why a custom Base?
    - Add shared columns (created_at, updated_at) to all models
    - Consistent behavior across the app
    """
    pass


class BaseMixin:
    """
    Mixin that adds created_at and updated_at to any model with UUID.

    Why a mixin?
    - DRY principle: define once, use everywhere
    - Every table needs these audit columns
    """
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )


async def get_db() -> AsyncSession:
    """
    Dependency injection for FastAPI routes.

    Usage in routes:
        @router.get("/")
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...

    Why a generator?
    - Ensures the session is always closed after the request
    - Even if an exception occurs (try/finally pattern)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
