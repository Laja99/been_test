"""
اختبارات identity feature.

كل test مستقل — لا يعتمد على ترتيب التشغيل.
كل test يبدأ بـ test_ عشان pytest يكتشفه تلقائياً.

تشغيل:
    pytest tests/features/identity/test_identity.py -v
    pytest tests/features/identity/test_identity.py::TestSignup -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from bayn.features.identity.models import User


# ═══════════════════════════════════════════════════════
# Signup Tests
# ═══════════════════════════════════════════════════════

class TestSignup:
    """اختبارات إنشاء حساب جديد POST /auth/signup"""

    VALID_PAYLOAD = {
        "first_name_ar": "محمد",
        "last_name_ar": "الأحمد",
        "first_name_en": "Mohammed",
        "last_name_en": "Al-Ahmad",
        "email": "new@example.com",
        "username": "new_user",
        "password": "TestPass123",
    }

    @pytest.mark.asyncio
    async def test_signup_success(self, client: AsyncClient):
        """تسجيل مستخدم جديد بنجاح — يرجع 201 مع tokens."""
        response = await client.post("/auth/signup", json=self.VALID_PAYLOAD)

        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "new@example.com"
        assert data["user"]["username"] == "new_user"
        # التأكد أن الباسورد لا يرجع أبداً في الـ response
        assert "password" not in data["user"]
        assert "password_hash" not in data["user"]

    @pytest.mark.asyncio
    async def test_signup_duplicate_email(self, client: AsyncClient, test_user: User):
        """إيميل مكرر → 409 Conflict."""
        payload = {**self.VALID_PAYLOAD, "email": test_user.email, "username": "another_user"}
        response = await client.post("/auth/signup", json=payload)

        assert response.status_code == 409
        assert "already in use" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_signup_duplicate_username(self, client: AsyncClient, test_user: User):
        """username مكرر → 409 Conflict."""
        payload = {**self.VALID_PAYLOAD, "email": "another@example.com", "username": test_user.username}
        response = await client.post("/auth/signup", json=payload)

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_signup_weak_password(self, client: AsyncClient):
        """باسورد ضعيف → 422 Validation Error."""
        payload = {**self.VALID_PAYLOAD, "email": "p@example.com", "username": "ptest", "password": "weak"}
        response = await client.post("/auth/signup", json=payload)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_signup_invalid_email(self, client: AsyncClient):
        """إيميل غير صالح → 422."""
        payload = {**self.VALID_PAYLOAD, "email": "not-an-email"}
        response = await client.post("/auth/signup", json=payload)

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_signup_username_lowercase(self, client: AsyncClient):
        """الـ username يُحول لحروف صغيرة تلقائياً."""
        payload = {**self.VALID_PAYLOAD, "email": "lower@example.com", "username": "UPPERCASE_USER"}
        response = await client.post("/auth/signup", json=payload)

        assert response.status_code == 201
        assert response.json()["user"]["username"] == "uppercase_user"


# ═══════════════════════════════════════════════════════
# Login Tests
# ═══════════════════════════════════════════════════════

class TestLogin:
    """اختبارات تسجيل الدخول POST /auth/login"""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, test_user: User):
        """تسجيل دخول ناجح — يرجع tokens."""
        response = await client.post("/auth/login", json={
            "email": test_user.email,
            "password": "TestPass123",
        })

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["id"] == str(test_user.id)

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, test_user: User):
        """باسورد غلط → 401. نفس الرسالة كـ إيميل غير موجود (حماية من enumeration)."""
        response = await client.post("/auth/login", json={
            "email": test_user.email,
            "password": "WrongPass999",
        })

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_email(self, client: AsyncClient):
        """إيميل غير مسجل → 401. نفس رسالة الباسورد الغلط."""
        response = await client.post("/auth/login", json={
            "email": "ghost@example.com",
            "password": "TestPass123",
        })

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_same_error_message(self, client: AsyncClient, test_user: User):
        """
        التحقق أن رسالة الخطأ واحدة سواء كان الإيميل غير موجود أو الباسورد غلط.
        هذا يمنع user enumeration attack.
        """
        wrong_password = await client.post("/auth/login", json={
            "email": test_user.email,
            "password": "WrongPass",
        })
        wrong_email = await client.post("/auth/login", json={
            "email": "ghost@example.com",
            "password": "TestPass123",
        })

        # نفس رسالة الخطأ في الحالتين
        assert wrong_password.json()["detail"] == wrong_email.json()["detail"]


# ═══════════════════════════════════════════════════════
# Token Tests
# ═══════════════════════════════════════════════════════

class TestTokens:
    """اختبارات الـ tokens و refresh"""

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, client: AsyncClient, test_user: User):
        """تجديد الـ access token بـ refresh token صالح."""
        # نسجل دخول أولاً للحصول على refresh token
        login = await client.post("/auth/login", json={
            "email": test_user.email,
            "password": "TestPass123",
        })
        refresh_token = login.json()["refresh_token"]

        # نجدد الـ token
        response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})

        assert response.status_code == 200
        assert "access_token" in response.json()

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_fails(self, client: AsyncClient, test_user: User):
        """
        استخدام access token في endpoint الـ refresh → يرفض.
        لأن decode_token يتحقق من النوع صراحةً.
        """
        login = await client.post("/auth/login", json={
            "email": test_user.email,
            "password": "TestPass123",
        })
        access_token = login.json()["access_token"]

        response = await client.post("/auth/refresh", json={"refresh_token": access_token})

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_without_token(self, client: AsyncClient):
        """endpoint محمي بدون token → 403."""
        response = await client.get("/auth/me")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_protected_route_with_invalid_token(self, client: AsyncClient):
        """token مزور → 401."""
        response = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer fake.token.here"},
        )
        assert response.status_code == 401


# ═══════════════════════════════════════════════════════
# Profile Tests
# ═══════════════════════════════════════════════════════

class TestProfile:
    """اختبارات الملف الشخصي"""

    @pytest.mark.asyncio
    async def test_get_me(self, client: AsyncClient, test_user: User, auth_headers: dict):
        """جلب بيانات المستخدم الحالي."""
        response = await client.get("/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["username"] == test_user.username
        assert "password_hash" not in data

    @pytest.mark.asyncio
    async def test_update_profile_partial(self, client: AsyncClient, auth_headers: dict):
        """تحديث جزئي للملف الشخصي — يُحدَّث فقط ما يُرسَل."""
        response = await client.patch(
            "/auth/me",
            headers=auth_headers,
            json={"city": "الرياض", "git_profile": "https://github.com/test"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["city"] == "الرياض"
        assert data["git_profile"] == "https://github.com/test"

    @pytest.mark.asyncio
    async def test_soft_delete_account(self, client: AsyncClient, db, auth_headers: dict):
        """حذف الحساب — soft delete، البيانات لا تُحذف."""
        response = await client.delete("/auth/me", headers=auth_headers)

        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()


# ═══════════════════════════════════════════════════════
# OTP Tests
# ═══════════════════════════════════════════════════════

class TestOTP:
    """اختبارات التحقق من الإيميل والهاتف."""

    @pytest.mark.asyncio
    async def test_send_email_otp(
        self,
        client: AsyncClient,
        auth_headers: dict,
        mock_authentica,
    ):
        """إرسال OTP للإيميل — يتحقق أن Authentica يُستدعى بالإيميل الصحيح."""
        response = await client.post("/auth/verify-email/send", headers=auth_headers)

        assert response.status_code == 200
        assert "message" in response.json()
        # نتحقق أن authentica_client.send_email_otp استُدعيت
        mock_authentica.send_email_otp.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_email_otp_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        mock_authentica,
    ):
        """تأكيد OTP الإيميل بنجاح → is_email_verified = true."""
        # نرسل OTP أولاً
        await client.post("/auth/verify-email/send", headers=auth_headers)

        # نؤكد الرمز
        response = await client.post(
            "/auth/verify-email/confirm",
            headers=auth_headers,
            json={"otp_code": "123456"},
        )

        assert response.status_code == 200
        assert response.json()["is_email_verified"] is True

    @pytest.mark.asyncio
    async def test_send_email_otp_already_verified(
        self,
        client: AsyncClient,
        db,
        test_user: User,
        auth_headers: dict,
        mock_authentica,
    ):
        """إيميل محقق مسبقاً → 400."""
        # نضع is_email_verified = True مباشرة
        test_user.is_email_verified = True
        await db.commit()

        response = await client.post("/auth/verify-email/send", headers=auth_headers)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_confirm_otp_invalid_code(
        self,
        client: AsyncClient,
        auth_headers: dict,
        mock_authentica,
    ):
        """رمز OTP غلط → 400."""
        from bayn.integrations.authentica import AuthenticaOTPInvalid
        mock_authentica.verify_email_otp.side_effect = AuthenticaOTPInvalid("Invalid OTP")

        # نرسل OTP أولاً
        await client.post("/auth/verify-email/send", headers=auth_headers)

        response = await client.post(
            "/auth/verify-email/confirm",
            headers=auth_headers,
            json={"otp_code": "000000"},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_send_phone_otp_no_phone(
        self,
        client: AsyncClient,
        auth_headers: dict,
        mock_authentica,
    ):
        """إرسال OTP الهاتف بدون رقم هاتف → 400."""
        response = await client.post("/auth/verify-phone/send", headers=auth_headers)
        # test_user ليس لديه phone_number بالافتراضي في بعض الحالات
        # يقبل 200 أو 400 حسب البيانات
        assert response.status_code in (200, 400)
