"""
إعدادات الاختبارات المشتركة.

conftest.py = ملف خاص بـ pytest يُحمَّل تلقائياً قبل أي test.
يحتوي على fixtures مشتركة بين كل الاختبارات.

كيف تشغل التستات:
    pytest tests/ -v
    pytest tests/features/identity/ -v
    pytest tests/ -v --tb=short
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bayn.common.exceptions import NotFoundError
from bayn.core.database import Base, get_db
from bayn.core.security import create_access_token, hash_password
from bayn.features.identity.models import Country, User, UserRole
from bayn.main import app

# ─────────────────────────────────────────────
# قاعدة بيانات للاختبارات
# ─────────────────────────────────────────────

# نستخدم SQLite في الذاكرة — سريع ولا يحتاج Postgres مثبت
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="session")
def event_loop():
    """event loop واحد لكل الـ session — يحسن الأداء."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """
    ينشئ الجداول مرة واحدة قبل كل الاختبارات
    ويحذفها بعد الانتهاء.
    scope="session" = يعمل مرة واحدة للـ session كلها.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """
    يوفر database session نظيفة لكل test.
    يعمل rollback بعد كل test حتى لا تؤثر التستات على بعض.
    """
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP client للاختبار يستخدم قاعدة البيانات التجريبية.
    نستبدل get_db dependency بقاعدة البيانات التجريبية.
    """
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# Fixtures للبيانات
# ─────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_country(db: AsyncSession) -> Country:
    """دولة تجريبية — السعودية."""
    country = Country(
        name_en="Saudi Arabia",
        name_ar="المملكة العربية السعودية",
        iso2="SA",
        dial_code="+966",
    )
    db.add(country)
    await db.commit()
    await db.refresh(country)
    return country


@pytest_asyncio.fixture
async def test_user(db: AsyncSession, test_country: Country) -> User:
    """مستخدم تجريبي جاهز — يُستخدم في تستات تحتاج مستخدم موجود مسبقاً."""
    user = User(
        first_name_ar="محمد",
        last_name_ar="الأحمد",
        first_name_en="Mohammed",
        last_name_en="Al-Ahmad",
        email="test@example.com",
        username="mohammed_test",
        password_hash=hash_password("TestPass123"),
        phone_country_id=test_country.id,
        phone_number=501234567,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user: User) -> dict:
    """
    Authorization headers جاهزة للاستخدام في requests المحمية.

    الاستخدام:
        response = await client.get("/auth/me", headers=auth_headers)
    """
    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
def mock_authentica():
    """
    يُعطل الـ Authentica API الحقيقي أثناء الاختبارات.
    بدله يرجع نجاح تلقائي حتى لا نحتاج credentials حقيقية.
    """
    with patch("src.integrations.authentica.authentica_client") as mock:
        mock.send_email_otp = AsyncMock(return_value=None)
        mock.send_sms_otp = AsyncMock(return_value=None)
        mock.verify_email_otp = AsyncMock(return_value=True)
        mock.verify_sms_otp = AsyncMock(return_value=True)
        yield mock


@pytest_asyncio.fixture
def mock_r2():
    """
    يُعطل Cloudflare R2 أثناء الاختبارات.
    بدله يرجع مفتاح وهمي.
    """
    with patch("src.integrations.storage.cloudflare.r2_client") as mock:
        mock.upload_avatar.return_value = "avatars/test-user.jpg"
        mock.delete_avatar.return_value = None
        mock.get_avatar_url.return_value = "https://pub-test.r2.dev/avatars/test-user.jpg"
        yield mock
