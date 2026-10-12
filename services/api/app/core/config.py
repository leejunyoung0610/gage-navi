"""환경 변수 설정. 비밀 값은 환경 변수로만 받는다 (docs/01 §6)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str | None


def get_settings() -> Settings:
    return Settings(
        app_env=os.environ.get("APP_ENV", "local"),
        database_url=os.environ.get("DATABASE_URL") or None,
    )
