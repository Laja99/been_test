"""
Pydantic schemas لـ Identity feature.

الفرق بين schemas و models:
- models.py  = SQLAlchemy = يصف شكل الجداول في قاعدة البيانات
- schemas.py = Pydantic   = يصف شكل البيانات اللي تدخل وتخرج من الـ API

قاعدة مهمة: لا يرجع password_hash أو أي بيانات حساسة في الـ response أبداً.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


# ─────────────────────────────────────────────
# Request Schemas (ما يصل للـ API من المستخدم)
# ─────────────────────────────────────────────

class UserSignup(BaseModel):
    """
    البيانات المطلوبة لإنشاء حساب جديد.
    الاسم رباعي بالعربي والإنجليزي إلزامي.
    """

    # الاسم بالعربي — الأول والأخير إلزامي، الثاني والثالث اختياري
    first_name_ar: str
    second_name_ar: Optional[str] = None
    third_name_ar: Optional[str] = None
    last_name_ar: str

    # الاسم بالإنجليزي — نفس القاعدة
    first_name_en: str
    second_name_en: Optional[str] = None
    third_name_en: Optional[str] = None
    last_name_en: str

    # بيانات الدخول
    email: EmailStr
    username: str
    password: str

    # الهاتف — اختياري عند التسجيل
    phone_country_id: Optional[uuid.UUID] = None
    phone_number: Optional[int] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """
        Username يجب أن:
        - يكون بين 3 و 30 حرف
        - يحتوي فقط على أحرف إنجليزية وأرقام وunderscore
        - يُخزن بحروف صغيرة دائماً (lowercase)
        """
        if not re.match(r"^[a-zA-Z0-9_]{3,30}$", value):
            raise ValueError(
                "Username must be 3-30 characters: letters, numbers, underscores only"
            )
        return value.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """
        الباسورد يجب أن:
        - لا يقل عن 8 أحرف
        - يحتوي على حرف كبير واحد على الأقل
        - يحتوي على حرف صغير واحد على الأقل
        - يحتوي على رقم واحد على الأقل
        """
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", value):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", value):
            raise ValueError("Password must contain at least one number")
        return value

class UserLogin(BaseModel):
    """بيانات تسجيل الدخول — إيميل وباسورد فقط."""
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    """طلب تجديد الـ access token باستخدام الـ refresh token."""
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    """
    تحديث جزئي للملف الشخصي (PATCH).
    كل الحقول اختيارية — يُحدَّث فقط ما يُرسَل.
    """
    # يُسمح بتحديث اسم المدينة
    city: Optional[str] = None

    # يُسمح بتحديث رابط GitHub
    git_profile: Optional[str] = None

    # يُسمح بتحديث التخصص الصناعي
    industry_id: Optional[uuid.UUID] = None

    # يُسمح بتحديث الهاتف
    phone_country_id: Optional[uuid.UUID] = None
    phone_number: Optional[int] = None

    # يُسمح بتحديث الرقم الوطني
    national_id: Optional[str] = None

    @field_validator("phone_number")
    @classmethod
    def validate_saudi_phone(cls, value: int | None) -> int | None:
        """التحقق من صيغة رقم الهاتف السعودي (نفس التحقق في UserSignup)."""
        if value is None:
            return None

        phone = str(value).strip()

        if phone.startswith('+966'):
            raise ValueError("Error: Phone number must be in format 5XXXXXXXX (e.g., 501234567), not +966")

        if phone.startswith('966'):
            raise ValueError("Error: Phone number must be in format 5XXXXXXXX (e.g., 501234567), not 966")

        if phone.startswith('0'):
            raise ValueError("Error: Phone number must be in format 5XXXXXXXX (e.g., 501234567), not 05XXXXXXX")

        if not phone.isdigit():
            raise ValueError("Error: Phone number must contain digits only.")

        if not re.match(r"^5\d{8}$", phone):
            raise ValueError("Error: Phone number must start with 5 and be exactly 9 digits long (e.g., 501234567).")

        return int(phone)


class OTPVerifyRequest(BaseModel):
    """
    تأكيد رمز OTP.

    [تغيير] حذفنا reference_id — Authentica لا يستخدمه.
    التحقق يتم بـ otp_code فقط، والـ email/phone يُؤخذ من current_user
    في الـ service مباشرة، مو من الـ request body.
    """
    otp_code: str


# ─────────────────────────────────────────────
# Response Schemas (ما يرجع للمستخدم من الـ API)
# ─────────────────────────────────────────────

class CountryResponse(BaseModel):
    """بيانات الدولة — تُستخدم في قائمة اختيار مفتاح الهاتف."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name_en: str
    name_ar: str
    iso2: str
    dial_code: str


class UserResponse(BaseModel):
    """
    بيانات المستخدم اللي تظهر في الـ API responses.
    لا يحتوي على password_hash أو أي بيانات Cal.com الحساسة.
    avatar_url يُولَّد من avatar_key عبر storage integration.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    # الاسم بالعربي
    first_name_ar: str
    second_name_ar: Optional[str]
    third_name_ar: Optional[str]
    last_name_ar: str

    # الاسم بالإنجليزي
    first_name_en: str
    second_name_en: Optional[str]
    third_name_en: Optional[str]
    last_name_en: str

    # الهوية الوطنية
    national_id: Optional[str]

    # بيانات الدخول (بدون باسورد)
    email: str
    username: str

    # الهاتف — مفتاح الدولة الدولي (مثل +966)
    phone_country_id: Optional[uuid.UUID]
    phone_number: Optional[int]

    # الملف الشخصي
    city: Optional[str]
    industry_id: Optional[uuid.UUID]
    git_profile: Optional[str]

    # avatar_url = None إذا لم يرفع المستخدم صورة
    # يُولَّد من avatar_key في service layer
    avatar_url: Optional[str] = None

    # الدور والحالة
    role: str
    is_active: bool
    is_email_verified: bool
    is_number_verified: bool

    # التواريخ
    created_at: datetime


class TokenResponse(BaseModel):
    """
    الـ tokens اللي تُرجع بعد التسجيل أو الدخول.
    access_token  = قصير العمر (15 دقيقة)، يُرسل مع كل request.
    refresh_token = طويل العمر (7 أيام)، يُستخدم فقط لتجديد الـ access token.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

    # بيانات المستخدم مباشرة في نفس الـ response لتوفير request إضافي
    user: UserResponse


class OTPSendResponse(BaseModel):
    """
    الـ response بعد إرسال OTP.

    [تغيير] حذفنا reference_id — Authentica لا يرجعه.
    الـ frontend يحتاج فقط يعرض رسالة النجاح ويطلب من المستخدم إدخال الرمز.
    """
    message: str


class MessageResponse(BaseModel):
    """Response بسيط لأي عملية ناجحة بدون بيانات إضافية."""
    message: str
