"""접속 로그에 쿼리스트링(검색어)을 남기지 않는다 (docs/01 §6)."""

import logging

from app.core.logging import ACCESS_LOGGER, StripQueryFilter, configure_logging


def access_record(path: str) -> logging.LogRecord:
    # uvicorn 접속 로그와 같은 형식·인자
    return logging.LogRecord(
        ACCESS_LOGGER, logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 200), None,
    )  # fmt: skip


def test_query_string_is_stripped() -> None:
    record = access_record("/api/v1/address/search?q=%EA%B0%80%EC%83%81%EB%A1%9C&page=1")
    assert StripQueryFilter().filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "GET /api/v1/address/search HTTP/1.1" 200'


def test_path_without_query_is_unchanged() -> None:
    record = access_record("/api/v1/health")
    StripQueryFilter().filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "GET /api/v1/health HTTP/1.1" 200'


def test_filter_is_installed_once_on_access_logger() -> None:
    configure_logging()
    configure_logging()
    filters = [
        f for f in logging.getLogger(ACCESS_LOGGER).filters if isinstance(f, StripQueryFilter)
    ]
    assert len(filters) == 1
