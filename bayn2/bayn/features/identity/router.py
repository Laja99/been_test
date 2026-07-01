"""
Identity Router — كل الـ HTTP endpoints للـ auth والملف الشخصي.

القاعدة هنا:
- الـ router يتكلم HTTP فقط: يستقبل requests، يرجع responses، يرفع HTTP exceptions.
- أي business logic يذهب للـ service.
- الـ dependencies تتولى المصادقة وجلب current user.
"""

import jwt
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from bayn.common.exceptions import InvalidTokenError
from bayn.core.database import get_db
from bayn.core.security import decode_token
from bayn.features.identity import service
from bayn.core.i18n import get_locale
from bayn.features.identity.dependencies import get_current_active_user
from bayn.features.identity.models import User
from bayn.features.identity.schemas import (
    MessageResponse,
    OTPSendResponse,
    OTPVerifyRequest,
    RefreshTokenRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
    UserSignup,
    UserLogin,
)

# prefix = البادئة المشتركة لكل endpoints في هذا الـ router
# tags  = تظهر في Swagger UI لتنظيم الـ endpoints
router = APIRouter(prefix="/auth", tags=["Identity"])


# ─────────────────────────────────────────────
# Auth: التسجيل والدخول والتجديد
# ─────────────────────────────────────────────

@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=201,
    summary="إنشاء حساب جديد",
)
async def signup(
    payload: UserSignup,
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> TokenResponse:
    """
    ينشئ حساباً جديداً ويسجّل الدخول تلقائياً.
    يرجع access_token + refresh_token + بيانات المستخدم.
    """
    return await service.create_user(db, payload, locale)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="تسجيل الدخول",
)
async def login(
    payload: UserLogin,
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> TokenResponse:
    """
    يتحقق من بيانات الدخول ويرجع tokens.
    يرفع 401 إذا كانت البيانات خاطئة.
    """
    return await service.authenticate_user(db, payload, locale)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="تجديد الـ access token",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> TokenResponse:
    """
    يصدر access token جديد باستخدام refresh token صالح.
    يُستدعى عندما ينتهي الـ access token (401 من أي endpoint محمي).

    نحن نتولى decode الـ refresh token هنا (لا في الـ dependency)
    لأن الـ dependency يتوقع access token.
    """
    try:
        # decode_token يتحقق من التوقيع وانتهاء الصلاحية ونوع الـ token
        user_id = decode_token(payload.refresh_token, expected_type="refresh")
    except jwt.PyJWTError:
        raise InvalidTokenError()

    return await service.refresh_access_token(db, user_id, locale)


# ─────────────────────────────────────────────
# Profile: الملف الشخصي للمستخدم الحالي
# ─────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserResponse,
    summary="جلب بيانات المستخدم الحالي",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """
    يرجع بيانات المستخدم المسجّل دخوله.
    يتطلب Authorization: Bearer <access_token>.
    """
    # الـ service يبني الـ response مع avatar_url
    from bayn.features.identity.service import _build_user_response
    return _build_user_response(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="تحديث الملف الشخصي",
)
async def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    يحدث بيانات الملف الشخصي — partial update.
    ترسل فقط الحقول اللي تريد تغييرها.
    """
    return await service.update_profile(db, current_user, payload)


@router.delete(
    "/me",
    response_model=MessageResponse,
    summary="حذف الحساب (soft delete)",
)
async def delete_me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    يحذف الحساب بشكل ناعم — deleted_at يُضبط والبيانات تبقى.
    لا يمكن التراجع عن هذه العملية من الـ API.
    """
    await service.soft_delete_account(db, current_user)
    return MessageResponse(message="Account deleted successfully")


# ─────────────────────────────────────────────
# Avatar: صورة المستخدم
# ─────────────────────────────────────────────

@router.post(
    "/me/avatar",
    response_model=UserResponse,
    summary="رفع أو تحديث صورة الملف الشخصي",
)
async def upload_avatar(
    file: UploadFile = File(..., description="صورة بصيغة JPG أو PNG أو WebP، بحد أقصى 5MB"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> UserResponse:
    """
    يرفع صورة للملف الشخصي لـ Cloudflare R2.
    إذا كانت هناك صورة قديمة يستبدلها تلقائياً.
    """
    # نقرأ محتوى الملف — UploadFile هو async
    file_bytes = await file.read()

    return await service.upload_avatar(
        db=db,
        user=current_user,
        file_bytes=file_bytes,
        content_type=file.content_type or "",
        locale=locale,
    )


@router.delete(
    "/me/avatar",
    response_model=UserResponse,
    summary="حذف صورة الملف الشخصي",
)
async def delete_avatar(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> UserResponse:
    """
    يحذف صورة الملف الشخصي من R2 وقاعدة البيانات.
    يرفع 400 إذا لم تكن هناك صورة أصلاً.
    """
    return await service.delete_avatar(db, current_user, locale)


# ─────────────────────────────────────────────
# OTP: التحقق من الإيميل
# ─────────────────────────────────────────────

@router.post(
    "/verify-email/send",
    response_model=OTPSendResponse,
    summary="إرسال OTP للإيميل",
)
async def send_email_otp(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> OTPSendResponse:
    """
    يرسل رمز OTP للإيميل المسجل عبر Authentica.
    يرجع reference_id يجب على الـ frontend الاحتفاظ به.
    """
    return await service.send_email_otp(db, current_user, locale)


@router.post(
    "/verify-email/confirm",
    response_model=UserResponse,
    summary="تأكيد OTP الإيميل",
)
async def confirm_email_otp(
    payload: OTPVerifyRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> UserResponse:
    """
    يتحقق من رمز OTP الإيميل.
    عند النجاح: is_email_verified = true.

    [تغيير] payload يحتوي على otp_code فقط (حذفنا reference_id).
    """
    return await service.verify_email_otp(
        db=db,
        user=current_user,
        otp_code=payload.otp_code,
        locale=locale,
    )


# ─────────────────────────────────────────────
# OTP: التحقق من الهاتف
# ─────────────────────────────────────────────

@router.post(
    "/verify-phone/send",
    response_model=OTPSendResponse,
    summary="إرسال OTP للهاتف",
)
async def send_phone_otp(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> OTPSendResponse:
    """
    يرسل رمز OTP عبر SMS لرقم الهاتف المسجل.
    يتطلب أن يكون phone_number و phone_country_id محددَين في الملف الشخصي.
    """
    return await service.send_phone_otp(db, current_user, locale)


@router.post(
    "/verify-phone/confirm",
    response_model=UserResponse,
    summary="تأكيد OTP الهاتف",
)
async def confirm_phone_otp(
    payload: OTPVerifyRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    locale: str = Depends(get_locale),
) -> UserResponse:
    """
    يتحقق من رمز OTP الهاتف.
    عند النجاح: is_number_verified = true.

    [تغيير] payload يحتوي على otp_code فقط (حذفنا reference_id).
    """
    return await service.verify_phone_otp(
        db=db,
        user=current_user,
        otp_code=payload.otp_code,
        locale=locale,
    )
