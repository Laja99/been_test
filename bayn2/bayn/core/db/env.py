"""
إعداد Alembic للـ migrations.

هذا الملف يربط Alembic بـ SQLAlchemy models عشان يقدر
يكتشف التغييرات تلقائياً ويولد migration scripts.

أوامر مهمة:
    # إنشاء migration جديد تلقائياً من التغييرات في الـ models
    alembic revision --autogenerate -m "add user table"

    # تطبيق آخر migration
    alembic upgrade head

    # التراجع عن آخر migration
    alembic downgrade -1

    # عرض التاريخ
    alembic history
"""

import asyncio
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# أضف /app إلى الـ path عشان يقدر يستورد bayn module
sys.path.insert(0, '/app')

# نستورد config و Base عشان Alembic يعرف الـ models والـ DATABASE_URL
from bayn.core.config import settings
from bayn.core.database import Base

# نستورد كل الـ models عشان تظهر في autogenerate
# (بدون الاستيراد لا يكتشفها Alembic)
from bayn.features.identity.models import AuthenticaOTPLog, Country, User  # noqa: F401

# ─────────────────────────────────────────────
# Alembic Config
# ─────────────────────────────────────────────

config = context.config

# نقرأ إعدادات الـ logging من alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Base.metadata يحتوي على كل الجداول — هذا ما يستخدمه autogenerate
target_metadata = Base.metadata

# نمرر الـ DATABASE_URL من settings بدل alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


# ─────────────────────────────────────────────
# Async Migration Functions
# ─────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    تشغيل migrations بدون اتصال حقيقي بقاعدة البيانات.
    يولد SQL scripts يمكن تطبيقها لاحقاً.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """تشغيل migrations عبر اتصال async حقيقي."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool مناسب للـ migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """نقطة دخول Alembic للـ migrations الـ online."""
    asyncio.run(run_async_migrations())


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
