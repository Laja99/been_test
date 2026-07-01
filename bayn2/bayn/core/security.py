"""
أدوات الأمان: تشفير الباسورد و JWT tokens.

- تشفير الباسورد: passlib + bcrypt
- JWT: access token (قصير العمر، يُرسل مع كل request)
       refresh token (طويل العمر، يُستخدم فقط لتجديد الـ access token)
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from bayn.core.config import settings

# ─────────────────────────────────────────────
# Password Hashing
# ─────────────────────────────────────────────

# CryptContext يدير خوارزمية الـ hashing
# deprecated="auto" = إذا أضفنا خوارزمية جديدة، القديمة تُرفض تلقائياً
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """يحول الباسورد النصي لـ hash مشفر للتخزين في قاعدة البيانات."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """يتحقق من أن الباسورد المدخل مطابق للـ hash المخزن."""
    return pwd_context.verify(plain_password, password_hash)


# ─────────────────────────────────────────────
# JWT Tokens
# ─────────────────────────────────────────────

# "sub" = معرف المستخدم، "type" = نوع الـ token (access/refresh)
TokenType = Literal["access", "refresh"]


def _create_token(
    user_id: uuid.UUID,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    """دالة داخلية مشتركة لإنشاء الـ tokens."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),   # subject = معرف المستخدم
        "type": token_type,    # نميز بين access و refresh
        "iat": now,            # issued at = وقت الإصدار
        "exp": now + expires_delta,  # expiry = وقت الانتهاء
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(user_id: uuid.UUID) -> str:
    """
    token قصير العمر — يُرسل في Authorization header مع كل request.
    ينتهي بعد ACCESS_TOKEN_EXPIRE_MINUTES دقيقة (افتراضي 15 دقيقة).
    """
    return _create_token(
        user_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    """
    token طويل العمر — يُستخدم فقط لطلب access token جديد.
    ينتهي بعد REFRESH_TOKEN_EXPIRE_DAYS أيام (افتراضي 7 أيام).
    """
    return _create_token(
        user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    """
    يفك تشفير الـ JWT ويتحقق منه، ويرجع user_id.

    يرفع jwt.InvalidTokenError إذا:
    - الـ token منتهي الصلاحية
    - التوقيع غلط
    - النوع غير متوقع (مثلاً refresh token في مكان access)
    """
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )

    # نتحقق من النوع صراحةً — refresh token مرفوض في endpoints الـ access
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(
            f"Expected {expected_type} token, got {payload.get('type')}"
        )

    return uuid.UUID(payload["sub"])
