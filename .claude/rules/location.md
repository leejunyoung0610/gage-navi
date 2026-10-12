---
paths:
  - "services/api/app/location/**"
  - "services/api/app/address/**"
  - "services/api/jobs/**"
---

<!-- .cursor/rules/40-location.mdc 와 같은 내용. 수정 시 둘 다 고친다. -->

# 자리 이력 규칙

- 정본 문서: `docs/10-module-location.md`. 파서 규칙·정의를 바꾸면 문서와 `method_version`/`parse_version`을 함께 올린다.
- 표시·통계 단위는 층키 `(pnu, floor)`. 호실 추정 연결(`location/matching`)은 게이트 통과 전 API·화면에 노출 금지.
- 과거 폐업 횟수·3년 내 폐업·코호트·버킷 정의는 문서 §7.2 그대로. 표본 200 미만 버킷은 표시하지 않는다.
- `method_version='w0'` 재현 모드는 analysis 스크립트와 같은 결과를 내야 한다(docs/50 §3). 이 모드의 로직을 "개선"하지 않는다.
- 원천 CSV는 CP949, 주소에 줄바꿈이 있다. 줄 단위 처리 금지, `csv` 모듈 사용.
- 전화번호 컬럼은 `license_raw.payload`에만 존재. 정규화 테이블·응답·로그로 옮기지 않는다.
- 대용량 계산은 pandas/numpy 벡터화(정렬 + `searchsorted`). 행 단위 Python 루프로 서울 전체를 돌리지 않는다.
- 통계·모형 결과는 하드코딩하지 않고 `base_rate`, `model_card` 테이블에서 읽는다.
