"""환경 변수 설정. 비밀 값은 환경 변수로만 받는다 (docs/01 §6)."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str | None
    juso_confm_key: str | None = field(default=None, repr=False)  # repr에 키를 내지 않는다
    kakao_rest_api_key: str | None = field(default=None, repr=False)  # 좌표 → 주소 (T-032)
    web_revalidate_url: str | None = None  # 웹 on-demand 재생성 (docs/30 §3, T-023)
    revalidate_secret: str | None = field(default=None, repr=False)
    cors_allowed_origins: tuple[str, ...] = ()  # 비면 어느 출처도 허용하지 않는다 (docs/30 §1)
    ssr_secret: str | None = field(default=None, repr=False)  # 서버 렌더링 공유 한도 (ADR-031)


def parse_origins(raw: str | None) -> tuple[str, ...]:
    """`http://a, http://b/` → `("http://a", "http://b")`. 빈 항목은 버린다."""
    if raw is None:
        return ()
    return tuple(origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip())


def get_settings() -> Settings:
    return Settings(
        app_env=os.environ.get("APP_ENV", "local"),
        database_url=os.environ.get("DATABASE_URL") or None,
        juso_confm_key=os.environ.get("JUSO_CONFM_KEY") or None,
        kakao_rest_api_key=os.environ.get("KAKAO_REST_API_KEY") or None,
        web_revalidate_url=os.environ.get("WEB_REVALIDATE_URL") or None,
        revalidate_secret=os.environ.get("REVALIDATE_SECRET") or None,
        cors_allowed_origins=parse_origins(os.environ.get("CORS_ALLOWED_ORIGINS")),
        ssr_secret=os.environ.get("API_SSR_SECRET") or None,
    )
