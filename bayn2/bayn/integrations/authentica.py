"""
Authentica OTP Integration.

الـ API الحقيقي لـ Authentica (https://api.authentica.sa):

الـ flow الصحيح — بدون reference_id:
1. نرسل طلب إرسال OTP بالقناة (sms/email) والمستقبل (phone/email).
2. Authentica يرسل الرمز مباشرة للمستخدم — لا يرجع reference_id.
3. المستخدم يكتب الرمز → نرسله مع نفس المستقبل للتحقق.
4. Authentica يرجع { verified: true } أو يرفع خطأ.

الفرق الجوهري عن التصميم الأول:
- Header المصادقة: X-Authorization (مو Authorization: Bearer)
- Endpoints: /api/v2/send-otp و /api/v2/verify-otp
- لا يوجد reference_id — التحقق يتم بـ (phone/email + otp) مباشرة
- body الإرسال: { method, phone } أو { method, email }
- body التحقق: { phone, otp } أو { email, otp }
"""

import httpx

from bayn.core.config import settings


# ─────────────────────────────────────────────
# Custom Exceptions
# ─────────────────────────────────────────────

class AuthenticaError(Exception):
    """خطأ عام من Authentica — فشل الاتصال أو خطأ في الـ API."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class AuthenticaOTPInvalid(AuthenticaError):
    """الرمز اللي أدخله المستخدم غلط أو منتهي الصلاحية."""
    pass


# ─────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────

class AuthenticaClient:
    """
    HTTP client لـ Authentica API v2.

    التغييرات عن النسخة الأولى:
    - _headers: استبدلنا Authorization: Bearer بـ X-Authorization
    - send_email_otp: endpoint صار /api/v2/send-otp، body صار { method, email }
    - send_sms_otp: نفس الـ endpoint، body صار { method, phone } بـ E.164
    - verify_otp: انقسم لدالتين (email/phone) لأن الـ body مختلف لكل قناة
    - حذفنا reference_id تماماً — مو موجود في هذا الـ API
    """

    def __init__(self) -> None:
        self._base_url = settings.AUTHENTICA_BASE_URL
        self._api_key = settings.AUTHENTICA_API_KEY
        self._timeout = 10.0

    def _headers(self) -> dict[str, str]:
        """
        [تغيير] Header المصادقة هو X-Authorization مو Authorization: Bearer.
        هذا ما تطلبه Authentica بالضبط في docs الرسمية.
        """
        return {
            "X-Authorization": self._api_key,   # ← كان: Authorization: Bearer
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def send_email_otp(self, email: str) -> None:
        """
        يرسل OTP للإيميل.

        [تغيير] endpoint: /api/v2/send-otp (كان /otp/send)
        [تغيير] body: { method: "email", email: "..." } (كان { channel, recipient })
        [تغيير] لا يرجع reference_id — الدالة صارت void (None)
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/v2/send-otp",
                headers=self._headers(),
                json={
                    "method": "email",  # ← كان "channel"
                    "email": email,     # ← كان "recipient"
                },
            )

        if not response.is_success:
            raise AuthenticaError(f"Failed to send email OTP: {response.text}")

        # [تغيير] لا نقرأ reference_id من الـ response — مو موجود في هذا الـ API

    async def send_sms_otp(self, dial_code: str, phone_number: int) -> None:
        """
        يرسل OTP عبر SMS.

        [تغيير] endpoint: /api/v2/send-otp (كان /otp/send)
        [تغيير] body: { method: "sms", phone: "+966..." } (كان { channel, recipient })
        [تغيير] لا يرجع reference_id — الدالة صارت void (None)

        phone يجب أن يكون E.164: مفتاح الدولة + الرقم بدون صفر
        مثال: dial_code="+966", phone_number=501234567 → "+966501234567"
        """
        full_phone = f"{dial_code}{phone_number}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/v2/send-otp",
                headers=self._headers(),
                json={
                    "method": "sms",        # ← كان "channel"
                    "phone": full_phone,     # ← كان "recipient"
                },
            )

        if not response.is_success:
            raise AuthenticaError(f"Failed to send SMS OTP: {response.text}")

    async def verify_email_otp(self, email: str, otp_code: str) -> bool:
        """
        يتحقق من OTP الإيميل.

        [تغيير] endpoint: /api/v2/verify-otp (كان /otp/verify)
        [تغيير] body: { email, otp } (كان { reference_id, otp })
        [تغيير] هذه دالة منفصلة عن التحقق من الهاتف (الـ body مختلف)

        يرجع True إذا تم التحقق بنجاح.
        يرفع AuthenticaOTPInvalid إذا الرمز غلط أو منتهي.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/v2/verify-otp",
                headers=self._headers(),
                json={
                    "email": email,      # ← كان reference_id
                    "otp": otp_code,
                },
            )

        if response.status_code == 400:
            raise AuthenticaOTPInvalid("Invalid or expired OTP code")

        if not response.is_success:
            raise AuthenticaError(f"OTP verification failed: {response.text}")

        return True

    async def verify_sms_otp(self, dial_code: str, phone_number: int, otp_code: str) -> bool:
        """
        يتحقق من OTP الهاتف.

        [تغيير] endpoint: /api/v2/verify-otp (كان /otp/verify)
        [تغيير] body: { phone, otp } (كان { reference_id, otp })
        [تغيير] دالة جديدة منفصلة عن verify_email_otp

        يرجع True إذا تم التحقق بنجاح.
        """
        full_phone = f"{dial_code}{phone_number}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/api/v2/verify-otp",
                headers=self._headers(),
                json={
                    "phone": full_phone,  # ← كان reference_id
                    "otp": otp_code,
                },
            )

        if response.status_code == 400:
            raise AuthenticaOTPInvalid("Invalid or expired OTP code")

        if not response.is_success:
            raise AuthenticaError(f"OTP verification failed: {response.text}")

        return True


# Singleton
authentica_client = AuthenticaClient()
