"""
Exceptions مشتركة للتطبيق.

كل feature ترمي هذه الـ exceptions من الـ service layer،
والـ exception handler في main.py يحولها لـ HTTP responses.

لماذا custom exceptions بدل HTTPException مباشرة؟
- الـ service layer لا يجب أن يعرف شيئاً عن HTTP
- نقدر نستخدم نفس الـ service في سياقات غير HTTP مستقبلاً
- الأكواد أوضح وأسهل في الاختبار
"""


class AppException(Exception):
    """الكلاس الأساسي لكل أخطاء التطبيق المتوقعة."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ─────────────────────────────────────────────
# HTTP Standard Errors
# ─────────────────────────────────────────────

class NotFoundError(AppException):
    """المورد المطلوب غير موجود. → HTTP 404"""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404)


class ConflictError(AppException):
    """تعارض مع بيانات موجودة (مثل إيميل مكرر). → HTTP 409"""

    def __init__(self, message: str = "Resource already exists"):
        super().__init__(message, status_code=409)


class ValidationError(AppException):
    """البيانات صحيحة الشكل لكن غير صالحة منطقياً. → HTTP 400"""

    def __init__(self, message: str = "Invalid request data"):
        super().__init__(message, status_code=400)


class UnauthorizedError(AppException):
    """بيانات المصادقة مفقودة أو غير صحيحة. → HTTP 401"""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, status_code=401)


class ForbiddenError(AppException):
    """المستخدم موثق لكن ليس لديه صلاحية. → HTTP 403"""

    def __init__(self, message: str = "You do not have permission"):
        super().__init__(message, status_code=403)


# ─────────────────────────────────────────────
# Identity Specific Errors
# ─────────────────────────────────────────────

class UserAlreadyExistsError(ConflictError):
    """الإيميل أو الـ username مستخدم مسبقاً."""

    def __init__(self, message: str = "Email or username already in use"):
        super().__init__(message)


class InvalidCredentialsError(UnauthorizedError):
    """إيميل أو باسورد غلط عند تسجيل الدخول."""

    def __init__(self, message: str = "Invalid email or password"):
        super().__init__(message)


class InvalidTokenError(UnauthorizedError):
    """JWT مفقود أو منتهي أو توقيعه غلط."""

    def __init__(self, message: str = "Invalid or expired token"):
        super().__init__(message)
