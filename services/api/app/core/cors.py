"""CORS (docs/30 §1, T-032). 허용 출처는 `CORS_ALLOWED_ORIGINS`에만 있다.

값이 없으면 아무 출처도 허용하지 않는다(`*`로 채우지 않는다). 메서드는 브라우저가 지금 부르는
`GET`뿐이고 자격 증명(쿠키)은 허용하지 않는다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ALLOWED_METHODS = ["GET"]


def add_cors(app: FastAPI, origins: tuple[str, ...]) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=ALLOWED_METHODS,
        allow_credentials=False,
    )
