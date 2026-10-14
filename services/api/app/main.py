"""FastAPI 앱: 라우터 등록, 예외 핸들러."""

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from app.address.router import router as address_router
from app.admin.router import router as admin_router
from app.core.errors import register_error_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.location.corrections.router import router as corrections_router
from app.location.places.router import router as places_router

configure_logging()

GZIP_MINIMUM_BYTES = 1000

app = FastAPI(title="가게내비 API", version="0.1.0")
register_error_handlers(app)
# 큰 목록(층 이력·층 미상 기록)은 자르지 않고 압축한다 (docs/30 §1 "압축")
app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_BYTES)
app.include_router(health_router, prefix="/api/v1")
app.include_router(address_router, prefix="/api/v1")
app.include_router(places_router, prefix="/api/v1")
app.include_router(corrections_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/admin/v1")
