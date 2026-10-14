"""정정 요청 입력 검증 (docs/30 §2): DB에 닿기 전에 422, 입력값을 되돌려 보내지 않는다."""

import pytest
from fastapi.testclient import TestClient

from app.core.ratelimit import correction_limiter
from app.main import app

PNU = "1121510700100470001"
CONTACT = "가상 연락처 010-0000-0000"  # 가상 예시
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_limit() -> None:
    correction_limiter.reset()


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"kind": "wrong_info"}, {"message": "missing"}),
        ({"kind": "wrong_info", "message": "   "}, {"message": "string_too_short"}),
        ({"kind": "wrong_info", "message": "가" * 1001}, {"message": "string_too_long"}),
        ({"kind": "bad", "message": CONTACT}, {"kind": "literal_error"}),
        ({"kind": "other", "message": CONTACT, "phone": CONTACT}, {"phone": "extra_forbidden"}),
        (
            {"kind": "other", "message": CONTACT, "record_id": 0},
            {"record_id": "greater_than_equal"},
        ),
        ({"kind": "other", "message": CONTACT, "floor": "지하1층"}, {"floor": "invalid_format"}),
    ],
)
def test_invalid_body_is_422_without_echo(body: dict[str, object], fields: dict[str, str]) -> None:
    response = client.post(f"/api/v1/places/{PNU}/corrections", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"fields": fields}
    assert "010-0000-0000" not in response.text


def test_invalid_pnu_is_422() -> None:
    response = client.post(
        "/api/v1/places/12345/corrections", json={"kind": "other", "message": "가상"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"fields": {"pnu": "invalid_format"}}
