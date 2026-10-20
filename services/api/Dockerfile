FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/repo/services/api/.venv/bin:$PATH"

# 저장소와 같은 배치로 둔다. jobs는 `Path(__file__).parents[3]`을 저장소 루트로 보고
# `data/`(원본 파일)와 `reports/`를 찾는다 — `/app/jobs/…`에서는 그 단계가 없어 import에서 실패한다
WORKDIR /repo/services/api

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY jobs ./jobs

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
