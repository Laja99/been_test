"""
Identity Service — طبقة الـ Business Logic.

القاعدة هنا: لا يوجد أي HTTP concern (لا status codes، لا Request، لا Response).
الـ router هو من يتحدث HTTP — هذه الطبقة تتحدث فقط business logic.

كل الـ exceptions اللي تُرفع هنا هي من common/exceptions.py،
والـ router يتركها تصل للـ exception handler في main.py اللي يحولها لـ HTTP response.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bayn.common.exceptions import (
    ForbiddenError,
    InvalidCredentialsError,
    NotFoundError,
    UserAlreadyExistsError,
    ValidationError,
)
from bayn.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from bayn.core.i18n import DEFAULT_LOCALE, t
from bayn.features.identity.models import AuthenticaOTPLog, OTPChannel, OTPStatus, User
from bayn.features.identity.schemas import (
    OTPSendResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
    UserSignup,
    UserLogin,
)
from bayn.integrations.authentica import AuthenticaError, AuthenticaOTPInvalid, authentica_client
from bayn.integrations.storage.cloudflare import InvalidFileError, StorageError, r2_client


# ─────────────────────────────────────────────
# Helper: بناء UserResponse
# ─────────────────────────────────────────────

def _build_user_response(user: User) -> UserResponse:
    """
    يحول User model لـ UserResponse schema.

    avatar_url يُولَّد هنا من avatar_key — الـ schema لا يعرف شيئاً عن R2.
    إذا لم توجد صورة → avatar_url = None.
    """
    # نولّد الـ URL فقط إذا كان المفتاح موجوداً
    avatar_url = None
    if user.avatar_key:
        try:
            avatar_url = r2_client.get_avatar_url(user.avatar_key)
        except StorageError:
            # إذا فشل توليد الـ URL لا نوقف الـ response — نرجع None فقط
            avatar_url = None

    return UserResponse(
        id=user.id,
        first_name_ar=user.first_name_ar,
        second_name_ar=user.second_name_ar,
        third_name_ar=user.third_name_ar,
        last_name_ar=user.last_name_ar,
        first_name_en=user.first_name_en,
        second_name_en=user.second_name_en,
        third_name_en=user.third_name_en,
        last_name_en=user.last_name_en,
        national_id=user.national_id,
        email=user.email,
        username=user.username,
        phone_country=user.phone_country,
        phone_number=user.phone_number,
        city=user.city,
        industry_id=user.industry_id,
        git_profile=user.git_profile,
        avatar_url=avatar_url,
        role=user.role.value,
        is_active=user.is_active,
        is_email_verified=user.is_email_verified,
        is_number_verified=user.is_number_verified,
        created_at=user.created_at,
    )


# ─────────────────────────────────────────────
# Helper: إصدار الـ tokens
# ─────────────────────────────────────────────

def _issue_tokens(user: User) -> TokenResponse:
    """
    يصدر access + refresh token pair للمستخدم.
    يُستدعى بعد التسجيل وبعد الدخول — كلاهما ينتهي بـ "سجّل الدخول".
    """
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=_build_user_response(user),
    )


# ─────────────────────────────────────────────
# Queries
# ─────────────────────────────────────────────

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """يبحث عن مستخدم بالإيميل — يرجع None إذا غير موجود."""
    result = await db.execute(
        select(User)
        .where(User.email == email, User.deleted_at.is_(None))
        .options(selectinload(User.phone_country))  # نجلب بيانات الدولة مع المستخدم
    )
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """يبحث عن مستخدم بالـ username — يرجع None إذا غير موجود."""
    result = await db.execute(
        select(User).where(User.username == username, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID, locale: str = DEFAULT_LOCALE) -> User:
    """
    يجلب المستخدم بالـ ID — يرفع NotFoundError إذا غير موجود.

    يختلف عن get_user_by_email في أنه يرفع exception لا يرجع None،
    لأنه يُستخدم في الـ auth dependency حيث "غير موجود" = token لحساب محذوف.
    """
    result = await db.execute(
        select(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .options(selectinload(User.phone_country))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError(t("auth.user_not_found", locale))
    return user


# ─────────────────────────────────────────────
# Auth: التسجيل والدخول والتجديد
# ─────────────────────────────────────────────

async def create_user(db: AsyncSession, payload: UserSignup, locale: str = DEFAULT_LOCALE) -> TokenResponse:
    """
    ينشئ حساب جديد.

    الترتيب مهم:
    1. نتحقق من uniqueness للإيميل والـ username أولاً — نعطي رسالة واضحة
       بدل ما نترك Postgres يرفع IntegrityError غير واضح.
    2. نعمل hash للباسورد — لا يُخزن الباسورد الأصلي أبداً.
    3. ننشئ المستخدم ونحفظ.
    4. نصدر tokens مباشرة — التسجيل = دخول تلقائي، بدون request إضافي.
    """
    # خطوة 1: التحقق من عدم التكرار
    if await get_user_by_email(db, payload.email):
        raise UserAlreadyExistsError(t("auth.email_already_in_use", locale))

    if await get_user_by_username(db, payload.username):
        raise UserAlreadyExistsError(t("auth.username_already_in_use", locale))

    # خطوة 2: إنشاء المستخدم مع hash الباسورد
    user = User(
        first_name_ar=payload.first_name_ar,
        second_name_ar=payload.second_name_ar,
        third_name_ar=payload.third_name_ar,
        last_name_ar=payload.last_name_ar,
        first_name_en=payload.first_name_en,
        second_name_en=payload.second_name_en,
        third_name_en=payload.third_name_en,
        last_name_en=payload.last_name_en,
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        phone_country_id=payload.phone_country_id,
        phone_number=payload.phone_number,
    )

    # خطوة 3: الحفظ في قاعدة البيانات
    db.add(user)
    await db.commit()
    # refresh يجلب القيم اللي أنشأها الـ DB: id، created_at، updated_at
    await db.refresh(user)

    # خطوة 4: إصدار الـ tokens
    return _issue_tokens(user)


async def authenticate_user(db: AsyncSession, payload: UserLogin, locale: str = DEFAULT_LOCALE) -> TokenResponse:
    """
    يتحقق من بيانات الدخول ويصدر tokens.

    نرفع نفس الخطأ سواء كان الإيميل غير موجود أو الباسورد غلط.
    السبب: إذا أعطينا رسالة مختلفة لكل حالة، يقدر المهاجم يعرف
    أي الإيميلات مسجلة في النظام (user enumeration attack).
    """
    user = await get_user_by_email(db, payload.email)

    # نتحقق من الإيميل والباسورد معاً قبل ما نعطي أي خطأ
    if user is None or not verify_password(payload.password, user.password_hash):
        raise InvalidCredentialsError(t("auth.invalid_credentials", locale))

    if not user.is_active:
        raise InvalidCredentialsError(t("auth.invalid_credentials", locale))

    return _issue_tokens(user)


async def refresh_access_token(db: AsyncSession, user_id: uuid.UUID, locale: str = DEFAULT_LOCALE) -> TokenResponse:
    """
    يصدر token pair جديد بعد التحقق من الـ refresh token.

    decode_token يُستدعى في الـ router قبل هذه الدالة —
    بحلول الوقت اللي نصل هنا user_id موثوق فيه.
    نعيد التحقق من وجود المستخدم ونشاطه لأن الحساب قد يُحذف
    أو يُوقف بعد إصدار الـ refresh token.
    """
    user = await get_user_by_id(db, user_id, locale)

    if not user.is_active:
        raise InvalidCredentialsError(t("auth.invalid_credentials", locale))

    return _issue_tokens(user)


# ─────────────────────────────────────────────
# Profile: الملف الشخصي
# ─────────────────────────────────────────────

async def update_profile(
    db: AsyncSession,
    user: User,
    payload: UpdateProfileRequest,
) -> UserResponse:
    """
    يحدث الملف الشخصي — partial update (PATCH).

    model_dump(exclude_unset=True) يرجع فقط الحقول اللي أرسلها المستخدم،
    فلو أرسل city فقط → نحدث city فقط ونترك الباقي.
    """
    # نأخذ فقط الحقول اللي أُرسلت فعلياً
    updates = payload.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    return _build_user_response(user)


async def soft_delete_account(db: AsyncSession, user: User) -> None:
    """
    يحذف الحساب بشكل ناعم (soft delete).

    بدل ما نحذف السجل، نضع تاريخ الحذف في deleted_at.
    البيانات تبقى محفوظة لـ audit trail، والـ queries تستثني
    السجلات اللي deleted_at ليس null.
    """
    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    await db.commit()


# ─────────────────────────────────────────────
# Avatar: صورة المستخدم
# ─────────────────────────────────────────────

async def upload_avatar(
    db: AsyncSession,
    user: User,
    file_bytes: bytes,
    content_type: str,
    locale: str = DEFAULT_LOCALE,
) -> UserResponse:
    """
    يرفع صورة المستخدم لـ R2 ويحدث avatar_key في قاعدة البيانات.

    الترتيب:
    1. نرفع الصورة الجديدة لـ R2 أولاً.
    2. إذا كان عنده صورة قديمة، نحذفها بعد نجاح الرفع الجديد.
    3. نحدث avatar_key في قاعدة البيانات.

    نرفع الجديدة أولاً عشان: إذا فشل الرفع الجديد، تبقى القديمة.
    نحذف القديمة ثانياً عشان: لو الحذف فشل، لا نفقد الجديدة.
    """
    try:
        # خطوة 1: رفع الصورة الجديدة
        new_avatar_key = r2_client.upload_avatar(user.id, file_bytes, content_type)
    except InvalidFileError as e:
        # نوع غير مسموح أو حجم كبير — خطأ من المستخدم
        raise ValidationError(e.message)
    except StorageError as e:
        raise ValidationError(t("avatar.upload_failed", locale))

    # خطوة 2: حذف الصورة القديمة إذا وجدت
    if user.avatar_key and user.avatar_key != new_avatar_key:
        try:
            r2_client.delete_avatar(user.avatar_key)
        except StorageError:
            # لو الحذف فشل نتجاهله — الأهم أن الجديدة اترفعت
            pass

    # خطوة 3: تحديث الـ key في قاعدة البيانات
    user.avatar_key = new_avatar_key
    await db.commit()
    await db.refresh(user)

    return _build_user_response(user)


async def delete_avatar(db: AsyncSession, user: User, locale: str = DEFAULT_LOCALE) -> UserResponse:
    """
    يحذف صورة المستخدم من R2 وقاعدة البيانات.
    إذا لم تكن لديه صورة يرفع ValidationError.
    """
    if not user.avatar_key:
        raise ValidationError(t("avatar.no_avatar_to_delete", locale))

    try:
        r2_client.delete_avatar(user.avatar_key)
    except StorageError as e:
        raise ValidationError(t("avatar.delete_failed", locale))

    user.avatar_key = None
    await db.commit()
    await db.refresh(user)

    return _build_user_response(user)


# ─────────────────────────────────────────────
# OTP: التحقق من الإيميل والهاتف
# ─────────────────────────────────────────────

async def send_email_otp(db: AsyncSession, user: User, locale: str = DEFAULT_LOCALE) -> OTPSendResponse:
    """
    يرسل OTP للإيميل عبر Authentica ويسجل الطلب في قاعدة البيانات.

    [تغيير] send_email_otp صارت void — لا ترجع reference_id.
    [تغيير] نخزن في الـ log string ثابت "n/a" بدل reference_id
            لأن Authentica لا يرجعه، لكن نبقي السجل للـ audit trail.
    """
    if user.is_email_verified:
        raise ValidationError(t("otp.email_already_verified", locale))

    try:
        await authentica_client.send_email_otp(user.email)
    except AuthenticaError:
        raise ValidationError(t("otp.send_failed", locale))

    otp_log = AuthenticaOTPLog(
        user_id=user.id,
        channel=OTPChannel.EMAIL,
        reference_id="n/a",
        status=OTPStatus.SENT,
    )
    db.add(otp_log)
    await db.commit()

    return OTPSendResponse(message=t("otp.sent_email", locale))


async def verify_email_otp(
    db: AsyncSession,
    user: User,
    otp_code: str,
    locale: str = DEFAULT_LOCALE,
) -> UserResponse:
    """
    يتحقق من OTP الإيميل ويحدث is_email_verified.

    [تغيير] حذفنا reference_id من parameters — مو موجود في Authentica API.
    [تغيير] نستخدم authentica_client.verify_email_otp(email, otp) مباشرة.
    [تغيير] نجلب آخر log بالإيميل بدل البحث بـ reference_id.
    """
    # نجلب آخر طلب OTP للإيميل لتحديث حالته
    result = await db.execute(
        select(AuthenticaOTPLog).where(
            AuthenticaOTPLog.user_id == user.id,
            AuthenticaOTPLog.channel == OTPChannel.EMAIL,
            AuthenticaOTPLog.status == OTPStatus.SENT,
        ).order_by(AuthenticaOTPLog.sent_at.desc()).limit(1)
    )
    otp_log = result.scalar_one_or_none()

    if otp_log is None:
        raise ValidationError(t("otp.no_pending_otp", locale))

    try:
        await authentica_client.verify_email_otp(user.email, otp_code)
    except AuthenticaOTPInvalid:
        raise ValidationError(t("otp.invalid_code", locale))
    except AuthenticaError:
        raise ValidationError(t("otp.verification_failed", locale))

    otp_log.status = OTPStatus.VERIFIED
    otp_log.verified_at = datetime.now(timezone.utc)
    user.is_email_verified = True

    await db.commit()
    await db.refresh(user)

    return _build_user_response(user)


async def send_phone_otp(db: AsyncSession, user: User, locale: str = DEFAULT_LOCALE) -> OTPSendResponse:
    """
    يرسل OTP عبر SMS.

    [تغيير] send_sms_otp صارت void — لا ترجع reference_id.
    [تغيير] نخزن "n/a" في reference_id بقاعدة البيانات.
    """
    if user.is_number_verified:
        raise ValidationError(t("otp.phone_already_verified", locale))

    if not user.phone_number or not user.phone_country_id:
        raise ValidationError(t("otp.phone_country_required", locale))

    if not user.phone_country:
        raise ValidationError(t("otp.phone_country_not_found", locale))

    try:
        await authentica_client.send_sms_otp(
            dial_code=user.phone_country.dial_code,
            phone_number=user.phone_number,
        )
    except AuthenticaError:
        raise ValidationError(t("otp.send_failed", locale))

    otp_log = AuthenticaOTPLog(
        user_id=user.id,
        channel=OTPChannel.SMS,
        reference_id="n/a",   # [تغيير] Authentica لا يرجع reference_id
        status=OTPStatus.SENT,
    )
    db.add(otp_log)
    await db.commit()

    return OTPSendResponse(message=t("otp.sent_phone", locale))


async def verify_phone_otp(
    db: AsyncSession,
    user: User,
    otp_code: str,
    locale: str = DEFAULT_LOCALE,
) -> UserResponse:
    """
    يتحقق من OTP الهاتف ويحدث is_number_verified.

    [تغيير] حذفنا reference_id من parameters.
    [تغيير] نستخدم authentica_client.verify_sms_otp(dial_code, phone, otp).
    [تغيير] نجلب آخر log بالـ SMS بدل البحث بـ reference_id.
    """
    if not user.phone_number or not user.phone_country:
        raise ValidationError(t("otp.phone_not_set", locale))

    result = await db.execute(
        select(AuthenticaOTPLog).where(
            AuthenticaOTPLog.user_id == user.id,
            AuthenticaOTPLog.channel == OTPChannel.SMS,
            AuthenticaOTPLog.status == OTPStatus.SENT,
        ).order_by(AuthenticaOTPLog.sent_at.desc()).limit(1)
    )
    otp_log = result.scalar_one_or_none()

    if otp_log is None:
        raise ValidationError(t("otp.no_pending_otp", locale))

    try:
        await authentica_client.verify_sms_otp(
            dial_code=user.phone_country.dial_code,
            phone_number=user.phone_number,
            otp_code=otp_code,
        )
    except AuthenticaOTPInvalid:
        raise ValidationError(t("otp.invalid_code", locale))
    except AuthenticaError:
        raise ValidationError(t("otp.verification_failed", locale))

    otp_log.status = OTPStatus.VERIFIED
    otp_log.verified_at = datetime.now(timezone.utc)
    user.is_number_verified = True

    await db.commit()
    await db.refresh(user)

    return _build_user_response(user)
