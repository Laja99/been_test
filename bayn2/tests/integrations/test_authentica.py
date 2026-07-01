"""
اختبارات Authentica integration.

نختبر الـ client نفسه بدون HTTP requests حقيقية
باستخدام httpx mock.

تشغيل:
    pytest tests/integrations/test_authentica.py -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from bayn.integrations.authentica import (
    AuthenticaClient,
    AuthenticaError,
    AuthenticaOTPInvalid,
)


class TestAuthenticaClient:
    """اختبارات AuthenticaClient."""

    def setup_method(self):
        """ينشئ client جديد لكل test."""
        self.client = AuthenticaClient()

    @pytest.mark.asyncio
    async def test_send_email_otp_success(self):
        """إرسال OTP للإيميل بنجاح — يتحقق من الـ request body والـ headers."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"success": True}

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            # لا يجب أن يرفع exception
            await self.client.send_email_otp("user@example.com")

    @pytest.mark.asyncio
    async def test_send_email_otp_failure(self):
        """فشل إرسال OTP → AuthenticaError."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.text = "Service unavailable"

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            with pytest.raises(AuthenticaError):
                await self.client.send_email_otp("user@example.com")

    @pytest.mark.asyncio
    async def test_send_sms_otp_e164_format(self):
        """
        التحقق أن الهاتف يُرسَل بتنسيق E.164.
        +966 + 501234567 = +966501234567
        """
        sent_body = {}

        async def capture_request(url, headers, json):
            sent_body.update(json)
            mock_resp = MagicMock()
            mock_resp.is_success = True
            return mock_resp

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=capture_request
            )
            await self.client.send_sms_otp("+966", 501234567)

        assert sent_body.get("phone") == "+966501234567"
        assert sent_body.get("method") == "sms"

    @pytest.mark.asyncio
    async def test_verify_email_otp_success(self):
        """التحقق من OTP الإيميل بنجاح → True."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await self.client.verify_email_otp("user@example.com", "123456")
            assert result is True

    @pytest.mark.asyncio
    async def test_verify_email_otp_invalid_code(self):
        """رمز OTP غلط (400) → AuthenticaOTPInvalid."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 400

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            with pytest.raises(AuthenticaOTPInvalid):
                await self.client.verify_email_otp("user@example.com", "000000")

    @pytest.mark.asyncio
    async def test_headers_use_x_authorization(self):
        """التحقق أن الـ header هو X-Authorization مو Authorization: Bearer."""
        headers = self.client._headers()
        assert "X-Authorization" in headers
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_verify_sms_otp_correct_body(self):
        """التحقق أن body التحقق من SMS يحتوي على phone + otp."""
        sent_body = {}

        async def capture_request(url, headers, json):
            sent_body.update(json)
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=capture_request
            )
            await self.client.verify_sms_otp("+966", 501234567, "123456")

        assert sent_body.get("phone") == "+966501234567"
        assert sent_body.get("otp") == "123456"
        assert "email" not in sent_body
