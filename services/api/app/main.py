"""FastAPI 앱: 라우터 등록, 예외 핸들러, 메모리 주기 정리."""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from app.address.router import router as address_router
from app.address.router import search_cache
from app.admin.router import router as admin_router
from app.core.config import get_settings
from app.core.cors import add_cors
from app.core.errors import register_error_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.core.memory_sweep import sweep_periodically
from app.core.ratelimit import LIMITERS
from app.location.corrections.router import router as corrections_router
from app.location.places.router import router as places_router
from app.location.sitemap.router import router as sitemap_router
from app.location.stats.router import router as stats_router
from app.measure.router import router as measure_router

configure_logging()

GZIP_MINIMUM_BYTES = 1000
# 1분마다 만료 값을 지우는 메모리 저장소: 호출 제한의 IP, 주소 검색 캐시 (docs/60 §5)
SWEEP_TARGETS = (*LIMITERS, search_cache)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    sweeper = asyncio.create_task(sweep_periodically(SWEEP_TARGETS))
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper


app = FastAPI(title="가게내비 API", version="0.1.0", lifespan=lifespan)
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
app.include_router(sitemap_router, prefix="/api/v1")
app.include_router(measure_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/admin/v1")
