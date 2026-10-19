"""FastAPI 앱: 라우터 등록, 예외 핸들러."""

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from app.address.router import router as address_router
from app.admin.router import router as admin_router
from app.core.config import get_settings
from app.core.cors import add_cors
from app.core.errors import register_error_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.location.corrections.router import router as corrections_router
from app.location.places.router import router as places_router
from app.location.stats.router import router as stats_router

configure_logging()

GZIP_MINIMUM_BYTES = 1000

app = FastAPI(title="가게내비 API", version="0.1.0")
register_error_handlers(app)
# 큰 목록(층 이력·층 미상 기록)은 자르지 않고 압축한다 (docs/30 §1 "압축")
app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_BYTES)
# 웹이 브라우저에서 공개 API를 부른다. 허용 출처는 환경 변수에만 (docs/30 §1)
add_cors(app, get_settings().cors_allowed_origins)
app.include_router(health_router, prefix="/api/v1")
app.include_router(address_router, prefix="/api/v1")
app.include_router(places_router, prefix="/api/v1")
app.include_router(corrections_router, prefix="/api/v1")
app.include_router(stats_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/admin/v1")
