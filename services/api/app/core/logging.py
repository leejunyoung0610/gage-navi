"""로그 설정. 접속 로그에 쿼리스트링(주소 검색어 `?q=` 등)을 남기지 않는다 (docs/01 §6)."""

import logging

ACCESS_LOGGER = "uvicorn.access"


class StripQueryFilter(logging.Filter):
    """uvicorn 접속 로그의 경로에서 `?` 뒤를 지운다.

    uvicorn은 `(client_addr, method, full_path, http_version, status_code)`를 인자로 넘긴다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def configure_logging() -> None:
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, StripQueryFilter) for f in access.filters):
        access.addFilter(StripQueryFilter())
