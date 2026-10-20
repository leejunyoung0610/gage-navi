"""운영 배포 설정 (T-081, docs/01 §5, docs/60 §5). 파일을 글자로 읽어 검사한다(외부 도구 없음)."""

import re
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DEPLOY = REPO_ROOT / "deploy"
API_DOCKERFILE = REPO_ROOT / "services" / "api" / "Dockerfile"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _service_block(compose: str, name: str) -> str:
    """`services:` 아래 두 칸 들여쓴 서비스 하나의 본문."""
    match = re.search(rf"^  {name}:\n((?:    .*\n|\n)*)", compose, re.MULTILINE)
    assert match, f"서비스 {name} 없음"
    return "\n".join(line.split("#", 1)[0] for line in match.group(1).splitlines())


def _workdir() -> PurePosixPath:
    workdirs = re.findall(r"^WORKDIR\s+(\S+)", _read(API_DOCKERFILE), re.MULTILINE)
    assert len(workdirs) == 1
    return PurePosixPath(workdirs[0])


def test_api_image_keeps_repo_layout_for_jobs() -> None:
    # jobs는 `Path(__file__).parents[3]`을 저장소 루트로 본다(reports/, data/derived/)
    job_file = _workdir() / "jobs" / "measure_search_match.py"
    assert len(job_file.parents) > 3
    assert job_file.parents[3] / "services" / "api" == _workdir()


@pytest.mark.parametrize("compose", ["docker-compose.yml", "deploy/compose.prod.yml"])
def test_compose_mounts_data_at_repo_root_of_image(compose: str) -> None:
    root = _workdir().parents[1]
    text = _read(REPO_ROOT / compose)
    assert re.search(rf"\./data:{root}/data:ro", text)
    assert f"STORAGE_DIR: {root}/storage" in text


def test_prod_compose_publishes_only_caddy() -> None:
    compose = _read(DEPLOY / "compose.prod.yml")
    publishes = re.compile(r"^\s+ports:", re.MULTILINE)
    assert not publishes.search(_service_block(compose, "db"))
    assert not publishes.search(_service_block(compose, "api"))
    assert publishes.search(_service_block(compose, "caddy"))


def test_prod_api_reads_client_address_from_caddy() -> None:
    # 호출 제한(docs/30 §1)이 Caddy 주소 하나로 묶이지 않게 한다
    api = _service_block(_read(DEPLOY / "compose.prod.yml"), "api")
    assert "--proxy-headers" in api
    assert "--forwarded-allow-ips" in api
    assert "APP_ENV: prod" in api


def test_caddy_keeps_no_access_log_and_drops_error_log() -> None:
    # 사이트 블록에 `log`가 없으면 접속 로그가 없다. 오류 로그에는 remote_ip가 들어 있다(docs/60 §5)
    lines = [line.split("#", 1)[0].strip() for line in _read(DEPLOY / "Caddyfile").splitlines()]
    lines = [line for line in lines if line]
    assert lines.count("log default {") == 1
    assert "exclude http.log.error" in lines
    assert [line for line in lines if re.match(r"log\b", line)] == ["log default {"]


@pytest.mark.parametrize("script", ["backup.sh", "restore-check.sh", "job.sh"])
def test_scripts_do_not_echo_commands(script: str) -> None:
    # `set -x`는 명령을 펼쳐 출력한다(비밀 값이 찍힐 수 있다)
    text = _read(DEPLOY / script)
    assert "set -euo pipefail" in text
    assert not re.search(r"set -[a-z]*x|bash -x", text)


def test_backup_uses_custom_format_and_keeps_seven_days() -> None:
    text = _read(DEPLOY / "backup.sh")
    assert "pg_dump" in text and "-Fc" in text
    assert "KEEP_DAYS=7" in text  # docs/01 §5


def test_readme_avoids_commands_that_print_secrets() -> None:
    readme = _read(DEPLOY / "README.md")
    code = "\n".join(re.findall(r"```\n(.*?)```", readme, re.DOTALL))
    for command in ("cat .env", "docker compose config", "dc config", "docker inspect", "printenv"):
        assert command not in code
    assert not re.search(r"^\s*env\s*$", code, re.MULTILINE)
