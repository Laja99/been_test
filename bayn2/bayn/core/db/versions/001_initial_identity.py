"""إنشاء جداول identity feature الأولية.

Revision ID: 001
Revises: 
Create Date: 2025-01-01 00:00:00

الجداول:
    - countries: الدول لمفتاح الهاتف
    - users: المستخدمين
    - authentica_otp_logs: سجلات OTP
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers
revision: str = "001_initial_identity"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """إنشاء الجداول."""

    # ─── جدول countries ───────────────────────
    op.create_table(
        "countries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("name_ar", sa.String(100), nullable=False),
        sa.Column("iso2", sa.String(2), nullable=False, unique=True),
        sa.Column("dial_code", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ─── جدول users ───────────────────────────
    op.create_table(
        "users",
        # المعرف
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),

        # الاسم بالعربي
        sa.Column("first_name_ar", sa.String(50), nullable=False),
        sa.Column("second_name_ar", sa.String(50), nullable=True),
        sa.Column("third_name_ar", sa.String(50), nullable=True),
        sa.Column("last_name_ar", sa.String(50), nullable=False),

        # الاسم بالإنجليزي
        sa.Column("first_name_en", sa.String(50), nullable=False),
        sa.Column("second_name_en", sa.String(50), nullable=True),
        sa.Column("third_name_en", sa.String(50), nullable=True),
        sa.Column("last_name_en", sa.String(50), nullable=False),

        # هوية وبيانات دخول
        sa.Column("national_id", sa.String(20), nullable=True, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("username", sa.String(30), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),

        # الهاتف
        sa.Column("phone_country_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("countries.id"), nullable=True),
        sa.Column("phone_number", sa.Integer, nullable=True),

        # الملف الشخصي
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("industry_id", postgresql.UUID(as_uuid=True), nullable=True),  # FK لـ catalog لاحقاً
        sa.Column("git_profile", sa.String(255), nullable=True),
        sa.Column("avatar_key", sa.String(500), nullable=True),

        # Cal.com
        sa.Column("calcom_user_id", sa.String(100), nullable=True),
        sa.Column("calcom_access_token", sa.String(500), nullable=True),
        sa.Column("calcom_refresh_token", sa.String(500), nullable=True),

        # الدور والحالة
        sa.Column("role", sa.Enum("user", "admin", name="userrole"), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_email_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_number_verified", sa.Boolean, nullable=False, server_default="false"),

        # التواريخ
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # indexes للـ queries الشائعة
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    # ─── جدول authentica_otp_logs ─────────────
    op.create_table(
        "authentica_otp_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.Enum("email", "sms", name="otpchannel"), nullable=False),
        sa.Column("reference_id", sa.String(255), nullable=False),
        sa.Column("status", sa.Enum("sent", "verified", "expired", name="otpstatus"), nullable=False, server_default="sent"),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_otp_logs_user_id", "authentica_otp_logs", ["user_id"])
    op.create_index("ix_otp_logs_status", "authentica_otp_logs", ["status"])


def downgrade() -> None:
    """حذف الجداول — يُستخدم للتراجع."""
    op.drop_table("authentica_otp_logs")
    op.drop_index("ix_users_deleted_at", "users")
    op.drop_index("ix_users_username", "users")
    op.drop_index("ix_users_email", "users")
    op.drop_table("users")
    op.drop_table("countries")
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS otpchannel")
    op.execute("DROP TYPE IF EXISTS otpstatus")
