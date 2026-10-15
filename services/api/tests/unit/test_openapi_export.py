"""OpenAPI 내보내기 (T-031): 웹 타입 생성(`pnpm gen:api`)의 입력."""

import json

import pytest

from app.openapi_export import main


def test_출력은_공개_관리자_경로를_모두_담은_json(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    schema = json.loads(capsys.readouterr().out)
    assert schema["openapi"].startswith("3.")
    assert "/api/v1/places/{pnu}" in schema["paths"]
    assert "/admin/v1/corrections" in schema["paths"]
