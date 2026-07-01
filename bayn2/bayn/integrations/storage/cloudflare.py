"""
Cloudflare R2 Storage Integration — خاص بصور المستخدمين.

R2 = خدمة تخزين من Cloudflare مثل S3 بالضبط،
لكن بدون رسوم على الـ egress (النقل الخارج).

الـ flow لرفع صورة:
1. المستخدم يرسل الصورة للـ API.
2. نتحقق من نوعها وحجمها.
3. نرفعها لـ R2 تحت مسار "avatars/{user_id}.{ext}".
4. نخزن avatar_key في قاعدة البيانات (المسار فقط، ليس الـ URL الكامل).
5. عند الحاجة للـ URL نولّده من R2_PUBLIC_URL + avatar_key.

لماذا نخزن المفتاح لا الـ URL الكامل؟
لأن الـ URL قد يتغير إذا غيرنا الـ domain أو الـ bucket،
لكن المفتاح يبقى ثابتاً ونولّد الـ URL منه دائماً.
"""

import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from bayn.core.config import settings


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

# أنواع الصور المسموح بها — نرفض أي شيء غيرها
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# الامتداد المقابل لكل MIME type
CONTENT_TYPE_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# الحجم الأقصى للصورة: 5 ميغابايت
MAX_AVATAR_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

# مجلد الصور داخل الـ bucket
AVATARS_FOLDER = "avatars"


# ─────────────────────────────────────────────
# Custom Exceptions
# ─────────────────────────────────────────────

class StorageError(Exception):
    """خطأ عام في التخزين — يُرفع عند فشل الاتصال بـ R2."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidFileError(StorageError):
    """الملف غير مقبول — نوع غير مسموح أو حجم كبير."""
    pass


# ─────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────

class CloudflareR2Client:
    """
    Client للتعامل مع Cloudflare R2.

    R2 متوافق مع S3 API — نستخدم boto3 (مكتبة AWS) لكن نغير الـ endpoint_url
    لـ Cloudflare بدل AWS.

    نُنشئ الـ client عند أول استخدام (lazy init) لأن بعض environments
    قد لا تحتوي على credentials (مثل بيئة التطوير المحلية).
    """

    def __init__(self) -> None:
        # _client = None حتى أول استخدام
        self._client = None

    def _get_client(self):
        """
        يُنشئ boto3 client إذا لم يكن موجوداً.
        Cloudflare R2 endpoint = https://<account_id>.r2.cloudflarestorage.com
        """
        if self._client is None:
            # نتأكد أن الـ credentials موجودة قبل المحاولة
            if not all([
                settings.R2_ACCOUNT_ID,
                settings.R2_ACCESS_KEY_ID,
                settings.R2_SECRET_ACCESS_KEY,
            ]):
                raise StorageError(
                    "R2 credentials not configured. "
                    "Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY in .env"
                )

            # endpoint_url = عنوان R2 الخاص بحسابك في Cloudflare
            endpoint_url = (
                f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            )

            # boto3 يتوقع region_name لكن R2 يستخدم "auto"
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                region_name="auto",
            )

        return self._client

    def _validate_avatar(self, file_bytes: bytes, content_type: str) -> None:
        """
        يتحقق من صحة الصورة قبل الرفع.
        يرفع InvalidFileError إذا:
        - النوع غير مسموح (ليس jpg/png/webp)
        - الحجم أكبر من 5 ميغابايت
        """
        # نتحقق من النوع أولاً
        if content_type not in ALLOWED_CONTENT_TYPES:
            allowed = ", ".join(ALLOWED_CONTENT_TYPES)
            raise InvalidFileError(
                f"File type '{content_type}' not allowed. Allowed types: {allowed}"
            )

        # ثم نتحقق من الحجم
        file_size = len(file_bytes)
        if file_size > MAX_AVATAR_SIZE_BYTES:
            size_mb = file_size / (1024 * 1024)
            raise InvalidFileError(
                f"File size {size_mb:.1f}MB exceeds maximum allowed size of 5MB"
            )

    def _build_avatar_key(self, user_id: uuid.UUID, content_type: str) -> str:
        """
        يبني مفتاح الصورة داخل الـ bucket.
        مثال: "avatars/550e8400-e29b-41d4-a716-446655440000.jpg"

        نستخدم user_id كاسم للملف حتى:
        - لا يكون في كل مستخدم أكثر من صورة واحدة (كل رفع يستبدل السابق)
        - الاسم ثابت ومتوقع — سهل في الـ delete لاحقاً
        """
        ext = CONTENT_TYPE_TO_EXT[content_type]
        return f"{AVATARS_FOLDER}/{user_id}.{ext}"

    def upload_avatar(
        self,
        user_id: uuid.UUID,
        file_bytes: bytes,
        content_type: str,
    ) -> str:
        """
        يرفع صورة المستخدم لـ R2.

        يرجع avatar_key = المسار داخل الـ bucket.
        يرفع InvalidFileError إذا الملف غير صالح.
        يرفع StorageError إذا فشل الرفع.
        """
        # خطوة 1: التحقق من الصورة قبل الرفع
        self._validate_avatar(file_bytes, content_type)

        # خطوة 2: بناء المفتاح
        avatar_key = self._build_avatar_key(user_id, content_type)

        try:
            # خطوة 3: الرفع لـ R2
            # put_object = رفع ملف — إذا الملف موجود يُستبدل تلقائياً
            self._get_client().put_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=avatar_key,           # المسار داخل الـ bucket
                Body=file_bytes,          # محتوى الملف
                ContentType=content_type, # MIME type — مهم للمتصفح عند العرض
            )
        except (ClientError, NoCredentialsError) as e:
            # ClientError = خطأ من R2 (مثل bucket غير موجود، صلاحيات ناقصة)
            # NoCredentialsError = مفاتيح AWS/R2 غير موجودة
            raise StorageError(f"Failed to upload avatar: {e}") from e

        return avatar_key

    def delete_avatar(self, avatar_key: str) -> None:
        """
        يحذف صورة المستخدم من R2.
        يُستدعى عند تحديث الصورة (نحذف القديمة) أو حذف الحساب.

        لا يرفع exception إذا الملف غير موجود — delete_object في S3/R2
        لا يرفع خطأ للملفات الغير موجودة.
        """
        try:
            self._get_client().delete_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=avatar_key,
            )
        except (ClientError, NoCredentialsError) as e:
            raise StorageError(f"Failed to delete avatar: {e}") from e

    def get_avatar_url(self, avatar_key: str) -> str:
        """
        يولّد الـ URL الكامل للصورة من المفتاح.

        R2_PUBLIC_URL = الـ domain العام للـ bucket
        مثال: "https://pub-xxx.r2.dev"

        النتيجة: "https://pub-xxx.r2.dev/avatars/user-id.jpg"
        """
        if not settings.R2_PUBLIC_URL:
            raise StorageError("R2_PUBLIC_URL not configured in .env")

        # نزيل أي trailing slash من الـ base URL ونضيف المفتاح
        base_url = settings.R2_PUBLIC_URL.rstrip("/")
        return f"{base_url}/{avatar_key}"


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

# instance واحد يُستخدم في كل التطبيق
r2_client = CloudflareR2Client()
