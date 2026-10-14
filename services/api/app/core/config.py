"""환경 변수 설정. 비밀 값은 환경 변수로만 받는다 (docs/01 §6)."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str | None
    juso_confm_key: str | None = field(default=None, repr=False)  # repr에 키를 내지 않는다
    web_revalidate_url: str | None = None  # 웹 on-demand 재생성 (docs/30 §3, T-023)
    revalidate_secret: str | None = field(default=None, repr=False)


def get_settings() -> Settings:
    return Settings(
        app_env=os.environ.get("APP_ENV", "local"),
        database_url=os.environ.get("DATABASE_URL") or None,
        juso_confm_key=os.environ.get("JUSO_CONFM_KEY") or None,
        web_revalidate_url=os.environ.get("WEB_REVALIDATE_URL") or None,
        revalidate_secret=os.environ.get("REVALIDATE_SECRET") or None,
    )
