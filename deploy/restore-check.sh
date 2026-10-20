#!/usr/bin/env bash
# 백업에서 복원 확인 (T-081): 덤프를 별도 DB에 pg_restore하고 운영 DB와 행 수를 비교한 뒤 지운다.
#   deploy/restore-check.sh                         # BACKUP_DIR의 가장 최근 덤프
#   deploy/restore-check.sh /path/gagenavi-….dump   # VM 밖 저장소에서 내려받은 덤프
# 백업 직후에 실행한다(그 사이 정정 요청이 들어오면 그 표만 다를 수 있다).
# 출력은 표 이름과 행 수뿐이다. 행 내용(정정 요청 메시지, 관리자 이름 등)은 출력하지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-/var/backups/gage-navi}"
COMPOSE=(docker compose -f deploy/compose.prod.yml --env-file .env)
CHECK_DB=gagenavi_restore_check
# 다시 만들 수 없는 기록(정정 요청·숨김·측정 합계·관리자)과 적재 결과의 대표 표
TABLES=(correction_request record_suppression measure_daily_count admin_user
        search_match_result data_snapshot license_record floor_summary base_rate model_card)

file="${1:-$(ls -1t "$BACKUP_DIR"/gagenavi-*.dump | head -n 1)}"
echo "restore $(basename "$file")"

psql_in() {  # psql_in <db> <sql> — 사용자 이름은 컨테이너 환경 변수
  "${COMPOSE[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d $1 -At -c \"$2\""
}

psql_in postgres "DROP DATABASE IF EXISTS $CHECK_DB" > /dev/null
psql_in postgres "CREATE DATABASE $CHECK_DB" > /dev/null
"${COMPOSE[@]}" exec -T db sh -c "pg_restore -U \"\$POSTGRES_USER\" -d $CHECK_DB --no-owner --exit-on-error" < "$file"

status=0
printf '%-22s %12s %12s %s\n' table live restored same
for t in "${TABLES[@]}"; do
  live="$(psql_in '"$POSTGRES_DB"' "SELECT count(*) FROM $t")"
  restored="$(psql_in $CHECK_DB "SELECT count(*) FROM $t")"
  same=yes
  if [[ "$live" != "$restored" ]]; then same=NO; status=1; fi
  printf '%-22s %12s %12s %s\n' "$t" "$live" "$restored" "$same"
done
live_head="$(psql_in '"$POSTGRES_DB"' "SELECT version_num FROM alembic_version")"
restored_head="$(psql_in $CHECK_DB "SELECT version_num FROM alembic_version")"
echo "alembic live=$live_head restored=$restored_head"
[[ "$live_head" == "$restored_head" ]] || status=1

psql_in postgres "DROP DATABASE $CHECK_DB" > /dev/null
echo "result $([[ $status -eq 0 ]] && echo PASS || echo FAIL)"
exit $status
