#!/usr/bin/env bash
# DB 백업 (T-081, docs/01 §5): pg_dump -Fc → VM 밖 저장소, 7일 보관. cron이 매일 1회 실행한다.
# Gate 1 시점 범위는 DB다(storage/는 비어 있다 — 넓히는 일은 docs/50 §7 Gate 2).
#
# 환경 변수 (VM의 .env가 아니라 cron 줄이나 셸에서 준다. 비밀 값 아님)
#   BACKUP_DIR            VM 안의 임시 보관 폴더 (기본 /var/backups/gage-navi)
#   BACKUP_RCLONE_REMOTE  VM 밖 저장소 (rclone 원격 이름:경로). 비우면 올리지 않고 실패로 끝낸다
# 출력은 파일 이름·크기·보관 개수뿐이다. 접속 정보를 출력하지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP_DAYS=7
BACKUP_DIR="${BACKUP_DIR:-/var/backups/gage-navi}"
COMPOSE=(docker compose -f deploy/compose.prod.yml --env-file .env)

mkdir -p "$BACKUP_DIR"
stamp="$(TZ=Asia/Seoul date +%Y%m%d-%H%M)"
file="$BACKUP_DIR/gagenavi-$stamp.dump"

# 사용자·DB 이름은 db 컨테이너의 환경 변수로 읽는다(작은따옴표 — 이 셸에서 펼치지 않는다)
"${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$file.part"
# 목록을 읽을 수 있어야 쓸 수 있는 덤프다
"${COMPOSE[@]}" exec -T db pg_restore --list < "$file.part" > /dev/null
mv "$file.part" "$file"
echo "backup $(basename "$file") $(wc -c < "$file" | tr -d ' ') bytes"

find "$BACKUP_DIR" -name 'gagenavi-*.dump' -mtime +$((KEEP_DAYS - 1)) -delete
echo "local kept $(find "$BACKUP_DIR" -name 'gagenavi-*.dump' | wc -l | tr -d ' ')"

if [[ -z "${BACKUP_RCLONE_REMOTE:-}" ]]; then
  echo "BACKUP_RCLONE_REMOTE가 비어 있어 VM 밖으로 올리지 않았습니다" >&2
  exit 1
fi
rclone copy "$file" "$BACKUP_RCLONE_REMOTE"
rclone delete --min-age "${KEEP_DAYS}d" --include 'gagenavi-*.dump' "$BACKUP_RCLONE_REMOTE"
echo "remote kept $(rclone lsf --include 'gagenavi-*.dump' "$BACKUP_RCLONE_REMOTE" | wc -l | tr -d ' ')"
