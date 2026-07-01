"""
Identity Dependencies — دوال الـ Depends() في FastAPI.

هذه الدوال تعمل تلقائياً قبل تنفيذ أي route تستخدمها.
إما أن ترجع قيمة يستخدمها الـ route، أو ترفع exception يوقف الـ request.

طريقة الاستخدام في الـ router:
    @router.get("/me")
    async def get_me(user: User = Depends(get_current_active_user)):
        ...
"""

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from bayn.common.exceptions import ForbiddenError, InvalidTokenError
from bayn.core.database import get_db
from bayn.core.security import decode_token
from bayn.features.identity.models import User, UserRole
from bayn.features.identity.service import get_user_by_id

# HTTPBearer يقرأ الـ "Authorization: Bearer <token>" header تلقائياً.
# auto_error=True (الافتراضي) = إذا لم يكن الـ header موجوداً، FastAPI يرجع 401
# قبل أن يصل الـ request لهذا الكود.
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    يحدد المستخدم الحالي من الـ access token.

    الـ flow:
    1. HTTPBearer يستخرج الـ token من الـ Authorization header.
    2. decode_token يتحقق من التوقيع وانتهاء الصلاحية وأن النوع "access".
       (refresh token يُرفض هنا حتى لو هو JWT صالح تقنياً)
    3. أي خطأ في الـ decode → InvalidTokenError → 401 واضح بدون تسريب رسائل PyJWT.
    4. get_user_by_id يجلب المستخدم — يرفع NotFoundError إذا الحساب محذوف.
    """
    token = credentials.credentials

    try:
        # expected_type="access" = يرفض refresh tokens صراحةً
        user_id = decode_token(token, expected_type="access")
    except jwt.PyJWTError:
        # نحول أي خطأ من PyJWT لـ exception خاص بنا
        # حتى لا تصل رسائل PyJWT الداخلية للـ client
        raise InvalidTokenError()

    return await get_user_by_id(db, user_id)


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """
    مثل get_current_user لكن يرفض الحسابات الموقوفة.

    مفصول عن get_current_user عمداً:
    بعض الـ endpoints تحتاج تعرف من هو المستخدم بدون اشتراط أن يكون نشطاً
    (مثل endpoint "إعادة تفعيل الحساب" مستقبلاً).
    معظم الـ endpoints تستخدم هذا الـ dependency.
    """
    if not user.is_active:
        raise ForbiddenError("This account has been deactivated")
    return user


async def require_admin(
    user: User = Depends(get_current_active_user),
) -> User:
    """
    يُستخدم فقط على الـ endpoints الإدارية.

    دور ADMIN لا يُعطى من الـ API — يُضبط مباشرة في قاعدة البيانات.
    ما في endpoint يرفع المستخدم لـ ADMIN من داخل التطبيق.

    طريقة الاستخدام:
        @router.delete("/users/{user_id}")
        async def delete_user(admin: User = Depends(require_admin)):
            ...
    """
    if user.role != UserRole.ADMIN:
        raise ForbiddenError("Admin access required")
    return user
