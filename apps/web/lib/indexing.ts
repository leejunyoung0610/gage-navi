/**
 * 검색 노출 설정 (docs/40 §9, T-035).
 *
 * `INDEXING_ENABLED`가 `"true"`이고 `SITE_URL`이 있을 때만 색인을 켠다. `SITE_URL`은 기본값이 없다
 * (운영 도메인은 T-081). 켜졌을 때 색인 허용은 기록 2건 이상인 층 페이지·홈·방법론뿐이고 나머지는 noindex.
 * 정적 페이지(홈)는 빌드 때 값으로 정해지므로 두 값을 빌드 인자와 실행 환경에 같이 준다(apps/web/Dockerfile).
 */
import type { Metadata } from "next";

/** 색인 허용: 기록(숨김 제외) 2건 이상인 층 (docs/40 §9). API 사이트맵 조건과 같은 값 */
export const MIN_RECORDS_FOR_INDEX = 2;

/** 사이트맵 파일 하나의 URL 수 상한 (docs/40 §9) */
export const SITEMAP_MAX_URLS = 50_000;

/** 색인이 켜졌으면 사이트 주소(끝의 `/` 없음), 아니면 `null`. http(s) 주소가 아니면 꺼진 것으로 본다 */
export function indexingSiteUrl(): string | null {
  if (process.env.INDEXING_ENABLED !== "true") return null;
  const value = process.env.SITE_URL?.trim();
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.href.replace(/\/+$/, "");
  } catch {
    return null;
  }
}

/** 페이지의 `robots` 메타. 색인이 꺼져 있거나 허용 범위 밖이면 noindex */
export function pageRobots(indexable: boolean): NonNullable<Metadata["robots"]> {
  const index = indexable && indexingSiteUrl() !== null;
  return { index, follow: index };
}

export function isIndexableFloor(recordCount: number): boolean {
  return recordCount >= MIN_RECORDS_FOR_INDEX;
}
