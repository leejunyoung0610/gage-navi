#!/usr/bin/env bash
# 운영 VM에서 배치 잡 하나를 실행한다 (docs/01 §5). 저장소 루트 어디서 불러도 된다.
#   deploy/job.sh correction_maintenance
#   deploy/job.sh ingest_licenses --mode full --type general_restaurant --file /repo/data/raw/…
# 원본 파일은 컨테이너 안에서 /repo/data/… 경로다(compose.prod.yml).
set -euo pipefail
cd "$(dirname "$0")/.."
name="$1"
shift
exec docker compose -f deploy/compose.prod.yml --env-file .env run --rm -T api python -m "jobs.${name}" "$@"
