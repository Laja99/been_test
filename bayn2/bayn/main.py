"""
نقطة دخول التطبيق.

يُشغَّل بـ: uvicorn src.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from bayn.common.exceptions import AppException
from bayn.features.identity.router import router as identity_router

# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────

app = FastAPI(
    title="Beyn API",
    description="Identity & Authentication Service",
    version="1.0.0",
)


# ─────────────────────────────────────────────
# Exception Handler
# ─────────────────────────────────────────────

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    يحول كل AppException لـ JSON response بشكل موحد.
    الـ service ترمي exceptions، هذا الـ handler يحولها لـ HTTP.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


# ─────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────

app.include_router(identity_router)


# ─────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check() -> dict:
    """يتحقق أن الـ API يعمل — يُستخدم من Docker و load balancer."""
    return {"status": "ok"}
