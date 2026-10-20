# 운영 배포 (T-081)

웹은 Vercel, API·DB는 VM 하나(Docker Compose + Caddy HTTPS)다(docs/01 §5). 이 문서는 **사용자가 VM에서 직접 실행하는 순서**다. 단계마다 "확인할 출력"과 같은지 보고, 출력을 붙여 준다.

- 명령은 모두 VM의 저장소 루트(아래 예시 `/srv/gage-navi`)에서 실행한다
- **비밀 값이 출력에 찍히는 명령은 쓰지 않는다.** `cat .env`, `env`, `docker compose config`(`.env` 값을 펼쳐 출력한다), `docker inspect`(환경 변수가 보인다)는 실행하지 않는다
- `<API 도메인>`·`<웹 도메인>`·`<사용자명>`처럼 꺾쇠로 쓴 곳은 사용자가 정한 값으로 바꾼다. 도메인은 아직 정하지 않았다(T-081 🧑)
- 기준 수치(행 수·시간)는 로컬에서 같은 원본 파일·같은 운영 compose로 새 DB에 적재해 잰 값이다(2026-10-21, macOS Docker). VM에서는 시간이 다를 수 있지만 **행 수·해시·판정은 같아야 한다**

줄여 쓰기 — 아래 명령의 `dc`는 이것이다(각 셸에서 한 번):

```
cd /srv/gage-navi
dc() { docker compose -f deploy/compose.prod.yml --env-file .env "$@"; }
```

## 0. 미리 정할 것 (🧑)

| 항목 | 정할 것 | 참고 |
|---|---|---|
| VM | **Lightsail 2GB로 시작**(2026-10-21 결정) | 정규화 잡이 로컬에서 최대 2,122MiB(+db 488MiB)를 써서 2GB 메모리를 넘는다 → 1단계 스왑 4GB. 적재 중 OOM이면 5단계 끝의 절차로 4GB로 옮긴다 |
| 백업 저장소 | VM 밖 저장소 하나(rclone이 붙는 곳) | 덤프 1개 크기 × 7일. 크기는 12단계 표 |
| 도메인 | API 도메인, 웹 도메인 | 웹 `SITE_URL`, API `CORS_ALLOWED_ORIGINS`·`WEB_REVALIDATE_URL`에 들어간다 |

## 1. VM 기본

```
timedatectl | grep 'Time zone'
docker compose version
```

확인할 출력
- `Time zone: Asia/Seoul` — 아니면 `sudo timedatectl set-timezone Asia/Seoul` (cron 시각이 docs/03 §5 기준이다)
- Docker Compose v2 버전 한 줄

### 스왑 4GB

2GB VM에서 정규화 잡(로컬 최대 2,122MiB)이 메모리를 넘기므로 적재 전에 스왑을 만든다.

```
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -m
swapon --show
```

확인할 출력: `free -m`의 `Swap:` 줄 `total`이 약 `4095`, `swapon --show`에 `/swapfile` `4G` 한 줄. 재부팅 뒤에도 남는지는 `/etc/fstab` 줄로 보장한다.

방화벽은 22(SSH)·80·443(TCP)·443(UDP)만 연다. DB(5432)와 API(8000)는 compose에서 포트를 열지 않는다.

## 2. 저장소와 `.env`

```
sudo mkdir -p /srv/gage-navi && sudo chown "$USER" /srv/gage-navi
git clone https://github.com/leejunyoung0610/gage-navi.git /srv/gage-navi
cd /srv/gage-navi && git log -1 --format='%h %s'
cp .env.example .env && chmod 600 .env
```

`.env`를 편집기로 열어 아래 값을 넣는다(값을 화면에 출력하지 않는다).

| 이름 | 운영 값 |
|---|---|
| `POSTGRES_PASSWORD` | 새로 만든 긴 무작위 값 (`change-me` 금지) |
| `API_DOMAIN` | `<API 도메인>` (Caddy가 이 이름으로 인증서를 받는다) |
| `CORS_ALLOWED_ORIGINS` | `https://<웹 도메인>` 하나. `localhost`·`*`를 넣지 않는다(docs/30 §1) |
| `WEB_REVALIDATE_URL` | `https://<웹 도메인>/api/revalidate` |
| `REVALIDATE_SECRET` | 새 무작위 값. Vercel에도 같은 값 |
| `JUSO_CONFM_KEY` | 도로명주소 승인키 (Gate 1 전에 운영 키로 — docs/50 §7) |
| `KAKAO_REST_API_KEY` | 카카오 REST 키 |
| `TZ` | `Asia/Seoul` |

`DATABASE_URL`·`APP_ENV`·`STORAGE_DIR`은 `deploy/compose.prod.yml`이 덮어쓰므로 `.env` 값은 쓰이지 않는다. `ANTHROPIC_API_KEY`·`DATA_GO_KR_SERVICE_KEY`는 Gate 1에 쓰지 않으므로 비워 둔다.

넣었는지만 확인(이름과 set/EMPTY만 나온다):

```
for k in POSTGRES_PASSWORD API_DOMAIN CORS_ALLOWED_ORIGINS WEB_REVALIDATE_URL REVALIDATE_SECRET JUSO_CONFM_KEY KAKAO_REST_API_KEY; do
  grep -qE "^$k=[^[:space:]#]" .env && echo "$k set" || echo "$k EMPTY"; done
grep -cE '^(POSTGRES_PASSWORD|REVALIDATE_SECRET)=change-me' .env
grep -E '^CORS_ALLOWED_ORIGINS=' .env | grep -cE 'localhost|\*'
```

확인할 출력: 일곱 줄 모두 `set`, 그다음 두 줄은 `0`과 `0`.

## 3. 원본 데이터 옮기기 (로컬 → VM)

로컬 DB 덤프는 쓰지 않는다. 원본 파일과 검색 일치율 건별 결과만 옮기고 VM에서 다시 적재한다(2026-10-21 결정). **로컬 터미널**에서:

```
cd ~/Desktop/gage-navi
ssh <VM> 'mkdir -p /srv/gage-navi/data/raw /srv/gage-navi/data/derived'
rsync -av data/raw/2026-10-08 data/raw/2026-10-12 <VM>:/srv/gage-navi/data/raw/
rsync -av data/derived/search_match <VM>:/srv/gage-navi/data/derived/
```

VM에서 해시 확인:

```
cd /srv/gage-navi/data
sha256sum raw/2026-10-12/'국토교통부_전국 법정동_20260630.csv' raw/2026-10-08/식품_일반음식점_서울특별시.csv \
  raw/2026-10-12/식품_휴게음식점_서울특별시.csv raw/2026-10-12/식품_제과점영업_서울특별시.csv \
  derived/search_match/seed_20261013.jsonl | cut -c1-16
```

확인할 출력 (앞 16자리, 위 순서)

```
e5657d4b53a16f72  (법정동)
3f3153d022e96244  (일반음식점)
9092429d77181800  (휴게음식점)
ad4c1d8dc31a8e73  (제과점)
ac4e98de33a6d62d  (검색 일치율 건별 결과)
```

## 4. 이미지 빌드, DB 시작

```
dc build api
dc pull db caddy
dc up -d --wait db
dc ps --format '{{.Service}} {{.Status}}'
```

확인할 출력: `db Up … (healthy)` 한 줄.

## 5. 운영 DB 적재 (docs/03 §5 순서)

한 단계가 끝나고 확인할 출력이 맞을 때 다음으로 간다. 실패하면 멈추고 출력을 붙인다. 원본 파일은 컨테이너 안에서 `/repo/data/…` 경로다.

**메모리 감시** — 적재하는 동안 SSH 창을 하나 더 열어 둔다:

```
free -m -s 5
```

5초마다 메모리·스왑이 찍힌다. 정규화·기준율 단계에서 `Swap: used`가 올라가는 것은 정상이다(2GB VM). 단계마다 끝나면 원래 창에서:

```
echo "exit=$?"
sudo dmesg -T | grep -iE 'out of memory|oom-kill|killed process' | tail -n 5
```

확인할 출력: `exit=0`, 그리고 `dmesg` 줄 없음. `exit=137`이거나 `dmesg`에 `Out of memory` / `Killed process … (python)` 줄이 있으면 OOM이다 — 멈추고 두 출력과 `free -m` 마지막 몇 줄을 붙인다.

```
dc run --rm -T api alembic upgrade head
dc run --rm -T api alembic current
deploy/job.sh ingest_legal_dong --file '/repo/data/raw/2026-10-12/국토교통부_전국 법정동_20260630.csv'
deploy/job.sh ingest_licenses --mode full --type general_restaurant --file /repo/data/raw/2026-10-08/식품_일반음식점_서울특별시.csv
deploy/job.sh ingest_licenses --mode full --type rest_restaurant --file /repo/data/raw/2026-10-12/식품_휴게음식점_서울특별시.csv
deploy/job.sh ingest_licenses --mode full --type bakery --file /repo/data/raw/2026-10-12/식품_제과점영업_서울특별시.csv
deploy/job.sh normalize_licenses
deploy/job.sh flag_stale_suspects
deploy/job.sh build_history
deploy/job.sh compute_base_rates
deploy/job.sh render_search_match --measured-on 2026-10-14 --criteria-commit "reports/search_match.md 참고" --calls 2074 --save --out /tmp/search_match.md
git status --short reports/
```

확인할 출력 (로컬 기준, 2026-10-21). 시간은 잡 시작부터 컨테이너 종료까지, 메모리는 1초마다 잰 `docker stats`의 최댓값이다

| 단계 | 확인할 출력 | 로컬 시간 | 최대 메모리 (잡 / db) |
|---|---|---|---|
| `alembic current` | `0009_measure (head)` | 2초 | — / 47MiB |
| 법정동 | `"file_rows": 20561, "table_rows": 20561, "seoul_rows": 493` | 9초 | 69MiB / 57MiB |
| 일반음식점 | `"snapshot_id": 1`, `"row_count": 539589`, `"non_seoul_address_rows": 14`, `"skipped": false` | 14초 | 90MiB / 296MiB |
| 휴게음식점 | `"snapshot_id": 2`, `"row_count": 147631`, `"non_seoul_address_rows": 9` | 4초 | 53MiB / 256MiB |
| 제과점 | `"snapshot_id": 3`, `"row_count": 16921`, `"non_seoul_address_rows": 2` | 2초 | — / 246MiB |
| 정규화 | `"applied": true, "records": 704116`, 세 스냅샷 모두 `"status": "validated", "failed": []` (DV1~DV10 통과) | 43초 | **2,122MiB** / 488MiB |
| 미갱신 표시 | `"candidates": 132191, "same_ho": 1850, "same_area": 8757` | 7초 | 779MiB / 281MiB |
| 층 이력 | `"as_of": "2026-10-07", "records": 703368, "parcels": 157898, "floors": 148604` | 13초 | 704MiB / 336MiB |
| 기준율 | `"holds": true, "saved": true, "base_rate_rows": 390, "floor_scales_held": ["single", "small"]`. 앞에 `층 규모 판정이 깨졌습니다: 대형(10+) …` 한 줄이 나오는 것은 정상(T-019b, 종료 코드 0) | 31초 | 1,335MiB / 346MiB |
| 검색 일치율 | `리포트 search_match.md (2000건)`, `search_match_result 저장 (seed 20261013)` | 3초 | 294MiB / 284MiB |
| `git status --short reports/` | ` M reports/stale_suspect.md` 한 줄 | | |

`—`는 잡이 1초 안에 끝나 재지 못한 값이다. 정규화가 잡 컨테이너 하나로 2GiB 넘게 쓰므로 VM 메모리는 그 시점의 db·api·caddy를 더해 여유를 둔다.

리포트 확인: `git diff -U0 reports/ | grep -E '^[-+][^-+]'`가 `측정일` 두 줄(`-` 커밋된 날짜, `+` 오늘)뿐이어야 한다 — 같은 원본으로 같은 결과가 나왔다는 뜻이다. 다른 줄이 있으면 붙인다. 확인한 뒤 `git checkout reports/`로 되돌린다.

**OOM이면 4GB로 옮기기**: Lightsail 콘솔에서 인스턴스 스냅샷을 만들고 → 그 스냅샷으로 4GB 플랜 새 인스턴스를 만든 뒤 → 고정 IP를 옛 인스턴스에서 떼어 새 인스턴스에 붙이고(DNS는 그대로) → 새 인스턴스에서 `free -m`·`dc ps`를 확인한 다음 옛 인스턴스를 지운다. 적재는 실패한 단계부터 다시 한다(잡은 다시 실행해도 결과가 같다).

`render_search_match`는 `--commit`을 주지 않으므로 git을 부르지 않는다. 리포트는 컨테이너 안 `/tmp`에 쓰고 버린다(커밋된 `reports/search_match.md`를 덮지 않는다). 저장되는 값은 건별 결과와 DB에서 다시 뽑은 표본으로만 계산한다 — 표본이 다르면 저장하지 않고 끝난다.

## 6. API·Caddy 시작

DNS에서 `<API 도메인>`의 A 레코드가 VM을 가리킨 뒤에 한다(Caddy가 인증서를 받는다).

```
dc up -d api caddy
dc ps --format '{{.Service}} {{.Status}}'
curl -s https://<API 도메인>/api/v1/health
```

확인할 출력
- `api Up`, `caddy Up`, `db Up (healthy)`
- `{"status":"ok","db":"ok","location_snapshot":"…","approved_rules":null}` — `location_snapshot`이 `null`이 아니다

## 7. 접속 기록에 IP가 없는지 (docs/60 §5)

Caddy 사이트 블록에는 `log` 지시어가 없다(접속 로그를 남기지 않는다). 오류 로그(`http.log.error`)에는 요청의 `remote_ip`·`client_ip`가 들어가므로 `deploy/Caddyfile`의 전역 설정에서 뺐다. 로컬 확인(2026-10-21, caddy 2.10.2, upstream이 없어 502가 나는 상태): 뺐을 때 `remote_ip`·`client_ip` 0줄, 빼지 않았을 때 1줄(`http.log.error`).

VM에서 정상 요청·404·502를 한 번씩 일으킨 뒤 로그를 센다. 502를 만들려고 API를 몇 초 멈추므로 공개 전에 한다.

```
curl -s -o /dev/null -w '%{http_code}\n' https://<API 도메인>/api/v1/health
curl -s -o /dev/null -w '%{http_code}\n' https://<API 도메인>/no-such-path
dc stop api && curl -s -o /dev/null -w '%{http_code}\n' https://<API 도메인>/api/v1/health; dc start api
dc logs caddy | grep -cE 'remote_ip|client_ip'
dc logs api | grep -vF '0.0.0.0' | grep -cE '([0-9]{1,3}\.){3}[0-9]{1,3}'
```

확인할 출력: `200`, `404`, `502`, 그다음 `0`, `0`(API 로그는 uvicorn 시작 줄의 `0.0.0.0`을 빼고 센다). 로컬 리허설(2026-10-21, `API_DOMAIN=localhost`)에서 같은 명령의 결과가 이와 같았다. 0이 아니면 그 줄을 지우지 말고(IP가 있으니 붙이지 말고) 줄 수와 `logger` 이름만 알려 준다:

```
dc logs caddy | grep -E 'remote_ip|client_ip' | grep -oE '"logger":"[^"]+"' | sort | uniq -c
```

결과를 docs/60 §5 "Caddy" 항목에 적는다.

### X-Forwarded-For 위조가 호출 제한을 비켜 가지 않는지

API는 `--proxy-headers --forwarded-allow-ips *`로 Caddy가 넘긴 `X-Forwarded-For`를 클라이언트 주소로 쓴다(호출 제한, docs/30 §1). 모든 주소를 믿어도 되는 근거는 두 가지다: API 포트를 열지 않아 밖에서는 Caddy를 거쳐야만 API에 닿고, Caddy는 믿는 프록시(`trusted_proxies`)가 설정되지 않으면 클라이언트가 보낸 `X-Forwarded-For`를 버리고 접속한 주소로 새로 쓴다.

판별 방법: API가 보는 주소를 출력하는 곳이 없으므로 **IP 기준 조회 한도(분당 120회)**로 본다. 요청마다 다른 위조 주소를 붙여 125번 보냈을 때 위조값이 통과하면 요청마다 다른 키가 돼 429가 없고, 무시되면 121번째부터 429다.

로컬 결과 (2026-10-21, 운영 compose, `API_DOMAIN=localhost`, `/api/v1/places/1111010100100010000`, 시나리오마다 api 재시작)

| 시나리오 | 결과 | 뜻 |
|---|---|---|
| A. Caddy 경유, 요청마다 다른 `X-Forwarded-For` 125번 | 404 120번, **429 5번** | 위조값 무시 — 실제 접속 주소 하나로 셌다 |
| B. Caddy 경유, `X-Forwarded-For`·`X-Real-IP`·`Forwarded` 모두 위조 125번 | 404 120번, **429 5번** | 위조값 무시 |
| C. 대조군: compose 네트워크 안(caddy 컨테이너)에서 api:8000으로 직접, 다른 위조값 125번 | 404 125번, 429 0번 | Caddy를 건너뛰면 위조가 통과한다 — 이 시험이 위조를 알아챌 수 있다는 확인 |
| D. 대조군: C와 같되 같은 위조값 125번 | 404 120번, 429 5번 | 직접 요청에서는 위조값이 키가 된다 |

C가 보여 주듯 `*`는 **compose 네트워크 안의 컨테이너**가 보낸 위조값도 믿는다. 이 네트워크에는 db·api·caddy만 있으므로 지금은 밖에서 위조할 길이 없다. 컨테이너를 더 붙이면 이 시험을 다시 한다.

VM 확인 (6단계 뒤, **로컬 터미널**에서 — 조회 한도를 1분 동안 다 쓰므로 공개 전에 한다):

```
for i in $(seq 1 125); do curl -s -o /dev/null -w '%{http_code}\n' -H "X-Forwarded-For: 203.0.113.$i" \
  https://<API 도메인>/api/v1/places/1111010100100010000; done | sort | uniq -c
```

확인할 출력: `120 404`와 `5 429`(DB에 그 PNU가 있으면 404 대신 200). 429가 없으면 위조값이 통과한 것이니 멈추고 알려 준다 — 그때는 compose 네트워크 대역만 믿도록 바꾼다.

## 8. 관리자 계정 (🧑)

```
dc run --rm api python -m jobs.set_admin_password <사용자명>
```

비밀번호를 두 번 입력한다(화면에 보이지 않는다). 확인할 출력: `관리자 계정 <사용자명>을(를) 만들었어요.` 비밀번호는 출력되지 않는다.

로그인 확인 — 비밀번호를 명령줄에 쓰지 않고 입력받는다(셸 기록·프로세스 목록에 남지 않는다). 비밀번호에 `"`나 `\`가 있으면 이 확인은 400이 나오니 그때는 알려 준다:

```
read -r -s -p 'password: ' PW; echo
printf '{"username":"%s","password":"%s"}' '<사용자명>' "$PW" | curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Content-Type: application/json' --data-binary @- https://<API 도메인>/admin/v1/login
printf '{"username":"%s","password":"%s"}' '<사용자명>' 'wrong-password-check' | curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Content-Type: application/json' --data-binary @- https://<API 도메인>/admin/v1/login
unset PW
```

확인할 출력: `200`, `401`. 틀린 비밀번호는 10분 안에 5번이면 잠기므로(docs/30 §3) 이 확인은 한 번만 한다.

## 9. 웹 (Vercel, 🧑)

Vercel 프로젝트의 루트 디렉터리는 `apps/web`. 환경 변수(Production):

| 이름 | 값 |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://<API 도메인>` (빌드 때 번들에 들어간다 — 바꾸면 다시 배포) |
| `API_INTERNAL_URL` | `https://<API 도메인>` (서버 렌더링) |
| `REVALIDATE_SECRET` | VM `.env`와 같은 값 |
| `NEXT_PUBLIC_KAKAO_JS_KEY` | 카카오 JavaScript 키. 카카오 개발자 콘솔에 `https://<웹 도메인>`을 사이트 도메인으로 등록 |
| `INDEXING_ENABLED` | `false` (Gate 1 전, docs/40 §9) |
| `SITE_URL` | `https://<웹 도메인>` |

배포 후 확인: 홈에서 주소 검색 → 필지 → 층 이력 페이지가 열리고, 방법론 페이지의 검색 정확도가 "아직 계산하지 않았어요"가 아니다. `https://<웹 도메인>/robots.txt`가 전체 차단이다(색인 꺼짐).

Vercel 대시보드의 런타임 로그에 남는 항목과 보관 기간(요금제)을 보고 docs/60 §5 "Vercel" 항목에 적는다(T-081 🧑).

## 10. CORS와 웹 재생성

```
curl -s -o /dev/null -D - -X OPTIONS -H 'Origin: https://<웹 도메인>' -H 'Access-Control-Request-Method: GET' \
  https://<API 도메인>/api/v1/health | grep -i '^access-control-allow-origin'
curl -s -o /dev/null -D - -X OPTIONS -H 'Origin: https://example.com' -H 'Access-Control-Request-Method: GET' \
  https://<API 도메인>/api/v1/health | grep -ci '^access-control-allow-origin'
dc run --rm -T api python -c "import asyncio; from app.admin.revalidate import revalidate; print(asyncio.run(revalidate(['/'], 0)))"
```

확인할 출력
- `access-control-allow-origin: https://<웹 도메인>`
- `0` (다른 출처에는 허용 헤더가 없다)
- `True` (웹의 `/api/revalidate`가 비밀 값을 받아들였다. `False`면 `WEB_REVALIDATE_URL`·`REVALIDATE_SECRET`이 Vercel과 다르다 — 경고 로그에 실패 종류만 있다)

## 11. cron

```
crontab -l
```

기존 줄을 본 뒤 `crontab -e`로 `deploy/crontab`의 줄을 붙인다. `GAGE_NAVI_DIR`과 `BACKUP_RCLONE_REMOTE`(rclone 원격 이름:경로)를 바꾼다. rclone 원격 설정(`rclone config`)은 저장소 업체의 안내를 따른다 — 설정 파일에 키가 들어가므로 출력하지 않는다.

처음 한 번은 손으로 돌려 본다:

```
BACKUP_RCLONE_REMOTE=<원격:경로> deploy/backup.sh
deploy/job.sh correction_maintenance
```

확인할 출력
- `backup gagenavi-YYYYMMDD-HHMM.dump N bytes`, `local kept 1`, `remote kept 1`
- `{"job": "correction_maintenance", "messages_purged": 0, "revalidation_pending": 0, "revalidated": 0}` (처음에는 모두 0)

다음 날 `~/gage-navi-backup.log`와 `~/gage-navi-jobs.log`에 cron이 돈 줄이 하나씩 있는지 본다.

## 12. 백업에서 복원 1회

VM 밖 저장소에서 내려받은 덤프로 복원한다(올라간 파일이 쓸 수 있는지까지 본다).

```
mkdir -p /tmp/restore-check
rclone copy <원격:경로>/gagenavi-YYYYMMDD-HHMM.dump /tmp/restore-check/
deploy/restore-check.sh /tmp/restore-check/gagenavi-YYYYMMDD-HHMM.dump
rm -r /tmp/restore-check
```

확인할 출력: 처음에 `NOTICE: database "gagenavi_restore_check" does not exist, skipping`이 나올 수 있다(정상). 표마다 `live`와 `restored`가 같고 `same yes`, `alembic live=0009_measure restored=0009_measure`, 마지막 줄 `result PASS`. 출력은 표 이름과 행 수뿐이다. 이 출력을 T-081 PR에 붙인다.

크기 참고 (로컬, 2026-10-21 — 5단계 적재 직후의 새 DB)

| 값 | 크기 |
|---|---|
| `pg_database_size` | 1,762,243,043 바이트 (약 1.64GiB). 가장 큰 표 `license_raw` 1.15GiB, `license_record` 384MiB |
| `pg_dump -Fc` 파일 | 144,738,786 바이트 (약 138MiB). 백업 12초, 복원 확인 35초 |
| 7일 보관 | 덤프 약 138MiB × 7 ≈ 0.95GiB (VM 안 `BACKUP_DIR`과 VM 밖 저장소 각각) |

인허가를 월 1회 다시 적재하면 `license_raw`에 새 스냅샷이 쌓이므로 DB와 덤프가 그만큼 커진다(오래된 스냅샷 정리는 아직 없다).

## 13. 배포 후 측정 카운터 (T-081을 마치는 날까지 매일)

운영자 기기는 먼저 `https://<웹 도메인>/privacy`에서 측정을 끈다.

```
deploy/job.sh measure_demand --start <배포일> --end <오늘> --daily-only
```

출력의 일별 값을 `reports/measure_prelaunch.md` 표에 옮긴다. 공개 알림 직전의 재확인은 docs/50 §7 Gate 1 체크리스트 항목이다.

## 월 1회 데이터 갱신

5단계의 인허가 세 줄(새 다운로드 폴더) → `normalize_licenses` → `flag_stale_suspects` → `build_history` → `compute_base_rates` 순서. 사람이 포털에서 내려받은 뒤 실행한다(ADR-025, 자동화는 제안 티켓 T-100).
