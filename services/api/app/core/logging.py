"""로그 설정 (docs/01 §6).

- 접속 로그에 쿼리스트링(주소 검색어 `?q=` 등)을 남기지 않는다
- `app.*` 로그에는 그 요청의 ID(`request_id=…`)가 붙는다. 응답 `meta.request_id`·`X-Request-ID`와
  같은 값이라, 사용자가 알려 준 오류 화면의 ID로 로그를 찾을 수 있다(docs/30 §1)
"""

import logging

from app.core.request_id import log_request_id

ACCESS_LOGGER = "uvicorn.access"
APP_LOGGER = "app"
APP_FORMAT = "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"


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
    _configure_app_logger()


class RequestIdFilter(logging.Filter):
    """레코드에 지금 요청의 ID를 `request_id`로 붙인다 (요청 밖이면 `-`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = log_request_id()
        return True


def _configure_app_logger() -> None:
    app_logger = logging.getLogger(APP_LOGGER)
    if any(isinstance(f, RequestIdFilter) for h in app_logger.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(APP_FORMAT))
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
