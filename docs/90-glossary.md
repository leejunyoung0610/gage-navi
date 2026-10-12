# 90. 용어집

코드·문서·화면에서 같은 개념은 같은 이름을 쓴다. 새 용어는 여기에 먼저 추가한다.

| 한국어 (화면·문서) | 코드 식별자 | 정의 |
|---|---|---|
| 필지 | `pnu`, `parcel` | 지번 하나. PNU 19자리 = 법정동코드(10)+산 여부(1)+본번(4)+부번(4) |
| 층키 | `(pnu, floor)`, floor key | 자리 이력의 표시·통계 단위 (ADR-015·016) |
| 층 | `floor` | 정규화 값 `B9…B1`, `1…99`, `RF` |
| 호수 | `ho_list` | 신고 주소에 적힌 호 번호 목록 |
| 같은 호수로 신고된 기록 | `ho_groups` | `ho_list`를 공유하는 기록 묶음 |
| 업소 기록 | `license_record` | 인허가 1건(식품 3종 중 하나) |
| 식품 3종 | `food3` | 일반음식점 `general_restaurant`, 휴게음식점 `rest_restaurant`, 제과점영업 `bakery` |
| 폐업 처리 몰린 날 (문서에서는 폐업 처리 급증일) | `bulk_closure` | 한 관할에서 하루에 평소보다 훨씬 많은 폐업이 처리된 날의 기록(docs/10 §5). "행정 일괄 정리"라는 해석은 검증하지 못해 쓰지 않는다 (ADR-020) |
| 폐업 신고 지연 의심 (화면에서는 "같은 호수에 새 신고") | `stale_suspect` | 영업 중으로 남았지만 같은 층의 같은 호수로 이후 다른 업소가 개업한 기록. 면적만 같은 경우는 `stale_area_match`로 따로 두고 화면에 내지 않는다 (ADR-023, docs/10 §6) |
| 과거 폐업 횟수 | `prior_closures_floor` | 층키에서 해당 기록 개업 전에 폐업한 기록 수 |
| 3년 내 폐업 | `event`, `closed_within_3y` | 개업 후 1,095일 이내 폐업 |
| 기준율 | `base_rate` | 과거 폐업 횟수 버킷별 3년 내 폐업 비율 (Wilson 95% CI) |
| 모형 카드 | `model_card` | 방법론 페이지에 싣는 모형 결과·한계 |
| 기준일 | `as_of` | 판정·통계의 기준 날짜 (ADR-007) |
| 데이터 기준일 | `data_as_of`, `snapshot_label` | 데이터 스냅샷 날짜·월 |
| 사업장 프로필 | `BusinessProfile` | 사용자가 입력한 사업장 정보, 브라우저에만 저장 (ADR-014) |
| 사실 | `Facts`, fact key | 엔진 입력. 프로필을 변환한 값 (docs/20 §3) |
| 구간 사실 | interval fact | `[lo, hi]` 형태의 사실 (신용점수·매출·잔액) |
| 규칙 | `Rule` | 지원사업 1개의 DSL JSON |
| 지원사업·정책자금 사업 | `program` | 규칙의 대상. `program_id`는 연도 없는 안정 키 |
| 충족 / 불충족 / 확인 필요 | `MET` / `NOT_MET` / `UNKNOWN` | 3치 판정 (ADR-003) |
| 접수예정 / 접수중 / 마감 | `UPCOMING` / `OPEN` / `CLOSED` | 접수 상태 (ADR-009) |
| 조기 마감 가능 | `budget_limited` | 예산 소진 시 마감 |
| 결정 조건 | `decisive` | 판정을 결정한 조건 목록 |
| 입력하면 판정되는 정보 | `missing_facts` | UNKNOWN을 만든 비어 있는 사실 키 |
| 중복 신청 불가 / 중복 수혜 불가 | `scope: apply` / `scope: benefit` | 충돌 범위 (ADR-008) |
| 한도 그룹 | `cap_groups` | 여러 사업이 공유하는 합산 상한 |
| 한도 차감 | `limit_adjustments.deduct_balance` | 기존·앞선 배분액만큼 한도가 줄어드는 효과 |
| 계획 | `Plan` | 추천 조합 + 순서 + 배분액 |
| 필요 금액 충족안 | `need_cover` | 정책자금 기본 계획 (ADR-017) |
| 최대 한도 참고안 | `max_limit` | 참고용, 부채 경고 필수 |
| 지원액 최대안 / 확실성 우선안 | `max_benefit` / `certainty_first` | 폐업 지원 계획 |
| 근거 | `evidence`, `ev` | 공고 원문 인용·위치 |
| 법정 기한 레지스트리 | `legal_deadlines` | 조문 근거가 확인된 기한만 담은 코드 목록 |
| 검수 / 2차 검수 | `review_log.review_kind` = `approve` / `second_review` | 사람의 규칙 승인 / 첫 승인 24시간 이후 원문 재대조 |
| 변동금리 기준값 | `rate_base`, `rate_bases` | 관리자가 갱신하는 기준 금리, 엔진 입력 |
| 근거 조회 키 | `(program_id, rule_version, ev_key)` | 화면이 근거 시트를 여는 키 |
| 정답셋 dev/test | `eval_case.split` | 추출 평가 데이터 분할 |
| 게이트 | Gate 1·2·3 | 모듈 공개 조건 (docs/50 §7) |
