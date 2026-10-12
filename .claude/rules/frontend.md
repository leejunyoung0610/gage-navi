---
paths:
  - "apps/web/**"
---

<!-- .cursor/rules/20-frontend.mdc 와 같은 내용. 수정 시 둘 다 고친다. -->

# 프론트엔드 규칙

- Next.js 15 App Router, React 19, TypeScript strict. 화면 명세는 `docs/40-frontend.md`.
- `/place/**`, `/methodology`는 서버 컴포넌트 + ISR(`revalidate = 86400`). 마법사·결과는 클라이언트 컴포넌트.
- API 타입은 `lib/api/types.ts`(openapi-typescript 생성물)만 사용. 응답 타입을 손으로 정의하지 않는다. API 변경 시 `pnpm gen:api`.
- 서버 상태는 TanStack Query, 폼은 react-hook-form + zod.
- 사업장 프로필은 `lib/profile-store.ts`로만 읽고 쓴다(키 `gn.profile.v1`). `localStorage` 접근은 모두 try/catch, 실패해도 화면은 동작해야 한다.
- 문구: 해요체, 숫자·날짜·금액은 `lib/format.ts`만 사용. 금지 표현은 `docs/40-frontend.md` §6(`scripts/check_copy.py`가 검사).
- 판정 배지는 색 + 글자(충족/불충족/확인 필요). 색만으로 의미 전달 금지.
- 모바일 360px 기준으로 먼저 구현, 터치 영역 44px, 포커스 표시, 폼 라벨 필수.
- 브라우저 `alert`/`confirm`/`prompt` 금지 — 앱 내 모달·시트 사용.
- 지도 SDK는 지연 로딩. 층 페이지 JS 예산 170KB(gzip, 지도 제외).
- `INDEXING_ENABLED`가 `true`가 아니면 모든 페이지 `noindex`.
- 분석 이벤트에 프로필 값·주소·금액을 넣지 않는다.
