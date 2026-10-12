"""import-linter 계약: 위반 코드를 넣으면 lint-imports가 실패한다 (T-001 수용 기준).

저장소 사본에 위반 파일을 하나 넣고 lint-imports를 실행한다.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"


def run_lint_imports(
    tmp_path: Path, violation: tuple[str, str] | None
) -> subprocess.CompletedProcess[str]:
    for name in ("app", "jobs"):
        shutil.copytree(
            API_ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copy(API_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    if violation is not None:
        path, source = violation
        (tmp_path / path).write_text(source, encoding="utf-8")
    return subprocess.run(
        [str(LINT_IMPORTS), "--no-cache"], cwd=tmp_path, capture_output=True, text=True
    )


def test_clean_tree_passes(tmp_path: Path) -> None:
    result = run_lint_imports(tmp_path, None)
    assert result.returncode == 0, result.stdout + result.stderr


VIOLATIONS = [
    ("app/location/_violation.py", "import app.rules.engine\n"),
    ("app/location/normalize/_violation.py", "from app.rules import dsl\n"),
    ("app/rules/_violation.py", "import app.location\n"),
    ("app/rules/engine/_violation.py", "from app.location import stats\n"),
    ("app/funding/_violation.py", "import anthropic\n"),
    ("app/rules/engine/_violation.py", "import anthropic\n"),
    ("app/main_violation.py", "from anthropic import Anthropic\n"),
    ("jobs/_violation.py", "import anthropic\n"),
    ("app/rules/engine/_violation.py", "import sqlalchemy\n"),
    ("app/rules/engine/_violation.py", "from fastapi import FastAPI\n"),
    ("app/rules/engine/_violation.py", "import httpx\n"),
]


@pytest.mark.parametrize(("path", "source"), VIOLATIONS)
def test_violation_fails(tmp_path: Path, path: str, source: str) -> None:
    result = run_lint_imports(tmp_path, (path, source))
    assert result.returncode != 0, result.stdout
    assert "BROKEN" in result.stdout


def test_extraction_may_import_anthropic(tmp_path: Path) -> None:
    result = run_lint_imports(tmp_path, ("app/rules/extraction/extractor.py", "import anthropic\n"))
    assert result.returncode == 0, result.stdout + result.stderr
