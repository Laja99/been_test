"""
نماذج قاعدة البيانات لـ Identity feature.

كل كلاس هنا = جدول في قاعدة البيانات.
SQLAlchemy يحول الكلاسات دي لـ SQL تلقائياً.
"""
import re

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bayn.core.database import Base


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class UserRole(str, enum.Enum):
    """
    دور المستخدم في النظام.
    USER  = مستخدم عادي (الغالبية).
    ADMIN = صلاحيات كاملة، لا يُعطى إلا من قاعدة البيانات مباشرة.
    """
    USER = "user"
    ADMIN = "admin"


class OTPChannel(str, enum.Enum):
    """
    القناة اللي أُرسل عبرها الـ OTP.
    EMAIL = إيميل.
    SMS   = رسالة نصية.
    """
    EMAIL = "email"
    SMS = "sms"


class OTPStatus(str, enum.Enum):
    """
    حالة طلب الـ OTP.
    SENT     = أُرسل ولم يُتحقق منه بعد.
    VERIFIED = تم التحقق بنجاح.
    EXPIRED  = انتهت صلاحيته (يحدده Authentica من جهته).
    """
    SENT = "sent"
    VERIFIED = "verified"
    EXPIRED = "expired"


# ─────────────────────────────────────────────
# Country
# ─────────────────────────────────────────────

class Country(Base):
    """
    جدول الدول — يُستخدم لمفتاح الهاتف (dial_code) وقائمة الاختيار في الواجهة.
    البيانات ثابتة تقريباً، تُحشى مرة واحدة عبر seed script.
    """
    __tablename__ = "countries"

    # المعرف الفريد لكل دولة
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # اسم الدولة بالإنجليزي — مثل "Saudi Arabia"
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)

    # اسم الدولة بالعربي — مثل "المملكة العربية السعودية"
    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)

    # رمز ISO المكون من حرفين — مثل "SA" أو "US"، فريد لكل دولة
    iso2: Mapped[str] = mapped_column(String(2), unique=True, nullable=False)

    # مفتاح الاتصال الدولي — مثل "+966" أو "+1"
    dial_code: Mapped[str] = mapped_column(String(10), nullable=False)

    # توقيت الإنشاء — يُضبط تلقائياً من قاعدة البيانات
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # توقيت آخر تعديل — يُحدَّث تلقائياً عند كل تغيير
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # العلاقة العكسية: كل المستخدمين المرتبطين بهذه الدولة
    users: Mapped[list["User"]] = relationship("User", back_populates="phone_country")

    def __repr__(self) -> str:
        return f"<Country {self.iso2} - {self.name_en}>"


# ─────────────────────────────────────────────
# User
# ─────────────────────────────────────────────

class User(Base):
    """
    المستخدم الأساسي في النظام.

    الاسم مقسم لأربعة حقول (أول / ثاني / ثالث / أخير) بالعربي والإنجليزي
    لأن الهوية الوطنية تتطلب الاسم الرباعي.

    avatar_key = مفتاح الصورة في R2 (Cloudflare) وليس URL كاملاً،
    لأن الـ URL يتولد عند الطلب من خلال integration الـ storage.

    deleted_at = حذف ناعم (soft delete): بدل ما نحذف السجل نضع تاريخ الحذف،
    البيانات تبقى محفوظة للـ audit trail.
    """
    __tablename__ = "users"

    # ── المعرف ──────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── الاسم بالعربي (رباعي) ────────────────────
    first_name_ar: Mapped[str] = mapped_column(String(50), nullable=False)
    second_name_ar: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    third_name_ar: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_name_ar: Mapped[str] = mapped_column(String(50), nullable=False)

    # ── الاسم بالإنجليزي (رباعي) ─────────────────
    first_name_en: Mapped[str] = mapped_column(String(50), nullable=False)
    second_name_en: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    third_name_en: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_name_en: Mapped[str] = mapped_column(String(50), nullable=False)

    # ── الهوية الوطنية ──────────────────────────
    # فريدة لكل مستخدم، اختيارية في البداية لأن بعض المستخدمين قد لا يدخلونها فوراً
    national_id: Mapped[Optional[str]] = mapped_column(
        String(20), unique=True, nullable=True
    )

    # ── بيانات الدخول ──────────────────────────
    # email و username كلاهما فريد — يُستخدم email في تسجيل الدخول
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)

    # الباسورد مخزن كـ hash فقط — لا يُخزن الباسورد الأصلي أبداً
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── الهاتف ──────────────────────────────────
    # phone_country_id = FK لجدول countries لتخزين مفتاح الدولة (+966 إلخ)
    phone_country_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("countries.id"), nullable=True
    )
    phone_country: Mapped[Optional[str]] = mapped_column(
      String(4), nullable=True
    )
    # رقم الهاتف بدون مفتاح الدولة — مثل 501234567
    phone_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── الموقع والتخصص ──────────────────────────
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # industry_id = FK لجدول industries (موجود في catalog feature)
    industry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("industries.id"), nullable=True
    )

    # ── الصلاحية ──────────────────────────────
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.USER, nullable=False
    )

    # ── الملف الشخصي ──────────────────────────
    # مفتاح الصورة في R2 — مثل "avatars/uuid.jpg"
    # لا يُخزن URL كامل لأن الـ URL يتغير إذا تغير الـ bucket أو الـ CDN
    avatar_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # رابط GitHub أو GitLab أو Bitbucket
    git_profile: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ── Cal.com integration ────────────────────
    # هذه الحقول تُملأ عند ربط حساب Cal.com بالمستخدم
    calcom_user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    calcom_access_token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    calcom_refresh_token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # ── حالة الحساب ──────────────────────────
    # is_active: حساب مفعّل (True) أو موقوف (False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # is_email_verified: هل تم التحقق من الإيميل عبر OTP
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # is_number_verified: هل تم التحقق من رقم الهاتف عبر OTP
    is_number_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── التواريخ ──────────────────────────────
    # deleted_at = null → الحساب نشط، أي قيمة → محذوف (soft delete)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── العلاقات ──────────────────────────────
    # الدولة المرتبطة برقم الهاتف
    phone_country: Mapped[Optional["Country"]] = relationship(
        "Country", back_populates="users"
    )

    # سجلات OTP الخاصة بهذا المستخدم
    otp_logs: Mapped[list["AuthenticaOTPLog"]] = relationship(
        "AuthenticaOTPLog", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.email})>"


# ─────────────────────────────────────────────
# Authentica OTP Log
# ─────────────────────────────────────────────

class AuthenticaOTPLog(Base):
    """
    سجل كل طلبات OTP المرسلة عبر Authentica.

    لماذا نحتفظ بهذا السجل؟
    - للـ audit trail: نعرف متى أُرسل الـ OTP ومتى تم التحقق منه.
    - للحماية من الإساءة: نقدر نحدد كم مرة طلب المستخدم OTP.
    - reference_id = المعرف اللي يرجعه Authentica، نحتاجه عند التحقق.

    ملاحظة: الـ OTP نفسه لا يُخزن هنا — Authentica هو اللي يتحقق منه.
    """
    __tablename__ = "authentica_otp_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # المستخدم اللي طلب الـ OTP
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # القناة: email أو sms
    channel: Mapped[OTPChannel] = mapped_column(Enum(OTPChannel), nullable=False)

    # المعرف اللي يرجعه Authentica — نحتاجه لاحقاً عند إرسال طلب التحقق
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # الحالة الحالية للطلب
    status: Mapped[OTPStatus] = mapped_column(
        Enum(OTPStatus), default=OTPStatus.SENT, nullable=False
    )

    # متى أُرسل الـ OTP
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # متى تم التحقق منه — null إذا لم يتم التحقق بعد
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # توقيت إنشاء السجل في قاعدة البيانات
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # العلاقة مع المستخدم
    user: Mapped["User"] = relationship("User", back_populates="otp_logs")

    def __repr__(self) -> str:
        return f"<OTPLog user={self.user_id} channel={self.channel} status={self.status}>"
