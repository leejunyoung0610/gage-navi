"""FastAPI 앱: 라우터 등록, 예외 핸들러."""

from fastapi import FastAPI

from app.address.router import router as address_router
from app.core.errors import register_error_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="가게내비 API", version="0.1.0")
register_error_handlers(app)
app.include_router(health_router, prefix="/api/v1")
app.include_router(address_router, prefix="/api/v1")
