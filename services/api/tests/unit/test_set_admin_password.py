"""관리자 계정 명령 (docs/30 §3): 비밀번호를 출력하지 않는다. 짧거나 두 입력이 다르면 멈춘다."""

import pytest

from app.admin.auth import PasswordSet
from jobs import set_admin_password as job

PASSWORD = "가상-비밀번호-예시-1234"  # 가상 예시


def _run(
    monkeypatch: pytest.MonkeyPatch, inputs: list[str], result: PasswordSet | None = None
) -> tuple[int, list[tuple[str, str]]]:
    seen: list[tuple[str, str]] = []

    async def fake_run(username: str, password: str) -> PasswordSet:
        seen.append((username, password))
        assert result is not None
        return result

    monkeypatch.setattr(job, "run", fake_run)
    answers = iter(inputs)
    code = job.main(["admin"], prompt=lambda _: next(answers))
    return code, seen


def test_creates_without_printing_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, seen = _run(monkeypatch, [PASSWORD, PASSWORD], PasswordSet(True, 0))
    assert code == 0 and seen == [("admin", PASSWORD)]
    out = capsys.readouterr()
    assert "만들었어요" in out.out
    assert PASSWORD not in out.out + out.err


def test_change_reports_deleted_sessions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = _run(monkeypatch, [PASSWORD, PASSWORD], PasswordSet(False, 2))
    assert code == 0
    assert "세션 2개를 지웠어요" in capsys.readouterr().out


@pytest.mark.parametrize(
    "inputs", [["짧은비번", "짧은비번"], [PASSWORD, PASSWORD + "x"]], ids=["short", "mismatch"]
)
def test_rejects_short_or_mismatched(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], inputs: list[str]
) -> None:
    code, seen = _run(monkeypatch, inputs)
    assert code == 2 and seen == []
    out = capsys.readouterr()
    assert PASSWORD not in out.out + out.err
